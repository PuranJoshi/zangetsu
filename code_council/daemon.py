"""FastAPI daemon for Code Council web UI.

Provides HTTP + WebSocket + SSE endpoints that wrap the existing headless
pipeline modules (framer, advisors, synthesizer, context scanner).  The
CLI remains the primary interface; this daemon is an optional companion
launched via ``bankai serve``.

Binds to 127.0.0.1 only.  No authentication for MVP (local-only tool).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str = "ok"


class CouncilStreamRequest(BaseModel):
    """Start the advisor + synthesis pipeline after framing is done."""
    plan_id: str
    change_description: str
    framed_requirement: dict[str, Any]
    project_context: dict[str, Any] | None = None
    base_plan_id: str | None = None  # original plan being re-advised


class ScanTreeRequest(BaseModel):
    project_path: str


class ScanDiscoverRequest(BaseModel):
    project_path: str
    change_description: str
    max_files: int = 20


class ScanApproveRequest(BaseModel):
    project_path: str
    approved_paths: list[str]
    config_files: list[str] | None = None


class ResumeRequest(BaseModel):
    load_id: str


class ReviewInitRequest(BaseModel):
    """Initialise a review session: create transcript, return new plan_id."""
    base_plan_id: str
    change_description: str
    feedback: str


class ReviewActionRequest(BaseModel):
    """Submit a review action for a synthesized plan.

    Actions:
        approve    -- accept the current plan
        re-advise  -- re-run advisors with feedback, then re-synthesize
        reject     -- discard the plan
    """
    plan_id: str
    change_description: str
    framed_requirement: dict[str, Any]
    project_context: dict[str, Any] | None = None
    action: str  # "approve" | "re-advise" | "reject"
    feedback: str = ""  # required when action is "re-advise"
    advisor_responses: dict[str, str] | None = None  # current advisor responses
    base_plan_id: str | None = None  # original plan being re-advised


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Code Council",
    description="Multi-advisor code planning API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5176",
        "http://127.0.0.1:5176",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> HealthResponse:
    return HealthResponse()


# ---------------------------------------------------------------------------
# WebSocket: interactive framer interview
# ---------------------------------------------------------------------------

_MAX_FRAMER_ROUNDS = 8

# System prompt for the web framer -- instructs LLM to produce JSON
_WEB_FRAMER_SYSTEM = """\
You are the Requirements Framer for a Code Council.  Your job is to
interview the user so the council has enough context to produce a
high-quality implementation plan.

You will receive the user's raw feature request.  Decide whether it needs
clarification.  If it does, ask ONE follow-up question at a time.

## Output format

You MUST respond in valid JSON.  Two possible shapes:

### 1. When you need more context (ask a question):
```json
{{
  "type": "question",
  "question": "Your single, focused question here",
  "choices": ["Option A", "Option B", "Option C"]
}}
```
- Ask exactly ONE question per turn.
- Provide 3-5 short choices that cover the most likely answers.
- The user can always type a custom answer instead of picking a choice.
- Keep choices short (under 10 words each).

### 2. When you have enough context (produce the framed requirement):
Produce a structured JSON requirement in this exact format:
```json
{{
  "type": "framed",
  "framed_requirement": {{
    "type": "epic|story|task|bug",
    "title": "Short descriptive title",
    "description": "What this change does and why",
    "acceptance_criteria": ["Given/When/Then..."],
    "out_of_scope": ["..."],
    "assumptions": ["..."],
    "clarifications_needed": [],
    "stories": [
      {{
        "type": "story",
        "title": "Sub-story title",
        "description": "...",
        "acceptance_criteria": ["..."],
        "out_of_scope": [],
        "assumptions": [],
        "clarifications_needed": [],
        "stories": []
      }}
    ]
  }}
}}
```

## Rules
- Be conversational and concise.
- Ask only what is genuinely missing.  Do not ask for the sake of asking.
- Never give advice or opinions -- you are gathering context, not advising.
- If the request is already clear enough, skip straight to framing.
- Maximum {max_rounds} rounds of questions.  After that, frame with what you have.
- When the user says "done" / "skip" / "just go", produce the framed output.
- Output ONLY the JSON object.  No markdown fences, no extra text.
"""


def _parse_framer_json(raw: str) -> dict | None:
    """Parse the framer's JSON response, stripping markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


