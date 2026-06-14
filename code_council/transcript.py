"""Transcript storage for code-council.

Records the running transcript of a bankai session: the original question,
every framer exchange (question, answer, choices), and the final framed
requirement.  The transcript file is created when the pipeline starts and
appended to after each meaningful event so progress is never lost.

Transcripts live under ``~/.code-council/transcripts/`` (separate from
plans) and are keyed by ``plan_id``.

Python lesson: append-style JSON storage
    JSON doesn't natively support "append."  We handle this by reading
    the whole file, mutating the dict, and rewriting it.  For the small
    files we produce (< 100 KB) this is fine.  If we ever need streaming
    writes, JSONL (one JSON object per line) would be the right tool.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default transcript directory -- can be overridden via Settings
_DEFAULT_TRANSCRIPT_DIR = Path.home() / ".code-council" / "transcripts"


def _ensure_dir(path: Path) -> None:
    """Create directory and parents if they don't exist."""
    path.mkdir(parents=True, exist_ok=True)


def _transcript_path(plan_id: str, transcript_dir: Path | None = None) -> Path:
    """Return the path for a transcript file."""
    directory = transcript_dir or _DEFAULT_TRANSCRIPT_DIR
    return directory / f"transcript-{plan_id}.json"


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def init_transcript(
    *,
    plan_id: str,
    question: str,
    transcript_dir: Path | None = None,
    base_plan_id: str | None = None,
    status: str = "active",
) -> Path:
    """Create a new transcript file with the original question.

    Called once at the start of a pipeline run.  Returns the file path.

    Args:
        plan_id: Unique identifier for this pipeline run.
        question: The user's original feature request.
        transcript_dir: Override the transcript directory (for testing).
        base_plan_id: For review transcripts, the plan_id of the original
            plan being re-advised.  ``None`` for first-time plans.
        status: ``"active"`` for normal pipeline runs, ``"review"`` for
            re-advise sessions initiated from an existing plan.
    """
    directory = transcript_dir or _DEFAULT_TRANSCRIPT_DIR
    _ensure_dir(directory)

    data: dict[str, Any] = {
        "plan_id": plan_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "question": question,
        "framer_messages": [],
        "framed_question": None,
        "base_plan_id": base_plan_id,
        "status": status,
    }

    path = _transcript_path(plan_id, directory)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    logger.info("Transcript created at %s", path)
    return path


def append_framer_message(
    *,
    plan_id: str,
    role: str,
    text: str,
    msg_id: str | None = None,
    choices: list[str] | None = None,
    transcript_dir: Path | None = None,
) -> None:
    """Append a single message to the framer_messages list.

    Args:
        plan_id: The plan ID linking this transcript to a pipeline run.
        role: One of ``"user"``, ``"framer"``.
        text: The message content (question text or user answer).
        msg_id: Optional identifier linking a framer question to its answer.
        choices: Optional list of choices the framer offered (framer role only).
        transcript_dir: Override the transcript directory (for testing).
    """
    path = _transcript_path(plan_id, transcript_dir)
    data = _read_transcript(path)
    if data is None:
        logger.warning("Transcript %s not found; skipping append", plan_id)
        return

    message: dict[str, Any] = {"role": role, "text": text}
    if msg_id is not None:
        message["msg_id"] = msg_id
    if choices is not None:
        message["choices"] = choices

    data["framer_messages"].append(message)
    _write(path, data)


def set_framed_question(
    *,
    plan_id: str,
    framed_question: str,
    transcript_dir: Path | None = None,
) -> None:
    """Record the final framed requirement text once clarifications resolve.

    This is the polished requirement the framer produced after all Q&A.
    """
    path = _transcript_path(plan_id, transcript_dir)
    data = _read_transcript(path)
    if data is None:
        logger.warning("Transcript %s not found; skipping framed_question", plan_id)
        return

    data["framed_question"] = framed_question
    _write(path, data)


def load_transcript(
    plan_id: str,
    transcript_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Load a transcript by plan_id.  Returns None if not found or corrupt."""
    path = _transcript_path(plan_id, transcript_dir)
    return _read_transcript(path)


def list_recent_transcripts(
    limit: int = 10,
    transcript_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Return summary metadata for the most recent transcripts.

    Sorted by file modification time (most recent first).
    Returns plan_id, timestamp, question (truncated), status,
    base_plan_id, and whether a framed_question exists.
    """
    directory = transcript_dir or _DEFAULT_TRANSCRIPT_DIR
    if not directory.is_dir():
        return []

    files = sorted(
        directory.glob("transcript-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    results: list[dict[str, Any]] = []
    for fp in files[:limit]:
        try:
            data = json.loads(fp.read_text())
            results.append({
                "plan_id": data.get("plan_id", ""),
                "timestamp": data.get("timestamp", ""),
                "question": (data.get("question", ""))[:120],
                "status": data.get("status", "active"),
                "base_plan_id": data.get("base_plan_id"),
                "has_framed_question": data.get("framed_question") is not None,
                "message_count": len(data.get("framer_messages", [])),
            })
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping unreadable transcript %s: %s", fp, exc)

    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_transcript(path: Path) -> dict[str, Any] | None:
    """Read and parse a transcript file.  Returns None on error."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read transcript %s: %s", path, exc)
        return None


def _write(path: Path, data: dict[str, Any]) -> None:
    """Atomically-ish rewrite the transcript file."""
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
