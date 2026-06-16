"""Plan storage for code-council.

Saves each plan as a JSON file under the configured plan directory.
Provides queries for recent plans and lookup by ID.

Python lesson: why JSON files instead of a database?
    For a local tool that stores 10-50 plans, flat JSON files are simpler
    than SQLite/Postgres. Each plan is one file, easy to inspect with any
    text editor, easy to back up (just copy the directory). The trade-off:
    no queries beyond "list by modification time." That's fine for our use case.

Python lesson: **kwargs (keyword-only arguments)
    save_plan uses `*` to force all arguments to be keyword-only:
        save_plan(plan_id="x", ...)  -- OK
        save_plan("x", ...)          -- TypeError
    This prevents bugs from argument ordering -- when a function has 7
    string parameters, positional args are asking for trouble.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from code_council.config import Settings, get_settings
from code_council.utils import plan_filename_stem

logger = logging.getLogger(__name__)


def _ensure_dir(path: Path) -> None:
    """Create directory and parents if they don't exist.

    exist_ok=True means no error if the directory already exists.
    parents=True means create intermediate directories too.
    """
    path.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


def save_plan(
    *,
    plan_id: str,
    change_description: str,
    plan_data: dict[str, Any],
    state_data: dict[str, Any],
    advisor_responses: dict[str, str],
    context_summary: str,
    framed_requirement: dict[str, Any] | None = None,
    base_plan_id: str | None = None,
    token_usage: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> Path | None:
    """Persist a plan as JSON. Returns the file path or None if disabled.

    The * in the signature means ALL arguments must be passed as keywords.
    This is defensive -- with 7+ parameters, positional args are error-prone.

    Args:
        framed_requirement: The structured FramedRequirement (model_dump()).
            Stored so that ``bankai "load context: <plan_id>"`` can
            reconstruct the framing without re-running the LLM.
        base_plan_id: For re-advise plans, the plan_id of the original
            plan this review is based on.  ``None`` for first-time plans.
        token_usage: Per-stage and total token usage from the pipeline.
            Produced by ``TokenTracker.to_dict()``.
    """
    settings = settings or get_settings()
    if not settings.code_council_save_plans:
        return None

    plan_dir = settings.plan_path
    _ensure_dir(plan_dir)

    ts = datetime.now(timezone.utc).isoformat()
    stem = plan_filename_stem(plan_id, change_description)

    # Council-reviewed plans now get their own plan_id (generated in
    # daemon.py) so they are saved as a separate file naturally via
    # the unique hex prefix.  The original plan is preserved because
    # it has a different plan_id and file.
    filename = f"plan-{stem}.json"

    path = plan_dir / filename

    data: dict[str, Any] = {
        "plan_id": plan_id,
        "timestamp": ts,
        "change_description": change_description,
        "plan": plan_data,
        "state": state_data,
        "advisor_responses": advisor_responses,
        "context_summary": context_summary,
        "base_plan_id": base_plan_id,
    }
    if framed_requirement is not None:
        data["framed_requirement"] = framed_requirement
    if token_usage is not None:
        data["token_usage"] = token_usage

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    logger.info("Plan saved to %s", path)
    return path


def save_council_review(
    *,
    plan_id: str,
    advisor_reviews: dict[str, str],
    decision: dict[str, Any],
    settings: Settings | None = None,
) -> Path | None:
    """Append council review results to an existing plan file.

    Called after the council feedback pipeline completes.  Reads the
    existing plan JSON, adds a ``council_review`` key with the advisor
    reviews and decision gate output, and writes it back.

    Returns the file path, or None if the plan was not found or saving
    is disabled.
    """
    settings = settings or get_settings()
    if not settings.code_council_save_plans:
        return None

    plan_dir = settings.plan_path

    # Find the plan file by ID.
    path: Path | None = None
    exact = plan_dir / f"plan-{plan_id}.json"
    if exact.is_file():
        path = exact
    else:
        matches = list(plan_dir.glob(f"plan-{plan_id}-*.json"))
        if matches:
            matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            path = matches[0]

    if path is None:
        logger.warning("Cannot save council review: plan %s not found", plan_id)
        return None

    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Cannot read plan %s for council review update: %s", plan_id, exc)
        return None

    data["council_review"] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "advisor_reviews": advisor_reviews,
        "decision": decision,
    }

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    logger.info("Council review saved to %s", path)
    return path


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


def load_plan(plan_id: str, settings: Settings | None = None) -> dict[str, Any] | None:
    """Load a plan by ID. Returns the plan dict or None if not found.

    Filenames include a human-readable slug (``plan-<hex>-<slug>.json``),
    but the ``plan_id`` is just the hex prefix.  We try an exact match
    first (``plan-<plan_id>.json`` for backward compat), then glob for
    ``plan-<plan_id>-*.json``.

    Returns None (not raises) for missing or corrupt files. This is the
    "forgiving" approach -- the caller decides what to do about missing plans,
    not us. Crashing because a JSON file is corrupt would be poor UX.
    """
    settings = settings or get_settings()
    plan_dir = settings.plan_path

    # Exact match (backward compat with old slug-in-id filenames)
    exact = plan_dir / f"plan-{plan_id}.json"
    if exact.is_file():
        try:
            return json.loads(exact.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load plan %s: %s", plan_id, exc)
            return None

    # Glob match: plan-<hex>-<slug>.json
    matches = list(plan_dir.glob(f"plan-{plan_id}-*.json"))
    if not matches:
        return None
    # Take the most recent if multiple (shouldn't happen)
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    try:
        return json.loads(matches[0].read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load plan %s: %s", plan_id, exc)
        return None


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


def list_recent_plans(
    limit: int = 10,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Return metadata for the most recent plans.

    Sorted by the ``timestamp`` field stored inside each plan JSON
    (i.e. the creation time), most recent first.
    Only returns summary metadata, not full plan contents.
    """
    settings = settings or get_settings()
    plan_dir = settings.plan_path
    if not plan_dir.is_dir():
        return []

    results: list[dict[str, Any]] = []
    for fp in plan_dir.glob("plan-*.json"):
        try:
            data = json.loads(fp.read_text())
            results.append(
                {
                    "plan_id": data.get("plan_id", ""),
                    "timestamp": data.get("timestamp", ""),
                    "change_description": (data.get("change_description", ""))[:120],
                    "status": data.get("state", {}).get("status", "unknown"),
                    "risk_level": data.get("plan", {}).get("risk_level", ""),
                    "effort": data.get("plan", {}).get("estimated_effort", ""),
                    "base_plan_id": data.get("base_plan_id"),
                    "has_council_review": "council_review" in data,
                }
            )
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping unreadable plan %s: %s", fp, exc)

    # Sort by creation timestamp (ISO-8601), most recent first.
    results.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return results[:limit]


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def delete_plan(plan_id: str, settings: Settings | None = None) -> bool:
    """Delete a plan by ID. Returns True if deleted."""
    settings = settings or get_settings()
    plan_dir = settings.plan_path

    # Exact match (backward compat)
    exact = plan_dir / f"plan-{plan_id}.json"
    if exact.is_file():
        exact.unlink()
        logger.info("Plan deleted: %s", exact)
        return True

    # Glob match: plan-<hex>-<slug>.json
    matches = list(plan_dir.glob(f"plan-{plan_id}-*.json"))
    if matches:
        matches[0].unlink()
        logger.info("Plan deleted: %s", matches[0])
        return True

    return False