async def _force_frame(llm, messages: list[dict[str, str]]) -> dict | None:
    """Force the LLM to produce a framed requirement."""
    messages.append({
        "role": "user",
        "content": (
            "You have asked enough questions.  Now produce the final "
            "framed requirement using the 'framed' JSON format.  "
            "Use all the context gathered so far."
        ),
    })
    raw = await llm.chat(messages)
    return _parse_framer_json(raw)


@app.websocket("/ws/framer")
async def ws_framer(ws: WebSocket) -> None:
    """Interactive framer interview over WebSocket.

    Protocol:
      Client sends:
        {"type": "question", "text": "...", "request_id": "..."}  (start)
        {"type": "reply", "text": "...", "msg_id": "..."}         (answer)
        {"type": "skip"}                                           (skip)

      Server sends:
        {"type": "framer_question", "question": "...",
         "choices": [...], "msg_id": "..."}                        (follow-up)
        {"type": "framed", "framed_requirement": {...},
         "request_id": "..."}                                      (done)
        {"type": "error", "message": "..."}                        (error)
    """
    await ws.accept()

    try:
        from code_council.config import get_settings
        from code_council.llm import get_llm

        settings = get_settings()
        settings.require_langdock()
        llm = get_llm(settings)
    except Exception as exc:
        await ws.send_json({"type": "error", "message": str(exc)})
        await ws.close()
        return

    request_id: str | None = None
    _msg_seq = 0

    try:
        # Wait for initial question
        init_data = await ws.receive_json()
        if init_data.get("type") != "question":
            await ws.send_json({
                "type": "error",
                "message": "Expected initial message with type 'question'",
            })
            await ws.close()
            return

        user_question = init_data.get("text", "").strip()
        request_id = init_data.get("request_id") or uuid.uuid4().hex[:12]

        if not user_question:
            await ws.send_json({
                "type": "error",
                "message": "Empty question text",
            })
            await ws.close()
            return

        # Build LLM conversation
        system_prompt = _WEB_FRAMER_SYSTEM.format(max_rounds=_MAX_FRAMER_ROUNDS)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_question},
        ]

        # Interview loop
        for round_num in range(_MAX_FRAMER_ROUNDS):
            raw = await llm.chat(messages)
            messages.append({"role": "assistant", "content": raw})

            parsed = _parse_framer_json(raw)

            if parsed is None:
                # Unparseable -- try to send as a plain question
                _msg_seq += 1
                await ws.send_json({
                    "type": "framer_question",
                    "question": raw,
                    "choices": [],
                    "msg_id": str(_msg_seq),
                })
            elif parsed.get("type") == "framed":
                # Done -- send the framed requirement
                framed_req = parsed.get("framed_requirement", parsed)
                await ws.send_json({
                    "type": "framed",
                    "framed_requirement": framed_req,
                    "request_id": request_id,
                })
                await ws.close()
                return
            elif parsed.get("type") == "question":
                _msg_seq += 1
                await ws.send_json({
                    "type": "framer_question",
                    "question": parsed.get("question", ""),
                    "choices": parsed.get("choices", []),
                    "msg_id": str(_msg_seq),
                })
            else:
                # Unknown type -- treat as done if it looks like a requirement
                if "title" in parsed and "description" in parsed:
                    await ws.send_json({
                        "type": "framed",
                        "framed_requirement": parsed,
                        "request_id": request_id,
                    })
                    await ws.close()
                    return

                _msg_seq += 1
                await ws.send_json({
                    "type": "framer_question",
                    "question": str(parsed),
                    "choices": [],
                    "msg_id": str(_msg_seq),
                })

            # Wait for user reply
            pending_msg_id = str(_msg_seq)
            while True:
                try:
                    reply_data = await ws.receive_json()
                except WebSocketDisconnect:
                    return

                if reply_data.get("type") == "skip":
                    # Force-frame with what we have
                    result = await _force_frame(llm, messages)
                    if result and result.get("type") == "framed":
                        framed_req = result.get("framed_requirement", result)
                    elif result and "title" in result:
                        framed_req = result
                    else:
                        # Fallback: use the raw question as the requirement
                        framed_req = {
                            "type": "story",
                            "title": user_question[:80],
                            "description": user_question,
                            "acceptance_criteria": [],
                            "out_of_scope": [],
                            "assumptions": [],
                            "clarifications_needed": [],
                            "stories": [],
                        }
                    await ws.send_json({
                        "type": "framed",
                        "framed_requirement": framed_req,
                        "request_id": request_id,
                    })
                    await ws.close()
                    return

                if reply_data.get("type") == "reply":
                    # Filter stale replies
                    if reply_data.get("msg_id") != pending_msg_id:
                        continue
                    reply_text = reply_data.get("text", "").strip()
                    if reply_text:
                        messages.append({"role": "user", "content": reply_text})
                    break

        # Max rounds reached -- force frame
        result = await _force_frame(llm, messages)
        if result:
            framed_req = result.get("framed_requirement", result)
        else:
            framed_req = {
                "type": "story",
                "title": user_question[:80],
                "description": user_question,
                "acceptance_criteria": [],
                "out_of_scope": [],
                "assumptions": [],
                "clarifications_needed": [],
                "stories": [],
            }
        await ws.send_json({
            "type": "framed",
            "framed_requirement": framed_req,
            "request_id": request_id,
        })
        await ws.close()

    except WebSocketDisconnect:
        logger.info("Framer WS disconnected (request_id=%s)", request_id)
    except Exception as exc:
        logger.exception("Framer WS error (request_id=%s)", request_id)
        try:
            await ws.send_json({"type": "error", "message": str(exc)})
            await ws.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# SSE: council pipeline stream (advisors + synthesis)
