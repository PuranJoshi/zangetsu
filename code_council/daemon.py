"""FastAPI daemon for Code Council web UI.

Provides HTTP + WebSocket + SSE endpoints that wrap the existing headless
pipeline modules (framer, advisors, synthesizer, context scanner).  The
CLI remains the primary interface; this daemon is an optional companion
launched via ``bankai serve``.

Binds to 127.0.0.1 only.  No authentication for MVP (local-only tool).
"""

from __future__ import annotations

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
    prior_token_usage: dict[str, Any] | None = None  # cumulative tokens from earlier stages


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


class ScanPromptRequest(BaseModel):
    """Generate an AI prompt for producing project context externally."""

    change_description: str
    framed_requirement: dict[str, Any] | None = None


class ScanUploadRequest(BaseModel):
    """Accept a raw ProjectContext JSON produced by an external AI tool."""

    project_context: dict[str, Any]


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
    prior_token_usage: dict[str, Any] | None = None  # cumulative tokens from earlier stages


class CouncilFeedbackRequest(BaseModel):
    """Request a council review: each advisor reviews the plan, then
    Business+Architect decide which recommendations to keep."""

    plan_id: str
    plan_data: dict[str, Any]
    prior_token_usage: dict[str, Any] | None = None  # cumulative tokens from earlier stages


class CouncilApplyRequest(BaseModel):
    """Apply user-approved council recommendations and re-synthesize.

    The user reviews the decision gate output, overrides decisions as
    needed, and submits only the accepted changes for re-synthesis.
    """

    plan_id: str
    change_description: str
    framed_requirement: dict[str, Any]
    project_context: dict[str, Any] | None = None
    accepted_changes: list[str]  # list of recommendation text strings to apply
    base_plan_id: str | None = None
    prior_token_usage: dict[str, Any] | None = None  # cumulative tokens from earlier stages


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


async def _force_frame(llm, messages: list[dict[str, str]]) -> tuple[dict | None, dict]:
    """Force the LLM to produce a framed requirement.

    Returns ``(parsed_json, token_usage_dict)``.
    """
    from code_council.config import get_skill_model

    framer_model = get_skill_model("framer") or None
    messages.append(
        {
            "role": "user",
            "content": (
                "You have asked enough questions.  Now produce the final "
                "framed requirement using the 'framed' JSON format.  "
                "Use all the context gathered so far."
            ),
        }
    )
    result = await llm.chat_with_usage(messages, model=framer_model)
    return _parse_framer_json(result.text), result.usage.to_dict()


