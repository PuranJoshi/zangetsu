"""CLI entry-point for code-council.

Installed as `bankai` command via pyproject.toml.

Usage:
    bankai "Want to build a cash deposit feature"
    bankai -p ./my-app "Add JWT auth to the API"

The pipeline:
    1. Frame requirements (brainstorm the idea -- no project needed)
    2. Ask if there's an existing project to build into
    3. If yes: scan the project for context
    4. Run technical advisors in parallel
    5. Synthesize implementation plan
    6. Output (you copy it to your AI coding agent)

Python lesson: typer.prompt and typer.confirm
    typer.prompt("Question") -- asks the user for text input, returns it
    typer.confirm("Yes/no?") -- asks yes/no, returns True/False
    These block the CLI and wait for input. They're the simplest way
    to make a CLI interactive without building a full TUI.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from code_council.utils import generate_plan_id as _generate_plan_id

app = typer.Typer(
    name="bankai",
    help="Plan code changes through multi-advisor deliberation.",
    add_completion=False,
    no_args_is_help=True,
)


# _STOP_WORDS and _generate_plan_id are imported from code_council.utils
# (kept as private aliases so the rest of cli.py is unchanged).


# ---------------------------------------------------------------------------
# bankai -- the main command
# ---------------------------------------------------------------------------


@app.callback(invoke_without_command=True)
def bankai(
    description: str = typer.Argument(
        None,
        help="Feature request to plan (e.g., 'Add user authentication')",
    ),
    project: str = typer.Option(
        None,
        "--project",
        "-p",
        help="Path to the project to build into. If omitted, asked after framing.",
    ),
    output_json: bool = typer.Option(
        False,
        "--json",
        help="Output raw JSON instead of formatted text.",
    ),
    load: str = typer.Option(
        None,
        "--load",
        help="Resume from a previous plan or transcript by ID.",
    ),
    export_id: str = typer.Option(
        None,
        "--export",
        help="Export a plan as a humanised Markdown document by ID.",
    ),
    context_file: str = typer.Option(
        None,
        "--context",
        help="Path to a JSON file containing ProjectContext (from AI-generated scan).",
    ),
) -> None:
    """Plan code changes through multi-advisor deliberation.

    Describe the feature or idea you want to build. Code Council will
    brainstorm and frame requirements first, then optionally scan an
    existing project before producing a structured implementation plan.

    Copy the output into your AI coding agent.

    Flags for working with existing plans:

        bankai --load <plan_id>           Resume from a plan or transcript.

        bankai --export <plan_id>         Export a plan as Markdown.
    """
    # -- Flag: --export <plan_id> -------------------------------------------
    if export_id is not None:
        asyncio.run(_export_plan_as_markdown(export_id))
        return

    # -- Flag: --load <plan_id> ---------------------------------------------
    if load is not None:
        # description is populated from the loaded plan/transcript inside
        # _run_pipeline; pass a placeholder here.
        asyncio.run(
            _run_pipeline(
                description=description or "",
                project_path=project,
                output_json=output_json,
                load_id=load,
                context_file=context_file,
            )
        )
        return

    if description is None:
        return

    asyncio.run(_run_pipeline(description, project, output_json, context_file=context_file))


# ---------------------------------------------------------------------------
# Load-context: resume-point detection
# ---------------------------------------------------------------------------

# Resume points -- which pipeline stage to jump to.
_RESUME_CONFIRMATION = "confirmation"  # skip framing, jump to confirmation gate
_RESUME_ADVISORS = "advisors"  # skip framing, jump to advisor phase
_RESUME_SYNTHESIS = "synthesis"  # skip framing + advisors, jump to synthesis


def _resolve_load_context(
    context_id: str,
    settings,
) -> dict | None:
    """Resolve a ``load context: <id>`` to a resume descriptor.

    Checks for a saved **plan** first, then a **transcript**. Returns a
    dict describing what was found and where to resume, or None if
    neither exists.

    Returned dict keys:

    - ``source``: ``"plan"`` or ``"transcript"``
    - ``resume_point``: one of ``_RESUME_*`` constants
    - ``framed_data``: FramedRequirement dict (if available)
    - ``description``: original change description
    - ``advisor_responses``: advisor dict (only for synthesis resume)
    - ``context_summary``: project context summary (only for synthesis resume)
    - ``plan_data``: full plan JSON dict (only from plan source)
    - ``transcript_data``: full transcript dict (only from transcript source)
    - ``all_answers``: list of "Q: ... / A: ..." strings from transcript Q&A
    """
    from code_council.storage import load_plan
    from code_council.transcript import load_transcript

    # -- 1. Try plan first ---------------------------------------------------
    plan_data = load_plan(context_id, settings=settings)
    if plan_data is not None:
        framed_data = plan_data.get("framed_requirement")
        advisor_responses = plan_data.get("advisor_responses")
        description = plan_data.get("change_description", "")

        # Plan exists and has advisor responses -> can re-synthesize
        if framed_data and advisor_responses:
            return {
                "source": "plan",
                "resume_point": _RESUME_SYNTHESIS,
                "framed_data": framed_data,
                "description": description,
                "advisor_responses": advisor_responses,
                "context_summary": plan_data.get("context_summary", ""),
                "plan_data": plan_data,
                "all_answers": [],
            }

        # Plan exists with framed requirement but no advisors
        if framed_data:
            return {
                "source": "plan",
                "resume_point": _RESUME_CONFIRMATION,
                "framed_data": framed_data,
                "description": description,
                "plan_data": plan_data,
                "all_answers": [],
            }

        # Plan exists but no framed_requirement -- fall through to transcript

    # -- 2. Try transcript ---------------------------------------------------
    transcript_data = load_transcript(
        context_id,
        transcript_dir=settings.transcript_path,
    )
    if transcript_data is not None:
        description = transcript_data.get("question", "")
        messages = transcript_data.get("framer_messages", [])

        # Reconstruct the Q&A pairs from the transcript messages.
        # Messages alternate: user, framer-question, user-answer, ...
        # We look for paired framer-question + user-answer with matching msg_id.
        all_answers = _extract_qa_pairs(messages)

        return {
            "source": "transcript",
            "resume_point": _RESUME_CONFIRMATION if all_answers else _RESUME_ADVISORS,
            "framed_data": None,
            "description": description,
            "transcript_data": transcript_data,
            "all_answers": all_answers,
        }

    return None


def _extract_qa_pairs(messages: list[dict]) -> list[str]:
    """Extract ``Q: .../A: ...`` pairs from transcript framer_messages.

    Pairs framer questions with user answers by matching ``msg_id``.
    Unpaired messages are skipped.
    """
    # Index framer questions by msg_id
    framer_questions: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") == "framer" and "msg_id" in msg:
            framer_questions[msg["msg_id"]] = msg["text"]

    # Match user answers to framer questions
    pairs: list[str] = []
    for msg in messages:
        if msg.get("role") == "user" and "msg_id" in msg:
            mid = msg["msg_id"]
            question_text = framer_questions.get(mid, "(unknown question)")
            pairs.append(f"Q: {question_text}\nA: {msg['text']}")

    # Also include [CORRECTION] messages (no msg_id pairing needed)
    for msg in messages:
        if msg.get("role") == "user" and "msg_id" in msg and msg["text"].startswith("[CORRECTION]"):
            correction = msg["text"].removeprefix("[CORRECTION]").strip()
            pairs.append(
                f"Q: (User correction after reviewing framed requirement)\nA: {correction}"
            )

    return pairs


async def _run_pipeline(
    description: str,
    project_path: str | None,
    output_json: bool,
    load_id: str | None = None,
    context_file: str | None = None,
) -> None:
    """Run the full bankai pipeline.

    The key insight: framing happens BEFORE project scanning. The Framer
    brainstorms on the idea itself -- it doesn't need to know what
    codebase you're working in. Project context only matters when the
    technical advisors need to give file-level recommendations.

    Args:
        load_id: If provided, resume from a previous plan or transcript
            with this ID instead of running the full pipeline.
        context_file: If provided, path to a JSON file containing
            pre-built ProjectContext (from AI-generated scan).
    """
    from code_council.advisors import run_advisors
    from code_council.config import get_settings
    from code_council.context import (
        ProjectContext,
        build_directory_tree,
        detect_tech_stack,
        detect_test_patterns,
        discover_relevant_paths,
        find_config_files,
        generate_context_prompt,
        read_approved_files,
    )
    from code_council.framer import FramedRequirement, frame_request
    from code_council.llm import get_llm
    from code_council.state import PlanState, PlanStatus
    from code_council.storage import save_plan
    from code_council.synthesizer import analyze_conflicts, synthesize_plan
    from code_council.transcript import (
        append_framer_message,
        init_transcript,
        set_framed_question,
    )

    settings = get_settings()

    # -- Check for load context (via --load flag) ----------------------------
    loaded_context_id = load_id

    # Tracks whether we should skip straight to synthesis (advisor responses
    # already available from a previous plan).
    _skip_to_synthesis = False
    _loaded_advisor_responses: dict[str, str] | None = None
    _loaded_context_summary: str | None = None

    if loaded_context_id is not None:
        resolved = _resolve_load_context(loaded_context_id, settings)
        if resolved is None:
            typer.echo(
                f"Error: No plan or transcript found for '{loaded_context_id}'.",
                err=True,
            )
            raise typer.Exit(code=1)

        source = resolved["source"]
        resume_point = resolved["resume_point"]
        description = resolved["description"] or description

        settings.require_llm_credentials()
        llm = get_llm(settings)
        # Reuse the original transcript/plan ID so corrections and
        # subsequent messages are appended to the *same* transcript file
        # instead of creating a new orphaned one.
        plan_id = loaded_context_id
        transcript_dir = settings.transcript_path
        all_answers: list[str] = list(resolved.get("all_answers", []))
        _question_counter = len(all_answers)

        # The transcript file already exists on disk -- no init_transcript
        # needed.  Just append a resume marker.
        append_framer_message(
            plan_id=plan_id,
            role="user",
            text=f"Resumed session from {source} {loaded_context_id}",
            transcript_dir=transcript_dir,
        )

        state = PlanState(
            plan_id=plan_id,
            max_rounds=settings.code_council_max_negotiation_rounds,
        )

        if resume_point == _RESUME_SYNTHESIS:
            # Plan has advisor responses -- ask user whether to re-synthesize
            # or re-run the full pipeline from framing.
            typer.echo(
                f"\nLoaded plan {loaded_context_id} (source: {source}, has advisor responses)"
            )
            resynthesize = typer.confirm(
                "  Re-synthesize from existing advisor responses?",
                default=True,
            )

            framed_data = resolved["framed_data"]
            framed = FramedRequirement(**framed_data)

            if resynthesize:
                _skip_to_synthesis = True
                _loaded_advisor_responses = resolved["advisor_responses"]
                _loaded_context_summary = resolved.get("context_summary", "")
                # Jump past framing, confirmation, project scan, and advisors
            else:
                typer.echo("  Re-running from framing confirmation.")
                # Fall through to the confirmation gate

        elif resume_point == _RESUME_CONFIRMATION and resolved.get("framed_data"):
            # Plan or transcript with framed requirement
            framed_data = resolved["framed_data"]
            framed = FramedRequirement(**framed_data)
            typer.echo(f"\nLoaded context from {source} {loaded_context_id}")
            # Fall through to the confirmation gate

        else:
            # Transcript only -- reconstruct framing from Q&A
            typer.echo(f"\nLoaded transcript {loaded_context_id} (no saved plan found)")
            if all_answers:
                typer.echo(f"  Reconstructing framing from {len(all_answers)} Q&A pair(s)...")
                clarification_text = "\n\n".join(all_answers)
                framed = await frame_request(
                    change_description=description,
                    context_summary="",
                    llm=llm,
                    clarification_answers=clarification_text,
                )
            else:
                typer.echo("  No Q&A found -- re-framing from scratch...")
                framed = await frame_request(
                    change_description=description,
                    context_summary="",
                    llm=llm,
                )
            # Fall through to the confirmation gate (or clarification loop
            # if the re-framed result still needs clarification)

    else:
        # -- Normal flow: frame from scratch --------------------------------
        settings.require_llm_credentials()
        llm = get_llm(settings)
        plan_id = _generate_plan_id(description)
        transcript_dir = settings.transcript_path

        # -- Transcript: record the original question -------------------------
        init_transcript(
            plan_id=plan_id,
            question=description,
            transcript_dir=transcript_dir,
        )
        append_framer_message(
            plan_id=plan_id,
            role="user",
            text=description,
            transcript_dir=transcript_dir,
        )

        # -- Phase 1: Frame requirements (no project needed) -------------------

        state = PlanState(
            plan_id=plan_id,
            max_rounds=settings.code_council_max_negotiation_rounds,
        )

        typer.echo("\nFraming requirements...")
        framed = await frame_request(
            change_description=description,
            context_summary="",  # no project context yet
            llm=llm,
        )

        # -- Interactive clarification loop ------------------------------------
        # The framer produces a BATCH of questions (typically 3-5). We ask
        # the user all of them locally -- no LLM call between questions.
        # After the whole batch is answered, we make ONE LLM call with all
        # answers so far, which may produce another batch. This eliminates
        # the latency of an LLM round-trip between every single question.
        #
        # After CLARIFICATION_BATCH_SIZE batches, we pause and ask the user
        # if they want to continue or proceed with assumptions. This is NOT
        # a hard stop -- the user always decides.
        CLARIFICATION_BATCH_SIZE = 3
        all_answers = []
        _batch_counter = 0
        _question_counter = 0

        while framed.needs_clarification():
            # After every CLARIFICATION_BATCH_SIZE batches, check in with
            # the user instead of silently continuing or silently stopping.
            if _batch_counter >= CLARIFICATION_BATCH_SIZE:
                typer.echo(f"\n--- {_batch_counter} clarification rounds completed ---")

                # Show the assumptions the framer would proceed with
                if framed.assumptions:
                    typer.echo("\nThe framer would proceed with these assumptions:")
                    for a in framed.assumptions:
                        typer.echo(f"  - {a}")

                # Show the remaining unanswered questions
                typer.echo(
                    f"\nThere are still {len(framed.clarifications_needed)} unanswered question(s):"
                )
                for q in framed.clarifications_needed:
                    typer.echo(f"  ? {q}")

                keep_going = typer.confirm(
                    "\nContinue with more clarifying questions?",
                    default=True,
                )
                if not keep_going:
                    typer.echo("  Proceeding with assumptions.")
                    break

                # Reset the counter so the user gets another
                # CLARIFICATION_BATCH_SIZE batches before the next check-in
                _batch_counter = 0

            questions = framed.clarifications_needed
            _batch_counter += 1
            typer.echo(f"\n--- Clarification Needed ({len(questions)} question(s)) ---")

            # Ask ALL questions in this batch locally -- no LLM call between them
            batch_answers: list[str] = []
            for question in questions:
                _question_counter += 1
                msg_id = str(_question_counter)
                typer.echo(f"\n  Q{_question_counter}: {question}")

                # Record the framer's question in the transcript
                append_framer_message(
                    plan_id=plan_id,
                    role="framer",
                    text=question,
                    msg_id=msg_id,
                    transcript_dir=transcript_dir,
                )

                answer = typer.prompt("\n  Your answer")

                if not answer.strip():
                    typer.echo("  Skipped.")
                    continue

                # Record the user's answer in the transcript
                append_framer_message(
                    plan_id=plan_id,
                    role="user",
                    text=answer,
                    msg_id=msg_id,
                    transcript_dir=transcript_dir,
                )

                batch_answers.append(f"Q: {question}\nA: {answer}")

            # Accumulate all answers across batches
            all_answers.extend(batch_answers)

            # ONE LLM call with all answers so far to re-evaluate
            clarification_text = "\n\n".join(all_answers)
            typer.echo("\nRe-evaluating requirements with your answers...")
            framed = await frame_request(
                change_description=description,
                context_summary="",
                llm=llm,
                clarification_answers=clarification_text,
            )

    if _skip_to_synthesis:
        # ---------------------------------------------------------------
        # Fast path: re-synthesize from saved advisor responses.
        # Skip confirmation, project scan, and advisor phases entirely.
        # ---------------------------------------------------------------
        assert _loaded_advisor_responses is not None

        advisor_responses = _loaded_advisor_responses
        context_summary = _loaded_context_summary or ""

        # Build a minimal ProjectContext from the saved context summary
        # so the synthesizer has something to work with.
        context = ProjectContext(
            project_path="(loaded from previous plan)",
            summary=context_summary,
        )

        state.transition(PlanStatus.DRAFTING)

        typer.echo(f"\nRe-synthesizing from {len(advisor_responses)} saved advisor response(s)...")
        typer.echo("  Analyzing advisor outputs...")
        conflict_analysis = await analyze_conflicts(
            change_description=description,
            advisor_responses=advisor_responses,
            context=context,
            llm=llm,
        )
        typer.echo("  Generating plan...")
        plan = await synthesize_plan(
            change_description=description,
            advisor_responses=advisor_responses,
            context=context,
            plan_id=plan_id,
            llm=llm,
            conflict_analysis=conflict_analysis,
        )

        state.transition(PlanStatus.PROPOSED)

        # -- Review gate (fast path) ------------------------------------
        # Show the plan and let the user approve or reject.
        # Re-advise / re-frame are not available on the fast path since
        # we don't have the full project context.
        typer.echo(_format_plan(plan))
        typer.echo(
            f"\n{'=' * 60}\n"
            f" REVIEW (re-synthesized from saved responses)\n"
            f"{'=' * 60}\n"
            f"  [a] Approve  -- accept this plan\n"
            f"  [r] Re-synthesize -- try synthesis again\n"
            f"  [x] Reject   -- discard this plan\n"
        )

        while True:
            choice = (
                typer.prompt(
                    "Your choice",
                    default="a",
                )
                .strip()
                .lower()
            )

            if choice in ("a", "approve"):
                state.transition(PlanStatus.REVIEWING)
                state.transition(PlanStatus.AGREED)
                typer.echo("\nPlan approved.")
                break

            if choice in ("x", "reject"):
                state.transition(PlanStatus.REVIEWING)
                state.transition(PlanStatus.REJECTED)
                typer.echo("\nPlan rejected.")
                break

            if choice in ("r", "re-synthesize"):
                typer.echo("\nRe-synthesizing...")
                typer.echo("  Analyzing advisor outputs...")
                conflict_analysis = await analyze_conflicts(
                    change_description=description,
                    advisor_responses=advisor_responses,
                    context=context,
                    llm=llm,
                )
                typer.echo("  Generating plan...")
                plan = await synthesize_plan(
                    change_description=description,
                    advisor_responses=advisor_responses,
                    context=context,
                    plan_id=plan_id,
                    llm=llm,
                    conflict_analysis=conflict_analysis,
                )
                typer.echo(_format_plan(plan))
                continue

            typer.echo(f"  Unknown choice '{choice}' -- try again.")
            continue

    else:
        # ---------------------------------------------------------------
        # Normal path: confirmation -> project scan -> advisors -> synth
        # ---------------------------------------------------------------

        # -- Confirmation gate -------------------------------------------
        # Show the full framed requirement and let the user approve or
        # correct it before moving to advisors.  If the user provides
        # corrections, we re-run framing with their feedback.
        while True:
            typer.echo(_format_framed_requirement(framed))

            confirmation = (
                typer.prompt(
                    "Proceed to advisors? [y]es / [n]o, let me correct",
                    default="y",
                )
                .strip()
                .lower()
            )

            if confirmation in ("y", "yes"):
                break

            correction = typer.prompt("\n  What needs to change?")
            if not correction.strip():
                continue

            # Record the correction in the transcript
            _question_counter += 1
            append_framer_message(
                plan_id=plan_id,
                role="user",
                text=f"[CORRECTION] {correction}",
                msg_id=str(_question_counter),
                transcript_dir=transcript_dir,
            )

            # Add the correction as a clarification answer and re-frame
            all_answers.append(
                f"Q: (User correction after reviewing framed requirement)\nA: {correction}"
            )
            clarification_text = "\n\n".join(all_answers)
            typer.echo("\nRe-framing with your corrections...")
            framed = await frame_request(
                change_description=description,
                context_summary="",
                llm=llm,
                clarification_answers=clarification_text,
            )

        # Record the final framed requirement in the transcript
        framed_text = (
            f"[FRAMED] {framed.title}\n\nType: {framed.type}\nDescription: {framed.description}"
        )
        append_framer_message(
            plan_id=plan_id,
            role="framer",
            text=framed_text,
            transcript_dir=transcript_dir,
        )
        set_framed_question(
            plan_id=plan_id,
            framed_question=framed.description,
            transcript_dir=transcript_dir,
        )

        # -- Phase 2: Project context (optional, with file approval) -----

        context: ProjectContext
        resolved_project: str | None = None

        # Option A: --context flag provides a pre-built JSON file
        if context_file is not None:
            context_path = Path(context_file)
            if not context_path.is_file():
                typer.echo(f"Error: {context_file} is not a file.", err=True)
                raise typer.Exit(code=1)
            try:
                raw = json.loads(context_path.read_text(encoding="utf-8"))
                context = ProjectContext(**raw)
                typer.echo(f"\nLoaded project context from {context_file}")
                if context.tech_stack.languages:
                    tech = ", ".join(context.tech_stack.languages + context.tech_stack.frameworks)
                    typer.echo(f"  Stack: {tech}")
                typer.echo(
                    f"  Files: {len(context.relevant_files)} relevant, "
                    f"{len(context.config_files)} config"
                )
            except Exception as exc:
                typer.echo(f"Error parsing context JSON: {exc}", err=True)
                raise typer.Exit(code=1) from exc

        # Option B: --project flag provides a local path to scan
        elif project_path is not None:
            resolved_project = str(Path(project_path).resolve())

        # Option C: Interactive -- ask the user
        else:
            typer.echo("\nHow would you like to provide project context?\n")
            typer.echo("  [s] Scan a local project directory")
            typer.echo("  [u] Upload context JSON (generated by an AI tool)")
            typer.echo("  [g] Skip (greenfield / no project)\n")
            choice = (
                typer.prompt(
                    "Choice",
                    default="s",
                )
                .strip()
                .lower()
            )

            if choice == "s":
                project_path = typer.prompt("Project path")
                resolved_project = str(Path(project_path).resolve())
            elif choice == "u":
                # Generate and display the tailored AI prompt
                framed_dict = framed.model_dump() if framed else None
                ai_prompt = generate_context_prompt(
                    change_description=description,
                    framed_requirement=framed_dict,
                )
                typer.echo("\n--- Copy the prompt below into your AI coding tool ---\n")
                typer.echo(ai_prompt)
                typer.echo("\n--- End of prompt ---\n")
                typer.echo(
                    "Run the prompt in your AI tool, then save the JSON output "
                    "to a file and provide the path below."
                )
                json_path_str = typer.prompt("Path to the JSON file")
                json_path = Path(json_path_str.strip())
                if not json_path.is_file():
                    typer.echo(f"Error: {json_path} is not a file.", err=True)
                    raise typer.Exit(code=1)
                try:
                    raw = json.loads(json_path.read_text(encoding="utf-8"))
                    context = ProjectContext(**raw)
                    typer.echo(f"\nLoaded project context from {json_path}")
                    if context.tech_stack.languages:
                        tech = ", ".join(
                            context.tech_stack.languages + context.tech_stack.frameworks
                        )
                        typer.echo(f"  Stack: {tech}")
                    typer.echo(
                        f"  Files: {len(context.relevant_files)} relevant, "
                        f"{len(context.config_files)} config"
                    )
                except Exception as exc:
                    typer.echo(f"Error parsing context JSON: {exc}", err=True)
                    raise typer.Exit(code=1) from exc
            else:
                typer.echo("\nNo project -- planning for greenfield build.")
                context = ProjectContext(
                    project_path="(greenfield)",
                    summary="Greenfield project -- no existing codebase.",
                )

        if resolved_project is not None:
            root = Path(resolved_project)
            if not root.is_dir():
                typer.echo(f"Error: {resolved_project} is not a directory.", err=True)
                raise typer.Exit(code=1)

            typer.echo(f"\nScanning project: {resolved_project}")

            # Step 1: Directory tree and tech detection (no file content read)
            directory_tree = build_directory_tree(root)
            config_files = find_config_files(root)
            tech_stack = detect_tech_stack(root, config_files)
            test_patterns = detect_test_patterns(root, tech_stack)

            if tech_stack.languages:
                tech = ", ".join(tech_stack.languages + tech_stack.frameworks)
                typer.echo(f"  Stack: {tech}")

            # Step 2: Discover relevant files (paths only, NO content read yet)
            discovered = discover_relevant_paths(root, description)

            # Separate safe files from sensitive (potential credential) files
            safe_files = [(p, s) for p, s, sensitive in discovered if not sensitive]
            sensitive_files = [(p, s) for p, s, sensitive in discovered if sensitive]

            # Step 3: Ask for approval -- safe files first
            approved_paths: list[str] = []
            if safe_files:
                typer.echo(f"\n  Found {len(safe_files)} relevant files:")
                for i, (rel_path, score) in enumerate(safe_files, 1):
                    typer.echo(f"    {i}. {rel_path}")

                include_files = typer.confirm(
                    "\n  Include these files for advisor context?",
                    default=True,
                )
                if include_files:
                    approved_paths = [p for p, _ in safe_files]
                    typer.echo(f"  Approved {len(approved_paths)} files.")
                else:
                    typer.echo("  No files included -- advisors will work from structure only.")

            # Step 3b: Sensitive files need individual confirmation
            if sensitive_files:
                typer.echo(f"\n  Found {len(sensitive_files)} files that may contain credentials:")
                for rel_path, _ in sensitive_files:
                    typer.echo(f"    ! {rel_path}")
                    include_it = typer.confirm(
                        f"    Include {rel_path}? (may contain secrets)",
                        default=False,
                    )
                    if include_it:
                        approved_paths.append(rel_path)

            if not safe_files and not sensitive_files:
                typer.echo("  No relevant files found for this description.")

            # Step 4: Read ONLY approved files
            relevant_files = read_approved_files(root, approved_paths) if approved_paths else {}

            # Step 5: Config files -- ask separately since they may contain secrets
            approved_configs: dict[str, str] = {}
            if config_files:
                config_names = list(config_files.keys())
                typer.echo(f"\n  Config files found: {', '.join(config_names)}")
                include_configs = typer.confirm(
                    "  Include config files for advisor context?",
                    default=True,
                )
                if include_configs:
                    approved_configs = config_files
                else:
                    typer.echo("  Config files excluded.")

            context = ProjectContext(
                project_path=resolved_project,
                directory_tree=directory_tree,
                tech_stack=tech_stack,
                config_files=approved_configs,
                relevant_files=relevant_files,
                test_patterns=test_patterns,
                summary="",
            )

        # -- Phase 3 & 4: Advisors + Synthesis (with review loop) ------------
        #
        # After synthesis, the user can review the plan and choose to:
        #   [a] Approve  -- accept and save
        #   [r] Re-advise -- re-run advisors with feedback, then re-synthesize
        #   [f] Re-frame -- go back to framing with corrections
        #   [x] Reject   -- discard the plan
        #
        # The loop runs up to max_rounds times (default 3). Each iteration
        # re-runs the advisors with accumulated feedback.

        negotiation_feedback = ""

        while True:
            state.transition(PlanStatus.DRAFTING)

            typer.echo("\nRunning advisors...")
            advisor_responses, advisor_params, timing = await run_advisors(
                change_description=description,
                context=context,
                llm=llm,
                plan_id=plan_id,
                temperature_spread=settings.code_council_advisor_temperature_spread,
                negotiation_feedback=negotiation_feedback,
            )
            typer.echo(
                f"  {len(advisor_responses)} advisors completed in {timing['duration']:.1f}s"
            )

            typer.echo("\nAnalyzing advisor outputs...")
            conflict_analysis = await analyze_conflicts(
                change_description=description,
                advisor_responses=advisor_responses,
                context=context,
                llm=llm,
            )
            typer.echo("Generating plan...")
            plan = await synthesize_plan(
                change_description=description,
                advisor_responses=advisor_responses,
                context=context,
                plan_id=plan_id,
                llm=llm,
                negotiation_round=state.negotiation_round,
                conflict_analysis=conflict_analysis,
            )

            state.transition(PlanStatus.PROPOSED)

            # -- Review gate ------------------------------------------------
            # Show the plan and let the user decide.
            typer.echo(_format_plan(plan))

            round_label = (
                f" (round {state.negotiation_round + 1}/{state.max_rounds})"
                if state.negotiation_round > 0
                else ""
            )
            typer.echo(
                f"\n{'=' * 60}\n"
                f" REVIEW{round_label}\n"
                f"{'=' * 60}\n"
                f"  [a] Approve  -- accept this plan\n"
                f"  [r] Re-advise -- send back to advisors with feedback\n"
                f"  [f] Re-frame  -- go back to requirements framing\n"
                f"  [x] Reject    -- discard this plan\n"
            )

            choice = (
                typer.prompt(
                    "Your choice",
                    default="a",
                )
                .strip()
                .lower()
            )

            if choice in ("a", "approve"):
                state.transition(PlanStatus.REVIEWING)
                state.transition(PlanStatus.AGREED)
                typer.echo("\nPlan approved.")
                break

            if choice in ("x", "reject"):
                state.transition(PlanStatus.REVIEWING)
                state.transition(PlanStatus.REJECTED)
                typer.echo("\nPlan rejected.")
                break

            if choice in ("r", "re-advise"):
                state.transition(PlanStatus.REVIEWING)

                if not state.can_negotiate():
                    typer.echo(f"\nMax negotiation rounds ({state.max_rounds}) reached.")
                    stall_or_approve = (
                        typer.prompt(
                            "  [a] Approve current plan / [x] Reject",
                            default="a",
                        )
                        .strip()
                        .lower()
                    )
                    if stall_or_approve in ("x", "reject"):
                        state.transition(PlanStatus.REJECTED)
                        typer.echo("\nPlan rejected.")
                    else:
                        state.transition(PlanStatus.AGREED)
                        typer.echo("\nPlan approved.")
                    break

                feedback = typer.prompt("\n  What should the advisors reconsider?")
                if not feedback.strip():
                    typer.echo("  No feedback provided -- keeping current plan.")
                    state.transition(PlanStatus.AGREED)
                    break

                negotiation_feedback = feedback
                state.record_negotiation(
                    concerns=[feedback],
                    suggestions=[],
                    plan_changes=[],
                )
                # Loop continues: REVIEWING -> DRAFTING at top of while
                continue

            if choice in ("f", "re-frame"):
                state.transition(PlanStatus.REVIEWING)
                state.transition(PlanStatus.FRAMING)

                correction = typer.prompt("\n  What needs to change in the requirements?")
                if not correction.strip():
                    typer.echo("  No correction -- keeping current plan.")
                    # Transition back to proposed -> reviewing -> agreed
                    state.transition(PlanStatus.DRAFTING)
                    state.transition(PlanStatus.PROPOSED)
                    state.transition(PlanStatus.REVIEWING)
                    state.transition(PlanStatus.AGREED)
                    break

                # Record the correction in the transcript
                _question_counter += 1
                append_framer_message(
                    plan_id=plan_id,
                    role="user",
                    text=f"[REVIEW CORRECTION] {correction}",
                    msg_id=str(_question_counter),
                    transcript_dir=transcript_dir,
                )

                # Add the correction and re-frame
                all_answers.append(f"Q: (User correction during plan review)\nA: {correction}")
                clarification_text = "\n\n".join(all_answers)
                typer.echo("\nRe-framing with your corrections...")
                framed = await frame_request(
                    change_description=description,
                    context_summary="",
                    llm=llm,
                    clarification_answers=clarification_text,
                )

                # Show the updated requirement for confirmation
                typer.echo(_format_framed_requirement(framed))
                confirm_reframe = (
                    typer.prompt(
                        "Proceed with updated requirements? [y]es / [n]o, cancel",
                        default="y",
                    )
                    .strip()
                    .lower()
                )

                if confirm_reframe not in ("y", "yes"):
                    typer.echo("  Cancelled -- keeping original plan.")
                    state.transition(PlanStatus.DRAFTING)
                    state.transition(PlanStatus.PROPOSED)
                    state.transition(PlanStatus.REVIEWING)
                    state.transition(PlanStatus.AGREED)
                    break

                # Update the description from re-framed requirement
                description = framed.description
                negotiation_feedback = ""
                # Loop continues: FRAMING -> DRAFTING at top of while
                continue

            typer.echo(f"  Unknown choice '{choice}' -- defaulting to approve.")
            state.transition(PlanStatus.REVIEWING)
            state.transition(PlanStatus.AGREED)
            break

    # -- Phase 5: Save & output (always runs) -------------------------------

    context_summary = (
        f"Project: {context.project_path}\n"
        f"Languages: {', '.join(context.tech_stack.languages)}\n"
        f"Frameworks: {', '.join(context.tech_stack.frameworks)}\n"
        f"Tests: {context.test_patterns.test_framework}"
    )

    save_plan(
        plan_id=plan_id,
        change_description=description,
        plan_data=plan.model_dump(),
        state_data=state.model_dump(),
        advisor_responses=advisor_responses,
        context_summary=context_summary,
        framed_requirement=framed.model_dump(),
        settings=settings,
    )

    if state.status == PlanStatus.REJECTED:
        typer.echo(f"\nPlan {plan_id} saved (rejected). Use --load {plan_id} to revisit.")
    elif output_json:
        typer.echo(json.dumps(plan.model_dump(), indent=2))
    else:
        # Plan was already displayed during the review gate, so just
        # print the plan ID for reference.
        typer.echo(
            f"\nPlan {plan_id} saved ({state.status.value}). "
            f"Negotiation rounds: {state.negotiation_round}"
        )


def _format_framed_requirement(framed) -> str:
    """Format a FramedRequirement as readable text for user confirmation.

    Shows every field so the user can verify the full context before
    the advisory phase begins.
    """
    lines = [
        f"\n{'=' * 60}",
        " FRAMED REQUIREMENT",
        f"{'=' * 60}",
        f" Type:  {framed.type}",
        f" Title: {framed.title}",
        f"{'=' * 60}",
        f"\n## Description\n{framed.description}",
    ]

    if framed.acceptance_criteria:
        lines.append("\n## Acceptance Criteria")
        for i, ac in enumerate(framed.acceptance_criteria, 1):
            lines.append(f"  {i}. {ac}")

    if framed.assumptions:
        lines.append("\n## Assumptions")
        for a in framed.assumptions:
            lines.append(f"  - {a}")

    if framed.out_of_scope:
        lines.append("\n## Out of Scope")
        for o in framed.out_of_scope:
            lines.append(f"  - {o}")

    if framed.stories:
        lines.append("\n## Stories")
        for i, story in enumerate(framed.stories, 1):
            lines.append(f"  {i}. [{story.type.upper()}] {story.title}")
            lines.append(f"     {story.description}")
            if story.acceptance_criteria:
                for ac in story.acceptance_criteria:
                    lines.append(f"       - {ac}")

    lines.append("")
    return "\n".join(lines)


def _format_plan(plan) -> str:
    """Format a ChangePlan as readable text for terminal output."""
    steps_text = "\n".join(
        f"  {s.order}. [{s.action.upper()}] {s.file_path}\n"
        f"     {s.description}\n"
        f"     Depends on: {s.depends_on if s.depends_on else 'none'}"
        for s in plan.implementation_steps
    )

    criteria_text = "\n".join(f"  - {c}" for c in plan.acceptance_criteria)

    return (
        f"\n{'=' * 60}\n"
        f" PLAN: {plan.title}\n"
        f"{'=' * 60}\n"
        f" ID: {plan.plan_id}\n"
        f" Risk: {plan.risk_level} | Effort: {plan.estimated_effort}\n"
        f"{'=' * 60}\n\n"
        f"## Summary\n{plan.summary}\n\n"
        f"## Affected Files\n"
        + "\n".join(f"  - {f}" for f in plan.affected_files)
        + f"\n\n## Implementation Steps\n{steps_text}\n\n"
        f"## Architecture Notes\n{plan.architecture_notes}\n\n"
        f"## Security Notes\n{plan.security_notes}\n\n"
        f"## Quality & Tests\n{plan.quality_notes}\n\n"
        f"## Risk Assessment\n{plan.risk_assessment}\n\n"
        f"## Execution Strategy\n{plan.execution_strategy}\n\n"
        f"## Acceptance Criteria\n{criteria_text}\n"
    )


# ---------------------------------------------------------------------------
# Markdown export
# ---------------------------------------------------------------------------

_SKILLS_DIR = Path(__file__).parent / "skills"


def _load_humaniser_skill() -> str:
    """Load the humaniser skill prompt from skills/humaniser.md.

    Returns the body text below the YAML frontmatter. If the file is
    missing, returns an empty string (the export still works, just
    without humanisation).
    """
    path = _SKILLS_DIR / "humaniser.md"
    if not path.is_file():
        return ""

    text = path.read_text()
    if text.strip().startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return text[end + 3 :].strip()
    return text


async def _humanise_markdown(markdown: str, llm) -> str:
    """Pass the structured markdown through the LLM with the humaniser skill.

    The humaniser rewrites the prose sections (summary, advisor notes,
    step descriptions) to remove AI writing patterns while preserving
    the structural elements (file paths, step numbers, metadata block).

    If the humaniser skill file is missing, returns the input unchanged.
    """
    skill_text = _load_humaniser_skill()
    if not skill_text:
        return markdown

    prompt = (
        f"{skill_text}\n\n"
        "---\n\n"
        "Below is a structured implementation plan in Markdown format. "
        "Humanise the prose sections (summary, descriptions, notes, "
        "strategy, risk assessment) so they read naturally. Keep the "
        "structural elements intact:\n"
        "- All headings, subheadings, and their hierarchy\n"
        "- The metadata block (plan ID, risk, effort, timestamp)\n"
        "- File paths (in backticks), step numbers, and dependency info\n"
        "- Acceptance criteria items (keep as bullet points)\n"
        "- The framed requirement section structure\n\n"
        "Return ONLY the final rewritten Markdown document. No commentary, "
        "no draft/audit steps, no explanation.\n\n"
        "---\n\n"
        f"{markdown}"
    )

    return await llm.complete(prompt)


def _plan_to_markdown(plan_data: dict) -> str:
    """Convert a saved plan dict to a well-structured Markdown document.

    Produces a self-contained Markdown page suitable for sharing,
    documentation, or pasting into an AI coding agent. Includes all
    plan sections: summary, implementation steps with dependency info,
    advisor notes, acceptance criteria, and metadata.

    Args:
        plan_data: The full plan dict as loaded from storage (the JSON
            structure produced by ``save_plan``). The ``plan`` key holds
            the ChangePlan fields.
    """
    plan = plan_data.get("plan", {})
    plan_id = plan_data.get("plan_id", plan.get("plan_id", "unknown"))
    timestamp = plan_data.get("timestamp", "")

    title = plan.get("title", "Untitled Plan")
    summary = plan.get("summary", "")
    risk_level = plan.get("risk_level", "?")
    effort = plan.get("estimated_effort", "?")
    change_desc = plan_data.get("change_description", "")

    lines: list[str] = []

    # Header
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"> **Plan ID:** `{plan_id}`  ")
    lines.append(f"> **Risk:** {risk_level} | **Effort:** {effort}  ")
    if timestamp:
        lines.append(f"> **Created:** {timestamp}  ")
    lines.append("")

    # Original request
    if change_desc:
        lines.append("## Original Request")
        lines.append("")
        lines.append(change_desc)
        lines.append("")

    # Summary
    if summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(summary)
        lines.append("")

    # Affected files
    affected = plan.get("affected_files", [])
    if affected:
        lines.append("## Affected Files")
        lines.append("")
        for f in affected:
            lines.append(f"- `{f}`")
        lines.append("")

    # Implementation steps
    steps = plan.get("implementation_steps", [])
    if steps:
        lines.append("## Implementation Steps")
        lines.append("")
        for step in steps:
            order = step.get("order", "?")
            fp = step.get("file_path", "?")
            action = step.get("action", "?").upper()
            desc = step.get("description", "")
            deps = step.get("depends_on", [])

            lines.append(f"### Step {order}: `{fp}` [{action}]")
            lines.append("")
            lines.append(desc)
            if deps:
                dep_str = ", ".join(str(d) for d in deps)
                lines.append("")
                lines.append(f"**Depends on:** step(s) {dep_str}")
            lines.append("")

    # Advisor notes sections
    _sections = [
        ("Architecture Notes", plan.get("architecture_notes", "")),
        ("Security Notes", plan.get("security_notes", "")),
        ("Quality & Tests", plan.get("quality_notes", "")),
        ("Risk Assessment", plan.get("risk_assessment", "")),
        ("Execution Strategy", plan.get("execution_strategy", "")),
    ]
    for heading, body in _sections:
        if body:
            lines.append(f"## {heading}")
            lines.append("")
            lines.append(body)
            lines.append("")

    # Acceptance criteria
    criteria = plan.get("acceptance_criteria", [])
    if criteria:
        lines.append("## Acceptance Criteria")
        lines.append("")
        for c in criteria:
            lines.append(f"- {c}")
        lines.append("")

    # Framed requirement (if stored)
    framed = plan_data.get("framed_requirement")
    if framed:
        lines.append("## Framed Requirement")
        lines.append("")
        lines.append(f"**Type:** {framed.get('type', '?')}  ")
        lines.append(f"**Title:** {framed.get('title', '?')}  ")
        lines.append("")
        if framed.get("description"):
            lines.append(framed["description"])
            lines.append("")

        ac = framed.get("acceptance_criteria", [])
        if ac:
            lines.append("### Acceptance Criteria")
            lines.append("")
            for i, c in enumerate(ac, 1):
                lines.append(f"{i}. {c}")
            lines.append("")

        assumptions = framed.get("assumptions", [])
        if assumptions:
            lines.append("### Assumptions")
            lines.append("")
            for a in assumptions:
                lines.append(f"- {a}")
            lines.append("")

        oos = framed.get("out_of_scope", [])
        if oos:
            lines.append("### Out of Scope")
            lines.append("")
            for o in oos:
                lines.append(f"- {o}")
            lines.append("")

    # Context summary
    ctx = plan_data.get("context_summary", "")
    if ctx:
        lines.append("---")
        lines.append("")
        lines.append(f"*{ctx}*")
        lines.append("")

    return "\n".join(lines)


def _display_and_save_markdown(markdown: str, plan_id: str) -> None:
    """Print markdown to terminal and optionally save to a file.

    After displaying, asks the user if they want to save. If yes,
    prompts for the file path (defaulting to ``plan-<plan_id>.md``
    in the current directory).
    """
    typer.echo(markdown)

    save = typer.confirm("\nSave this markdown to a file?", default=False)
    if not save:
        return

    default_name = f"plan-{plan_id}.md"
    path_str = typer.prompt("File path", default=default_name)
    path = Path(path_str).expanduser().resolve()

    # If the user provided a directory, append the default filename
    if path.is_dir():
        path = path / default_name

    # Create parent directories if needed
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    typer.echo(f"Saved to {path}")


async def _export_plan_as_markdown(plan_id: str) -> None:
    """Load a plan, convert to markdown, humanise, display, and optionally save.

    This is the shared async implementation used by both the
    ``bankai export <id>`` subcommand and the
    ``bankai "export <id> to markdown"`` shortcut.
    """
    from code_council.config import get_settings
    from code_council.llm import get_llm
    from code_council.storage import load_plan

    data = load_plan(plan_id)
    if not data:
        typer.echo(f"Error: Plan '{plan_id}' not found.", err=True)
        raise typer.Exit(code=1)

    # Step 1: Build structured markdown from plan data
    typer.echo(f"\nConverting plan {plan_id} to markdown...")
    raw_markdown = _plan_to_markdown(data)

    # Step 2: Humanise the prose through the LLM
    settings = get_settings()
    try:
        settings.require_llm_credentials()
        llm = get_llm(settings)
        typer.echo("Humanising prose...")
        markdown = await _humanise_markdown(raw_markdown, llm)
    except EnvironmentError:
        # No LLM credentials -- skip humanisation, use raw markdown
        typer.echo(
            "  (Skipping humanisation -- no LLM credentials configured. "
            "Set LLM_API_KEY and LLM_BASE_URL to enable.)"
        )
        markdown = raw_markdown

    # Step 3: Display and optionally save
    _display_and_save_markdown(markdown, plan_id)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


@app.command()
def plans(
    limit: int = typer.Option(10, "--limit", "-n", help="Number of plans to show."),
) -> None:
    """List recent plans."""
    from code_council.storage import list_recent_plans

    results = list_recent_plans(limit=limit)
    if not results:
        typer.echo("No plans found.")
        return

    for p in results:
        typer.echo(
            f"  {p['plan_id']}  [{p.get('status', '?')}]  "
            f"risk={p.get('risk_level', '?')} effort={p.get('effort', '?')}  "
            f"{p.get('change_description', '')}"
        )


@app.command()
def show(
    plan_id: str = typer.Argument(..., help="Plan ID to display."),
) -> None:
    """View a specific plan."""
    from code_council.storage import load_plan

    data = load_plan(plan_id)
    if not data:
        typer.echo(f"Plan '{plan_id}' not found.", err=True)
        raise typer.Exit(code=1)

    typer.echo(json.dumps(data, indent=2))


@app.command()
def export(
    plan_id: str = typer.Argument(..., help="Plan ID to export as Markdown."),
) -> None:
    """Export a plan as a Markdown document.

    Loads the plan by ID, converts it to a structured Markdown page,
    runs it through the humaniser to clean up AI writing patterns,
    prints it to the terminal, and optionally saves to a file.
    """
    asyncio.run(_export_plan_as_markdown(plan_id))


@app.command()
def serve(
    port: int = typer.Option(8766, "--port", help="Port to listen on."),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to."),
) -> None:
    """Start the Code Council web UI server.

    Launches a FastAPI server that powers the browser-based wizard
    for framing, advising, and plan synthesis.  Binds to localhost
    by default (no external access).

    Usage:
        bankai serve              # http://127.0.0.1:8765
        bankai serve --port 9000  # http://127.0.0.1:9000
    """
    import uvicorn

    typer.echo(f"\n  Code Council server starting on http://{host}:{port}")
    typer.echo("  Press Ctrl+C to stop.\n")

    uvicorn.run(
        "code_council.daemon:app",
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    app()