# ---------------------------------------------------------------------------


def _sse_event(stage: str, status: str, data: dict | None = None) -> str:
    """Format a single SSE event."""
    payload = {"stage": stage, "status": status}
    if data:
        payload["data"] = data
    return f"data: {json.dumps(payload)}\n\n"


@app.post("/council/stream")
async def council_stream(req: CouncilStreamRequest) -> StreamingResponse:
    """Run the advisor + synthesis pipeline as an SSE stream.

    Expects the framed requirement (from the WS framer or direct input)
    and optional project context.  Emits stage events as advisors
    complete and the plan is synthesized.
    """
    try:
        from code_council.config import get_settings
        from code_council.llm import get_llm

        settings = get_settings()
        settings.require_langdock()
        llm = get_llm(settings)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc)},
        )

    async def _generate():
        from code_council.advisors import run_advisors, discover_advisor_skills
        from code_council.context import ProjectContext
        from code_council.synthesizer import synthesize_plan
        from code_council.framer import FramedRequirement

        plan_id = req.plan_id
        change_description = req.change_description

        # Reconstruct the framed requirement
        try:
            framed = FramedRequirement(**req.framed_requirement)
        except Exception as exc:
            yield _sse_event("session", "error", {"message": f"Invalid framed requirement: {exc}"})
            return

        # Build project context
        if req.project_context:
            try:
                ctx = ProjectContext(**req.project_context)
            except Exception:
                ctx = ProjectContext(project_path="(none)")
        else:
            ctx = ProjectContext(project_path="(none)")

        # Session started
        yield _sse_event("session", "started", {"plan_id": plan_id})

        # Discover advisor names for the frontend
        skills = discover_advisor_skills()
        advisor_names = [s.display_name for s in skills]
        yield _sse_event("advisors", "started", {"advisor_names": advisor_names})

        # Run all advisors in parallel, but emit events as each completes
        # We use individual tasks instead of gather so we can stream results
        total = len(skills)
        advisor_responses: dict[str, str] = {}

        async def _run_one(skill_name: str) -> tuple[str, str]:
            """Run advisors via the existing parallel function."""
            # We re-use run_advisors which does gather internally
            # But we need individual results, so we run tasks individually
            pass

        # Actually run them all in parallel via run_advisors
        t0 = time.monotonic()
        try:
            responses, params, timing = await run_advisors(
                change_description=change_description,
                context=ctx,
                llm=llm,
                plan_id=plan_id,
                temperature_spread=settings.code_council_advisor_temperature_spread,
            )
            advisor_responses = responses
        except Exception as exc:
            yield _sse_event("session", "error", {"message": f"Advisor error: {exc}"})
            return

        # Emit individual advisor completions
        for name, response in advisor_responses.items():
            yield _sse_event("advisor", "completed", {
                "name": name,
                "response": response,
            })

        advisor_duration = round(time.monotonic() - t0, 3)

        # Synthesis phase
        yield _sse_event("synthesis", "started", {})

        try:
            plan = await synthesize_plan(
                change_description=change_description,
                advisor_responses=advisor_responses,
                context=ctx,
                plan_id=plan_id,
                llm=llm,
            )
        except Exception as exc:
            yield _sse_event("session", "error", {"message": f"Synthesis error: {exc}"})
            return

        yield _sse_event("synthesis", "completed", {
            "plan": plan.model_dump(),
        })

        # Save the plan
        try:
            from code_council.storage import save_plan
            save_plan(
                plan_id=plan_id,
                change_description=change_description,
                plan_data=plan.model_dump(),
                state_data={"status": "completed"},
                advisor_responses=advisor_responses,
                context_summary=ctx.summary or "",
                framed_requirement=framed.model_dump(),
                base_plan_id=req.base_plan_id,
                settings=settings,
            )
        except Exception as exc:
            logger.warning("Failed to save plan: %s", exc)

        total_duration = round(time.monotonic() - t0, 3)
        yield _sse_event("session", "completed", {
            "plan_id": plan_id,
            "duration": total_duration,
            "advisor_duration": advisor_duration,
        })

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# REST: initialise a review session (transcript + new plan_id)
# ---------------------------------------------------------------------------