@app.websocket("/ws/framer")
async def ws_framer(ws: WebSocket) -> None:
    """Interactive framer interview over WebSocket.

    Protocol:
      Client sends:
        {"type": "question", "text": "...", "plan_id": "...",
         "request_id": "..."}                                      (start)
        {"type": "reply", "text": "...", "msg_id": "..."}         (answer)
        {"type": "skip"}                                           (skip)

      Server sends:
        {"type": "framer_question", "question": "...",
         "choices": [...], "msg_id": "...", "plan_id": "..."}     (follow-up)
        {"type": "framed", "framed_requirement": {...},
         "request_id": "...", "plan_id": "..."}                    (done)
        {"type": "error", "message": "..."}                        (error)

    Transcript persistence:
      The server creates a transcript at the start of the session
      (using the ``plan_id`` from the initial message, or generating one).
      Each framer question and user reply is appended. The final framed
      requirement is recorded as ``framed_question``.  This ensures
      web-UI sessions have the same transcript history as CLI sessions.
    """
    await ws.accept()

    try:
        from code_council.config import get_settings, get_skill_model
        from code_council.llm import TokenUsage, get_llm

        settings = get_settings()
        settings.require_llm_credentials()
        llm = get_llm(settings)
    except Exception as exc:
        await ws.send_json({"type": "error", "message": str(exc)})
        await ws.close()
        return

    request_id: str | None = None
    plan_id: str | None = None
    _msg_seq = 0
    _framing_usage = TokenUsage()

    # Helper: persist framer question to transcript
    def _save_framer_msg(question: str, msg_id: str, choices: list[str] | None = None):
        if not plan_id:
            return
        try:
            from code_council.transcript import append_framer_message

            append_framer_message(
                plan_id=plan_id,
                role="framer",
                text=question,
                msg_id=msg_id,
                choices=choices or None,
                transcript_dir=settings.transcript_path,
            )
        except Exception as exc:
            logger.warning("Failed to save framer message: %s", exc)

    # Helper: persist user reply to transcript
    def _save_user_msg(text: str, msg_id: str | None = None):
        if not plan_id:
            return
        try:
            from code_council.transcript import append_framer_message

            append_framer_message(
                plan_id=plan_id,
                role="user",
                text=text,
                msg_id=msg_id,
                transcript_dir=settings.transcript_path,
            )
        except Exception as exc:
            logger.warning("Failed to save user message: %s", exc)

    # Helper: persist token usage to transcript
    def _save_framing_tokens():
        if not plan_id:
            return
        try:
            from code_council.transcript import update_token_usage

            usage_dict = _framing_usage.to_dict()
            update_token_usage(
                plan_id=plan_id,
                token_usage={
                    "stages": {"framing": usage_dict},
                    "total": usage_dict,
                },
                transcript_dir=settings.transcript_path,
            )
        except Exception as exc:
            logger.warning("Failed to save framing token usage: %s", exc)

    # Helper: persist the framed requirement text to transcript
    def _save_framed(framed_req: dict):
        if not plan_id:
            return
        try:
            from code_council.transcript import set_framed_question

            # Store a compact summary as framed_question
            title = framed_req.get("title", "")
            desc = framed_req.get("description", "")
            summary = f"{title}: {desc}" if title else desc
            set_framed_question(
                plan_id=plan_id,
                framed_question=summary[:500],
                transcript_dir=settings.transcript_path,
            )
        except Exception as exc:
            logger.warning("Failed to save framed question: %s", exc)

    try:
        # Wait for initial question
        init_data = await ws.receive_json()
        if init_data.get("type") != "question":
            await ws.send_json(
                {
                    "type": "error",
                    "message": "Expected initial message with type 'question'",
                }
            )
            await ws.close()
            return

        user_question = init_data.get("text", "").strip()
        request_id = init_data.get("request_id") or uuid.uuid4().hex[:12]

        # Accept or generate plan_id for transcript persistence
        plan_id = init_data.get("plan_id") or None
        if not plan_id:
            from code_council.utils import generate_plan_id

            plan_id = generate_plan_id(user_question)

        if not user_question:
            await ws.send_json(
                {
                    "type": "error",
                    "message": "Empty question text",
                }
            )
            await ws.close()
            return

        # Create transcript for this framing session
        try:
            from code_council.transcript import init_transcript

            init_transcript(
                plan_id=plan_id,
                question=user_question,
                transcript_dir=settings.transcript_path,
            )
            _save_user_msg(user_question)
        except Exception as exc:
            logger.warning("Failed to init transcript: %s", exc)

        # Build LLM conversation with cache-aware system message.
        # For Anthropic, we add cache_control breakpoints to the system
        # message so the framer instructions are cached across rounds.
        system_text = _WEB_FRAMER_SYSTEM.format(max_rounds=_MAX_FRAMER_ROUNDS)
        if settings.code_council_prompt_caching and settings.is_anthropic_provider():
            system_msg: dict = {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": system_text,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        else:
            system_msg = {"role": "system", "content": system_text}
        messages: list[dict] = [
            system_msg,
            {"role": "user", "content": user_question},
        ]

        # Interview loop
        framer_model = get_skill_model("framer") or None
        for round_num in range(_MAX_FRAMER_ROUNDS):
            chat_result = await llm.chat_with_usage(messages, model=framer_model)
            raw = chat_result.text
            _framing_usage += chat_result.usage
            _save_framing_tokens()
            messages.append({"role": "assistant", "content": raw})

            parsed = _parse_framer_json(raw)

            if parsed is None:
                # Unparseable -- try to send as a plain question
                _msg_seq += 1
                _save_framer_msg(raw, str(_msg_seq))
                await ws.send_json(
                    {
                        "type": "framer_question",
                        "question": raw,
                        "choices": [],
                        "msg_id": str(_msg_seq),
                        "plan_id": plan_id,
                        "token_usage": _framing_usage.to_dict(),
                    }
                )
            elif parsed.get("type") == "framed":
                # Done -- send the framed requirement
                framed_req = parsed.get("framed_requirement", parsed)
                _save_framed(framed_req)
                await ws.send_json(
                    {
                        "type": "framed",
                        "framed_requirement": framed_req,
                        "request_id": request_id,
                        "plan_id": plan_id,
                        "token_usage": _framing_usage.to_dict(),
                    }
                )
                await ws.close()
                return
            elif parsed.get("type") == "question":
                _msg_seq += 1
                q_text = parsed.get("question", "")
                q_choices = parsed.get("choices", [])
                _save_framer_msg(q_text, str(_msg_seq), q_choices)
                await ws.send_json(
                    {
                        "type": "framer_question",
                        "question": q_text,
                        "choices": q_choices,
                        "msg_id": str(_msg_seq),
                        "plan_id": plan_id,
                        "token_usage": _framing_usage.to_dict(),
                    }
                )
            else:
                # Unknown type -- treat as done if it looks like a requirement
                if "title" in parsed and "description" in parsed:
                    _save_framed(parsed)
                    await ws.send_json(
                        {
                            "type": "framed",
                            "framed_requirement": parsed,
                            "request_id": request_id,
                            "plan_id": plan_id,
                            "token_usage": _framing_usage.to_dict(),
                        }
                    )
                    await ws.close()
                    return

                _msg_seq += 1
                _save_framer_msg(str(parsed), str(_msg_seq))
                await ws.send_json(
                    {
                        "type": "framer_question",
                        "question": str(parsed),
                        "choices": [],
                        "msg_id": str(_msg_seq),
                        "plan_id": plan_id,
                        "token_usage": _framing_usage.to_dict(),
                    }
                )

            # Wait for user reply
            pending_msg_id = str(_msg_seq)
            while True:
                try:
                    reply_data = await ws.receive_json()
                except WebSocketDisconnect:
                    return

                if reply_data.get("type") == "skip":
                    # Force-frame with what we have
                    result, force_usage = await _force_frame(llm, messages)
                    _framing_usage += TokenUsage(**force_usage)
                    _save_framing_tokens()
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
                    _save_framed(framed_req)
                    await ws.send_json(
                        {
                            "type": "framed",
                            "framed_requirement": framed_req,
                            "request_id": request_id,
                            "plan_id": plan_id,
                            "token_usage": _framing_usage.to_dict(),
                        }
                    )
                    await ws.close()
                    return

                if reply_data.get("type") == "reply":
                    # Filter stale replies
                    if reply_data.get("msg_id") != pending_msg_id:
                        continue
                    reply_text = reply_data.get("text", "").strip()
                    if reply_text:
                        _save_user_msg(reply_text, pending_msg_id)
                        messages.append({"role": "user", "content": reply_text})
                    break

        # Max rounds reached -- force frame
        result, force_usage = await _force_frame(llm, messages)
        _framing_usage += TokenUsage(**force_usage)
        _save_framing_tokens()
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
        _save_framed(framed_req)
        await ws.send_json(
            {
                "type": "framed",
                "framed_requirement": framed_req,
                "request_id": request_id,
                "plan_id": plan_id,
                "token_usage": _framing_usage.to_dict(),
            }
        )
        await ws.close()

    except WebSocketDisconnect:
        logger.info("Framer WS disconnected (plan_id=%s)", plan_id)
    except Exception as exc:
        logger.exception("Framer WS error (plan_id=%s)", plan_id)
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
        settings.require_llm_credentials()
        llm = get_llm(settings)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc)},
        )

    async def _generate():
        from code_council.advisors import discover_advisor_skills, run_advisors
        from code_council.context import ProjectContext
        from code_council.framer import FramedRequirement
        from code_council.llm import TokenTracker
        from code_council.synthesizer import analyze_conflicts, synthesize_plan

        plan_id = req.plan_id
        change_description = req.change_description

        # Seed tracker with prior cumulative usage (e.g. framing tokens)
        if req.prior_token_usage:
            tracker = TokenTracker.from_dict(req.prior_token_usage)
        else:
            tracker = TokenTracker()

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

        # Helper: persist token usage to transcript
        def _save_token_usage():
            try:
                from code_council.transcript import update_token_usage

                update_token_usage(
                    plan_id=plan_id,
                    token_usage=tracker.to_dict(),
                    transcript_dir=settings.transcript_path,
                )
            except Exception as exc:
                logger.warning("Failed to save token usage to transcript: %s", exc)

        # Session started
        yield _sse_event("session", "started", {"plan_id": plan_id})

        # Discover advisor names for the frontend
        skills = discover_advisor_skills()
        advisor_names = [s.display_name for s in skills]
        yield _sse_event("advisors", "started", {"advisor_names": advisor_names})

        # Actually run them all in parallel via run_advisors
        t0 = time.monotonic()
        try:
            responses, params, timing, advisor_usage = await run_advisors(
                change_description=change_description,
                context=ctx,
                llm=llm,
                plan_id=plan_id,
                temperature_spread=settings.code_council_advisor_temperature_spread,
            )
            advisor_responses = responses
            tracker.record("advisors", advisor_usage)
        except Exception as exc:
            yield _sse_event("session", "error", {"message": f"Advisor error: {exc}"})
            return

        # Emit individual advisor completions
        for name, response in advisor_responses.items():
            yield _sse_event(
                "advisor",
                "completed",
                {
                    "name": name,
                    "response": response,
                },
            )

        advisor_duration = round(time.monotonic() - t0, 3)

        # Emit advisor stage token usage
        yield _sse_event(
            "token_usage",
            "update",
            {
                "stage": "advisors",
                "usage": tracker.stage_usage["advisors"].to_dict(),
                "total": tracker.total.to_dict(),
            },
        )
        _save_token_usage()

        # Analysis phase (Pass 1: conflict resolution)
        yield _sse_event("analysis", "started", {})

        try:
            conflict_analysis, analysis_usage = await analyze_conflicts(
                change_description=change_description,
                advisor_responses=advisor_responses,
                context=ctx,
                llm=llm,
            )
            tracker.record("analysis", analysis_usage)
        except Exception as exc:
            yield _sse_event("session", "error", {"message": f"Analysis error: {exc}"})
            return

        yield _sse_event("analysis", "completed", {})
        yield _sse_event(
            "token_usage",
            "update",
            {
                "stage": "analysis",
                "usage": tracker.stage_usage["analysis"].to_dict(),
                "total": tracker.total.to_dict(),
            },
        )
        _save_token_usage()

        # Synthesis phase (Pass 2: structured plan generation)
        yield _sse_event("synthesis", "started", {})

        try:
            plan, synth_usage = await synthesize_plan(
                change_description=change_description,
                advisor_responses=advisor_responses,
                context=ctx,
                plan_id=plan_id,
                llm=llm,
                conflict_analysis=conflict_analysis,
            )
            tracker.record("synthesis", synth_usage)
        except Exception as exc:
            yield _sse_event("session", "error", {"message": f"Synthesis error: {exc}"})
            return

        yield _sse_event(
            "synthesis",
            "completed",
            {
                "plan": plan.model_dump(),
            },
        )
        yield _sse_event(
            "token_usage",
            "update",
            {
                "stage": "synthesis",
                "usage": tracker.stage_usage["synthesis"].to_dict(),
                "total": tracker.total.to_dict(),
            },
        )
        _save_token_usage()

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
                token_usage=tracker.to_dict(),
                settings=settings,
            )
        except Exception as exc:
            logger.warning("Failed to save plan: %s", exc)

        total_duration = round(time.monotonic() - t0, 3)
        yield _sse_event(
            "session",
            "completed",
            {
                "plan_id": plan_id,
                "duration": total_duration,
                "advisor_duration": advisor_duration,
                "token_usage": tracker.to_dict(),
            },
        )

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
        append_framer_message,
        init_transcript,
        load_transcript,
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
            original_transcript.get("framed_question") if original_transcript else None
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
        settings.require_llm_credentials()
        llm = get_llm(settings)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc)},
        )

    async def _generate():
        from code_council.advisors import discover_advisor_skills, run_advisors
        from code_council.context import ProjectContext
        from code_council.llm import TokenTracker
        from code_council.synthesizer import analyze_conflicts, synthesize_plan

        plan_id = req.plan_id
        change_description = req.change_description

        # Seed tracker with prior cumulative usage
        if req.prior_token_usage:
            tracker = TokenTracker.from_dict(req.prior_token_usage)
        else:
            tracker = TokenTracker()

        if req.action == "approve":
            yield _sse_event("review", "approved", {"plan_id": plan_id})
            return

        if req.action == "reject":
            yield _sse_event("review", "rejected", {"plan_id": plan_id})
            return

        if req.action != "re-advise":
            yield _sse_event(
                "session",
                "error",
                {
                    "message": f"Unknown review action: {req.action}",
                },
            )
            return

        # -- Re-advise: re-run advisors with feedback -----------------------

        if not req.feedback.strip():
            yield _sse_event(
                "session",
                "error",
                {
                    "message": "Feedback is required for re-advise action.",
                },
            )
            return

        # Build project context
        if req.project_context:
            try:
                ctx = ProjectContext(**req.project_context)
            except Exception:
                ctx = ProjectContext(project_path="(none)")
        else:
            ctx = ProjectContext(project_path="(none)")

        # Helper: persist token usage to transcript
        def _save_token_usage():
            try:
                from code_council.transcript import update_token_usage

                update_token_usage(
                    plan_id=plan_id,
                    token_usage=tracker.to_dict(),
                    transcript_dir=settings.transcript_path,
                )
            except Exception as exc:
                logger.warning("Failed to save token usage to transcript: %s", exc)

        yield _sse_event(
            "review",
            "started",
            {
                "plan_id": plan_id,
                "action": "re-advise",
                "feedback": req.feedback,
            },
        )

        # Discover advisor names
        skills = discover_advisor_skills()
        advisor_names = [s.display_name for s in skills]
        yield _sse_event("advisors", "started", {"advisor_names": advisor_names})

        # Re-run advisors with negotiation feedback
        t0 = time.monotonic()
        try:
            responses, params, timing, advisor_usage = await run_advisors(
                change_description=change_description,
                context=ctx,
                llm=llm,
                plan_id=plan_id,
                temperature_spread=settings.code_council_advisor_temperature_spread,
                negotiation_feedback=req.feedback,
            )
            tracker.record("advisors", advisor_usage)
        except Exception as exc:
            yield _sse_event(
                "session",
                "error",
                {
                    "message": f"Advisor error: {exc}",
                },
            )
            return

        for name, response in responses.items():
            yield _sse_event(
                "advisor",
                "completed",
                {
                    "name": name,
                    "response": response,
                },
            )

        yield _sse_event(
            "token_usage",
            "update",
            {
                "stage": "advisors",
                "usage": tracker.stage_usage["advisors"].to_dict(),
                "total": tracker.total.to_dict(),
            },
        )
        _save_token_usage()

        # Analysis phase (Pass 1: conflict resolution)
        yield _sse_event("analysis", "started", {})

        try:
            conflict_analysis, analysis_usage = await analyze_conflicts(
                change_description=change_description,
                advisor_responses=responses,
                context=ctx,
                llm=llm,
            )
            tracker.record("analysis", analysis_usage)
        except Exception as exc:
            yield _sse_event(
                "session",
                "error",
                {
                    "message": f"Analysis error: {exc}",
                },
            )
            return

        yield _sse_event("analysis", "completed", {})
        yield _sse_event(
            "token_usage",
            "update",
            {
                "stage": "analysis",
                "usage": tracker.stage_usage["analysis"].to_dict(),
                "total": tracker.total.to_dict(),
            },
        )
        _save_token_usage()

        # Re-synthesize (Pass 2: structured plan generation)
        yield _sse_event("synthesis", "started", {})

        try:
            plan, synth_usage = await synthesize_plan(
                change_description=change_description,
                advisor_responses=responses,
                context=ctx,
                plan_id=plan_id,
                llm=llm,
                conflict_analysis=conflict_analysis,
            )
            tracker.record("synthesis", synth_usage)
        except Exception as exc:
            yield _sse_event(
                "session",
                "error",
                {
                    "message": f"Synthesis error: {exc}",
                },
            )
            return

        yield _sse_event(
            "synthesis",
            "completed",
            {
                "plan": plan.model_dump(),
            },
        )
        yield _sse_event(
            "token_usage",
            "update",
            {
                "stage": "synthesis",
                "usage": tracker.stage_usage["synthesis"].to_dict(),
                "total": tracker.total.to_dict(),
            },
        )
        _save_token_usage()

        # Save updated plan
        try:
            from code_council.framer import FramedRequirement
            from code_council.storage import save_plan

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
                token_usage=tracker.to_dict(),
                settings=settings,
            )
        except Exception as exc:
            logger.warning("Failed to save reviewed plan: %s", exc)

        total_duration = round(time.monotonic() - t0, 3)
        yield _sse_event(
            "session",
            "completed",
            {
                "plan_id": plan_id,
                "duration": total_duration,
                "token_usage": tracker.to_dict(),
            },
        )

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
# SSE: council feedback (all advisors review plan + decision gate)
# ---------------------------------------------------------------------------