@app.post("/council/review/init")
async def init_review_session(req: ReviewInitRequest) -> dict:
    """Create a review transcript and return a fresh plan_id.

    Called by the frontend before starting the SSE re-advise stream.
    Generates a new plan_id (server-side), creates a transcript with
    ``status="review"`` and ``base_plan_id`` pointing to the original
    plan, copies framer context from the original transcript, and
    appends the re-advise feedback as a new message.
    """
    from code_council.config import get_settings
    from code_council.transcript import (
        init_transcript,
        load_transcript,
        append_framer_message,
        set_framed_question,
    )
    from code_council.utils import generate_plan_id

    settings = get_settings()

    # Generate a fresh plan_id with a new hex prefix + slug
    new_plan_id = generate_plan_id(req.change_description)

    # Load original transcript for context (if it exists)
    original_transcript = load_transcript(
        req.base_plan_id,
        transcript_dir=settings.transcript_path,
    )

    # Create the new review transcript
    init_transcript(
        plan_id=new_plan_id,
        question=req.change_description,
        transcript_dir=settings.transcript_path,
        base_plan_id=req.base_plan_id,
        status="review",
    )

    # Copy framer_messages from the original transcript (if available)
    if original_transcript:
        for msg in original_transcript.get("framer_messages", []):
            append_framer_message(
                plan_id=new_plan_id,
                role=msg.get("role", "user"),
                text=msg.get("text", ""),
                msg_id=msg.get("msg_id"),
                choices=msg.get("choices"),
                transcript_dir=settings.transcript_path,
            )
        framed_q = original_transcript.get("framed_question")
        if framed_q:
            set_framed_question(
                plan_id=new_plan_id,
                framed_question=framed_q,
                transcript_dir=settings.transcript_path,
            )

    # Append the re-advise feedback as a new user message
    append_framer_message(
        plan_id=new_plan_id,
        role="user",
        text=f"[RE-ADVISE FEEDBACK]: {req.feedback}",
        transcript_dir=settings.transcript_path,
    )

    # Also load the original plan to get the framed_requirement if the
    # transcript didn't have a framed_question.
    framed_requirement = None
    from code_council.storage import load_plan
    original_plan = load_plan(req.base_plan_id, settings=settings)
    if original_plan and original_plan.get("framed_requirement"):
        framed_requirement = original_plan["framed_requirement"]

    return {
        "plan_id": new_plan_id,
        "base_plan_id": req.base_plan_id,
        "framed_question": (
            original_transcript.get("framed_question")
            if original_transcript
            else None
        ),
        "framed_requirement": framed_requirement,
    }


# ---------------------------------------------------------------------------
# SSE: review action (re-advise with feedback)
# ---------------------------------------------------------------------------


@app.post("/council/review")
async def council_review(req: ReviewActionRequest) -> StreamingResponse:
    """Handle a plan review action as an SSE stream.

    Supports three actions:
        approve    -- returns a simple completion event
        re-advise  -- re-runs advisors with feedback, re-synthesizes, streams progress
        reject     -- returns a rejection event
    """
    try:
        from code_council.config import get_settings
        from code_council.llm import get_llm

        settings = get_settings()
        settings.require_langdock()
        llm = get_llm(settings)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc)},
        )

    async def _generate():
        from code_council.advisors import run_advisors, discover_advisor_skills
        from code_council.context import ProjectContext
        from code_council.synthesizer import synthesize_plan

        plan_id = req.plan_id
        change_description = req.change_description

        if req.action == "approve":
            yield _sse_event("review", "approved", {"plan_id": plan_id})
            return

        if req.action == "reject":
            yield _sse_event("review", "rejected", {"plan_id": plan_id})
            return

        if req.action != "re-advise":
            yield _sse_event("session", "error", {
                "message": f"Unknown review action: {req.action}",
            })
            return

        # -- Re-advise: re-run advisors with feedback -----------------------

        if not req.feedback.strip():
            yield _sse_event("session", "error", {
                "message": "Feedback is required for re-advise action.",
            })
            return

        # Build project context
        if req.project_context:
            try:
                ctx = ProjectContext(**req.project_context)
            except Exception:
                ctx = ProjectContext(project_path="(none)")
        else:
            ctx = ProjectContext(project_path="(none)")

        yield _sse_event("review", "started", {
            "plan_id": plan_id,
            "action": "re-advise",
            "feedback": req.feedback,
        })

        # Discover advisor names
        skills = discover_advisor_skills()
        advisor_names = [s.display_name for s in skills]
        yield _sse_event("advisors", "started", {"advisor_names": advisor_names})

        # Re-run advisors with negotiation feedback
        t0 = time.monotonic()
        try:
            responses, params, timing = await run_advisors(
                change_description=change_description,
                context=ctx,
                llm=llm,
                plan_id=plan_id,
                temperature_spread=settings.code_council_advisor_temperature_spread,
                negotiation_feedback=req.feedback,
            )
        except Exception as exc:
            yield _sse_event("session", "error", {
                "message": f"Advisor error: {exc}",
            })
            return

        for name, response in responses.items():
            yield _sse_event("advisor", "completed", {
                "name": name,
                "response": response,
            })

        # Re-synthesize
        yield _sse_event("synthesis", "started", {})

        try:
            plan = await synthesize_plan(
                change_description=change_description,
                advisor_responses=responses,
                context=ctx,
                plan_id=plan_id,
                llm=llm,
            )
        except Exception as exc:
            yield _sse_event("session", "error", {
                "message": f"Synthesis error: {exc}",
            })
            return

        yield _sse_event("synthesis", "completed", {
            "plan": plan.model_dump(),
        })

        # Save updated plan
        try:
            from code_council.storage import save_plan
            from code_council.framer import FramedRequirement

            framed = FramedRequirement(**req.framed_requirement)
            save_plan(
                plan_id=plan_id,
                change_description=change_description,
                plan_data=plan.model_dump(),
                state_data={"status": "reviewing"},
                advisor_responses=responses,
                context_summary=ctx.summary or "",
                framed_requirement=framed.model_dump(),
                base_plan_id=req.base_plan_id,
                settings=settings,
            )
        except Exception as exc:
            logger.warning("Failed to save reviewed plan: %s", exc)

        total_duration = round(time.monotonic() - t0, 3)
        yield _sse_event("session", "completed", {
            "plan_id": plan_id,
            "duration": total_duration,
        })

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# REST: project scanning
# ---------------------------------------------------------------------------