@app.post("/council/feedback")
async def council_feedback(req: CouncilFeedbackRequest) -> StreamingResponse:
    """Each advisor reviews the synthesized plan, then Business+Architect
    decide which recommendations to accept, defer, or drop.

    SSE events:
        feedback/started       -- review phase begins
        feedback/advisor       -- one advisor's review completed
        feedback/deciding      -- decision gate phase begins
        feedback/decision      -- final decision with verdicts
        feedback/error         -- error during review
    """
    try:
        from code_council.config import get_settings
        from code_council.llm import get_llm

        settings = get_settings()
        settings.require_llm_credentials()
        llm = get_llm(settings)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc)},
        )

    async def _generate():
        from code_council.advisors import decide_changes, review_plan
        from code_council.llm import TokenTracker

        plan_id = req.plan_id
        plan_data = req.plan_data

        # Seed tracker with prior cumulative usage
        if req.prior_token_usage:
            tracker = TokenTracker.from_dict(req.prior_token_usage)
        else:
            tracker = TokenTracker()

        yield _sse_event("feedback", "started", {"plan_id": plan_id})

        # Phase 1: Each advisor reviews the plan in parallel
        try:
            advisor_reviews, timing, review_usage = await review_plan(
                plan_data=plan_data,
                llm=llm,
                plan_id=plan_id,
                temperature_spread=settings.code_council_advisor_temperature_spread,
            )
            tracker.record("review", review_usage)
        except Exception as exc:
            yield _sse_event(
                "feedback",
                "error",
                {
                    "message": f"Review error: {exc}",
                },
            )
            return

        # Emit each advisor's review
        for name, review in advisor_reviews.items():
            yield _sse_event(
                "feedback",
                "advisor",
                {
                    "name": name,
                    "review": review,
                },
            )

        yield _sse_event(
            "token_usage",
            "update",
            {
                "stage": "review",
                "usage": tracker.stage_usage["review"].to_dict(),
                "total": tracker.total.to_dict(),
            },
        )

        # Phase 2: Business + Architect decision gate
        yield _sse_event("feedback", "deciding", {})

        try:
            decision, gate_usage = await decide_changes(
                plan_data=plan_data,
                advisor_reviews=advisor_reviews,
                llm=llm,
            )
            tracker.record("decision_gate", gate_usage)
        except Exception as exc:
            yield _sse_event(
                "feedback",
                "error",
                {
                    "message": f"Decision error: {exc}",
                },
            )
            return

        yield _sse_event(
            "feedback",
            "decision",
            {
                "decision": decision,
                "advisor_reviews": advisor_reviews,
                "token_usage": tracker.to_dict(),
            },
        )

        # Persist council review results to the plan file
        try:
            from code_council.storage import save_council_review

            save_council_review(
                plan_id=plan_id,
                advisor_reviews=advisor_reviews,
                decision=decision,
                settings=settings,
            )
        except Exception as exc:
            logger.warning("Failed to save council review: %s", exc)

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
# SSE: apply council feedback (re-synthesize with accepted changes)
# ---------------------------------------------------------------------------