@app.post("/scan/tree")
async def scan_tree(req: ScanTreeRequest) -> dict:
    """Scan a project directory and return tree + tech stack."""
    from code_council.context import (
        build_directory_tree, find_config_files,
        detect_tech_stack, detect_test_patterns,
    )

    root = Path(req.project_path).resolve()
    if ".." in str(root):
        raise HTTPException(status_code=400, detail="Invalid project path")
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    tree = build_directory_tree(root)
    configs = find_config_files(root)
    tech = detect_tech_stack(root, configs)
    tests = detect_test_patterns(root, tech)

    return {
        "project_path": str(root),
        "directory_tree": tree,
        "tech_stack": tech.model_dump(),
        "test_patterns": tests.model_dump(),
        "config_files": list(configs.keys()),
    }


@app.post("/scan/discover")
async def scan_discover(req: ScanDiscoverRequest) -> dict:
    """Discover relevant files without reading their contents."""
    from code_council.context import discover_relevant_paths

    root = Path(req.project_path).resolve()
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    paths = discover_relevant_paths(root, req.change_description, req.max_files)

    return {
        "discovered_files": [
            {"path": p, "score": s, "is_sensitive": sens}
            for p, s, sens in paths
        ],
    }


@app.post("/scan/approve")
async def scan_approve(req: ScanApproveRequest) -> dict:
    """Read approved files and return their contents + full context."""
    from code_council.context import (
        read_approved_files, find_config_files,
        detect_tech_stack, detect_test_patterns,
        build_directory_tree, ProjectContext,
    )

    root = Path(req.project_path).resolve()
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    # Read approved source files
    relevant_files = read_approved_files(root, req.approved_paths)

    # Read config files if specified
    all_configs = find_config_files(root)
    if req.config_files:
        config_contents = {
            k: v for k, v in all_configs.items() if k in req.config_files
        }
    else:
        config_contents = all_configs

    tech = detect_tech_stack(root, config_contents)
    tests = detect_test_patterns(root, tech)
    tree = build_directory_tree(root)

    ctx = ProjectContext(
        project_path=str(root),
        directory_tree=tree,
        tech_stack=tech,
        config_files=config_contents,
        relevant_files=relevant_files,
        test_patterns=tests,
    )

    return {
        "project_context": ctx.model_dump(),
        "files_read": len(relevant_files),
    }


# ---------------------------------------------------------------------------
# REST: plans and transcripts
# ---------------------------------------------------------------------------


@app.get("/plans")
async def list_plans(limit: int = 20) -> list[dict]:
    """List recent plans."""
    from code_council.storage import list_recent_plans
    return list_recent_plans(limit=limit)


@app.get("/plans/{plan_id}")
async def get_plan(plan_id: str) -> dict:
    """Get a full plan by ID."""
    from code_council.storage import load_plan
    data = load_plan(plan_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return data


@app.get("/transcripts")
async def list_transcripts(limit: int = 20) -> list:
    """List recent transcripts (summary metadata only)."""
    from code_council.config import get_settings
    from code_council.transcript import list_recent_transcripts

    settings = get_settings()
    return list_recent_transcripts(
        limit=limit,
        transcript_dir=settings.transcript_path,
    )


@app.get("/transcripts/{plan_id}")
async def get_transcript(plan_id: str) -> dict:
    """Get a full transcript by ID."""
    from code_council.transcript import load_transcript
    data = load_transcript(plan_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return data


# ---------------------------------------------------------------------------
# REST: resume from plan/transcript
# ---------------------------------------------------------------------------


@app.post("/council/resume")
async def resume_session(req: ResumeRequest) -> dict:
    """Resolve a plan or transcript ID and return resume context."""
    from code_council.config import get_settings

    settings = get_settings()

    # Re-use the CLI's resolve logic by importing its internals
    from code_council.storage import load_plan
    from code_council.transcript import load_transcript

    # Try plan first
    plan_data = load_plan(req.load_id, settings=settings)
    if plan_data is not None:
        return {
            "source": "plan",
            "plan_id": req.load_id,
            "data": plan_data,
        }

    # Try transcript
    transcript_data = load_transcript(
        req.load_id,
        transcript_dir=settings.transcript_path,
    )
    if transcript_data is not None:
        return {
            "source": "transcript",
            "plan_id": req.load_id,
            "data": transcript_data,
        }

    raise HTTPException(
        status_code=404,
        detail=f"No plan or transcript found for '{req.load_id}'",
    )