@app.post("/council/feedback/apply")
async def apply_council_feedback(req: CouncilApplyRequest) -> StreamingResponse:
    """Re-run advisors with accepted council changes as feedback, then
    re-synthesize.  The resulting plan is saved with status
    ``council_reviewed``.

    SSE events follow the same pattern as ``/council/stream``:
        session/started, advisors/started, advisor/completed,
        synthesis/started, synthesis/completed, session/completed
    """
    try:
        from code_council.config import get_settings
        from code_council.llm import get_llm

        settings = get_settings()
        settings.require_llm_credentials()
        llm = get_llm(settings)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc)},
        )

    async def _generate():
        from code_council.advisors import discover_advisor_skills, run_advisors
        from code_council.context import ProjectContext
        from code_council.framer import FramedRequirement
        from code_council.llm import TokenTracker
        from code_council.synthesizer import analyze_conflicts, synthesize_plan
        from code_council.utils import generate_plan_id

        # Generate a NEW plan_id for the council-revised plan so it gets
        # its own file on disk.  The original plan_id becomes base_plan_id,
        # creating a linked chain for version comparison.
        original_plan_id = req.plan_id
        plan_id = generate_plan_id(req.change_description)
        base_plan_id = req.base_plan_id or original_plan_id
        change_description = req.change_description

        # Seed tracker with prior cumulative usage (framing + council + feedback)
        if req.prior_token_usage:
            tracker = TokenTracker.from_dict(req.prior_token_usage)
        else:
            tracker = TokenTracker()

        # Parse framed requirement
        try:
            framed = FramedRequirement(**req.framed_requirement)
        except Exception as exc:
            yield _sse_event(
                "session",
                "error",
                {
                    "message": f"Invalid framed requirement: {exc}",
                },
            )
            return

        # Build project context
        if req.project_context:
            try:
                ctx = ProjectContext(**req.project_context)
            except Exception:
                ctx = ProjectContext(project_path="(none)")
        else:
            ctx = ProjectContext(project_path="(none)")

        # Build negotiation feedback from the accepted changes
        feedback_lines = [
            "The following changes were accepted during council review. "
            "Incorporate them into the revised plan.\n\n"
            "IMPORTANT: Acceptance criteria must be human-readable "
            "behaviour descriptions (Given/When/Then or plain English). "
            "Do NOT write test file paths, test function names, or "
            "code-level assertions as acceptance criteria.\n"
        ]
        for i, change in enumerate(req.accepted_changes, 1):
            feedback_lines.append(f"{i}. {change}")
        negotiation_feedback = "\n".join(feedback_lines)

        # Helper: persist token usage to transcript (uses original plan_id
        # since the transcript was created under that ID)
        def _save_token_usage():
            try:
                from code_council.transcript import update_token_usage

                update_token_usage(
                    plan_id=original_plan_id,
                    token_usage=tracker.to_dict(),
                    transcript_dir=settings.transcript_path,
                )
            except Exception as exc:
                logger.warning("Failed to save token usage to transcript: %s", exc)

        yield _sse_event(
            "session",
            "started",
            {"plan_id": plan_id, "base_plan_id": base_plan_id},
        )

        # Discover advisor names
        skills = discover_advisor_skills()
        advisor_names = [s.display_name for s in skills]
        yield _sse_event("advisors", "started", {"advisor_names": advisor_names})

        # Re-run advisors with council feedback
        t0 = time.monotonic()
        try:
            responses, params, timing, advisor_usage = await run_advisors(
                change_description=change_description,
                context=ctx,
                llm=llm,
                plan_id=plan_id,
                temperature_spread=settings.code_council_advisor_temperature_spread,
                negotiation_feedback=negotiation_feedback,
            )
            tracker.record("advisors", advisor_usage)
        except Exception as exc:
            yield _sse_event(
                "session",
                "error",
                {
                    "message": f"Advisor error: {exc}",
                },
            )
            return

        for name, response in responses.items():
            yield _sse_event(
                "advisor",
                "completed",
                {
                    "name": name,
                    "response": response,
                },
            )

        yield _sse_event(
            "token_usage",
            "update",
            {
                "stage": "advisors",
                "usage": tracker.stage_usage["advisors"].to_dict(),
                "total": tracker.total.to_dict(),
            },
        )
        _save_token_usage()

        # Analysis phase (Pass 1: conflict resolution)
        yield _sse_event("analysis", "started", {})

        try:
            conflict_analysis, analysis_usage = await analyze_conflicts(
                change_description=change_description,
                advisor_responses=responses,
                context=ctx,
                llm=llm,
            )
            tracker.record("analysis", analysis_usage)
        except Exception as exc:
            yield _sse_event(
                "session",
                "error",
                {
                    "message": f"Analysis error: {exc}",
                },
            )
            return

        yield _sse_event("analysis", "completed", {})
        yield _sse_event(
            "token_usage",
            "update",
            {
                "stage": "analysis",
                "usage": tracker.stage_usage["analysis"].to_dict(),
                "total": tracker.total.to_dict(),
            },
        )
        _save_token_usage()

        # Re-synthesize (Pass 2: structured plan generation)
        yield _sse_event("synthesis", "started", {})

        try:
            plan, synth_usage = await synthesize_plan(
                change_description=change_description,
                advisor_responses=responses,
                context=ctx,
                plan_id=plan_id,
                llm=llm,
                conflict_analysis=conflict_analysis,
            )
            tracker.record("synthesis", synth_usage)
        except Exception as exc:
            yield _sse_event(
                "session",
                "error",
                {
                    "message": f"Synthesis error: {exc}",
                },
            )
            return

        yield _sse_event(
            "synthesis",
            "completed",
            {
                "plan": plan.model_dump(),
            },
        )
        yield _sse_event(
            "token_usage",
            "update",
            {
                "stage": "synthesis",
                "usage": tracker.stage_usage["synthesis"].to_dict(),
                "total": tracker.total.to_dict(),
            },
        )
        _save_token_usage()

        # Save with council_reviewed status under the NEW plan_id
        try:
            from code_council.storage import save_plan

            save_plan(
                plan_id=plan_id,
                change_description=change_description,
                plan_data=plan.model_dump(),
                state_data={"status": "council_reviewed"},
                advisor_responses=responses,
                context_summary=ctx.summary or "",
                framed_requirement=framed.model_dump(),
                base_plan_id=base_plan_id,
                token_usage=tracker.to_dict(),
                settings=settings,
            )
        except Exception as exc:
            logger.warning("Failed to save council-reviewed plan: %s", exc)

        total_duration = round(time.monotonic() - t0, 3)
        yield _sse_event(
            "session",
            "completed",
            {
                "plan_id": plan_id,
                "base_plan_id": base_plan_id,
                "duration": total_duration,
                "token_usage": tracker.to_dict(),
            },
        )

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
        build_directory_tree,
        detect_tech_stack,
        detect_test_patterns,
        find_config_files,
    )

    root = Path(req.project_path).resolve()
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
        "discovered_files": [{"path": p, "score": s, "is_sensitive": sens} for p, s, sens in paths],
    }


@app.post("/scan/approve")
async def scan_approve(req: ScanApproveRequest) -> dict:
    """Read approved files and return their contents + full context."""
    from code_council.context import (
        ProjectContext,
        build_directory_tree,
        detect_tech_stack,
        detect_test_patterns,
        find_config_files,
        read_approved_files,
    )

    root = Path(req.project_path).resolve()
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    # Read approved source files
    relevant_files = read_approved_files(root, req.approved_paths)

    # Read config files if specified
    all_configs = find_config_files(root)
    if req.config_files:
        config_contents = {k: v for k, v in all_configs.items() if k in req.config_files}
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


@app.post("/scan/prompt")
async def scan_prompt(req: ScanPromptRequest) -> dict:
    """Generate an AI prompt for producing project context externally.

    Instead of scanning a local filesystem, the user copies this prompt
    into their AI coding tool, which reads the repo and returns JSON
    matching the ProjectContext schema.
    """
    from code_council.context import generate_context_prompt

    prompt = generate_context_prompt(
        change_description=req.change_description,
        framed_requirement=req.framed_requirement,
    )
    return {"prompt": prompt}


@app.post("/scan/upload")
async def scan_upload(req: ScanUploadRequest) -> dict:
    """Accept a raw ProjectContext JSON produced by an external AI tool.

    Validates the JSON against the ProjectContext schema and returns
    the normalised context ready for the advisor pipeline.
    """
    from code_council.context import ProjectContext

    try:
        ctx = ProjectContext(**req.project_context)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid ProjectContext JSON: {exc}",
        ) from exc

    return {
        "project_context": ctx.model_dump(),
        "valid": True,
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
