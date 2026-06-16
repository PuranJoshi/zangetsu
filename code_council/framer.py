"""Requirements Framer -- the gate before technical advisors.

Takes a raw feature request and produces structured requirements in
Jira-style format (epic, story, task, or bug). If the request is
ambiguous, produces clarifying questions that must be answered before
proceeding.

This is Phase 1 of the bankai pipeline:
    User request -> Framer -> [clarification loop] -> Advisors -> Synthesizer

Python lesson: separation of concerns
    The Framer is NOT an advisor. It runs BEFORE the advisors, in a
    separate phase. This is why it's in its own module (framer.py) rather
    than being another entry in the skills/ registry. It has a different
    job: define WHAT to build (requirements), not HOW to build it (plan).

Python lesson: Pydantic model with a method
    FramedRequirement.needs_clarification() is a method on a Pydantic model.
    Pydantic models can have methods just like regular classes. The model
    gives you data validation + serialization, and methods give you
    behaviour. Best of both worlds.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from code_council.config import get_skill_model
from code_council.llm import LLMResult, TokenUsage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM Protocol (same as advisors.py -- see Python lesson there)
# ---------------------------------------------------------------------------


class LLMClient(Protocol):
    async def complete(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        seed: int | None = None,
        model: str | None = None,
    ) -> str: ...

    async def complete_with_usage(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        seed: int | None = None,
        model: str | None = None,
    ) -> LLMResult: ...


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class FramedRequirement(BaseModel):
    """Structured requirement produced by the Framer.

    Maps to Jira work item types:
    - epic: large effort broken into stories
    - story: single user-facing feature
    - task: technical work, not directly user-facing
    - bug: something is broken

    If clarifications_needed is non-empty, the pipeline pauses and
    the user must answer before advisors run.
    """

    type: str
    """One of: epic, story, task, bug"""

    title: str
    """Short descriptive title."""

    description: str
    """What this change does and why it matters."""

    acceptance_criteria: list[str] = []
    """Testable conditions that must be true when done.
    Ideally in Given/When/Then format for user-facing behaviour."""

    out_of_scope: list[str] = []
    """Things explicitly NOT included in this work."""

    assumptions: list[str] = []
    """Things assumed to be true."""

    clarifications_needed: list[str] = []
    """Questions that must be answered before proceeding.
    If non-empty, the pipeline pauses."""

    stories: list[FramedRequirement] = []
    """Sub-stories if type is 'epic'."""

    def needs_clarification(self) -> bool:
        """Check if there are unanswered questions blocking progress."""
        return len(self.clarifications_needed) > 0


# ---------------------------------------------------------------------------
# Skill loader
# ---------------------------------------------------------------------------

_SKILLS_DIR = Path(__file__).parent / "skills"


def _load_framer_skill() -> str:
    """Load the framer skill prompt from skills/framer.md.

    Unlike advisors (which are discovered dynamically), the framer
    is loaded by explicit path because there's exactly one framer.
    It uses the same frontmatter format though, and we extract just
    the body (below the ---).
    """
    path = _SKILLS_DIR / "framer.md"
    if not path.is_file():
        logger.warning("Framer skill not found at %s", path)
        return ""

    text = path.read_text()
    # Extract body below frontmatter
    if text.strip().startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return text[end + 3 :].strip()
    return text


# ---------------------------------------------------------------------------
# JSON extraction (same pattern as synthesizer)
# ---------------------------------------------------------------------------


def _backfill_story_types(data: dict) -> dict:
    """Ensure every sub-story has a ``type`` field.

    LLMs sometimes omit ``type`` from sub-stories inside an epic even
    though ``FramedRequirement`` requires it.  Walk the tree and default
    missing types to ``"story"``.
    """
    for story in data.get("stories", []):
        if "type" not in story:
            story["type"] = "story"
        _backfill_story_types(story)  # recurse for nested epics
    return data


def _extract_json(text: str) -> str:
    """Extract JSON from a response that may contain markdown code fences.

    The LLM often wraps JSON in ```json ... ``` blocks. This function
    strips the fences to get the raw JSON.

    Python lesson: str.index() vs str.find()
        index() raises ValueError if not found -- use when missing is a bug.
        find() returns -1 if not found -- use when missing is expected.
        Here we use index() after confirming the substring exists with 'in'.
    """
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        return text[start:end].strip()
    if "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        return text[start:end].strip()
    return text.strip()


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def _framer_prompt(
    change_description: str,
    context_summary: str,
    clarification_answers: str = "",
) -> str:
    """Build the prompt for the Framer.

    Args:
        change_description: The raw feature request from the user.
        context_summary: Brief summary of the project context (tech stack, etc.)
        clarification_answers: If this is a follow-up after clarifying questions
            were asked, this contains the user's answers.
    """
    skill_text = _load_framer_skill()

    parts = []
    if skill_text:
        parts.append(f"{skill_text}\n\n---\n")

    if context_summary:
        parts.append(f"## Project Context\n\n{context_summary}\n\n---\n")

    parts.append(
        f"A user has submitted the following feature request:\n\n---\n{change_description}\n---\n\n"
    )

    if clarification_answers:
        parts.append(
            "## Clarification Answers\n\n"
            "The user previously answered these clarifying questions:\n\n"
            f"{clarification_answers}\n\n---\n\n"
            "Incorporate these answers and produce updated requirements. "
            "If more clarification is still needed, include new questions "
            "in clarifications_needed.\n\n"
        )

    parts.append(
        "Produce the structured requirement as a JSON object. "
        "Use the exact format specified in your skill reference.\n\n"
        "If the request is clear enough, set clarifications_needed to an "
        "empty list. If it's ambiguous, list your questions there.\n"
    )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------


async def frame_request(
    change_description: str,
    context_summary: str,
    llm: LLMClient,
    clarification_answers: str = "",
) -> tuple[FramedRequirement, TokenUsage]:
    """Frame a raw feature request into structured requirements.

    This is the entry point called by the bankai pipeline. It:
    1. Builds a prompt with the framer skill + project context
    2. Calls the LLM to produce structured requirements
    3. Parses the JSON response into a FramedRequirement
    4. If parsing fails, retries once with a repair prompt

    Returns ``(FramedRequirement, TokenUsage)`` -- the framed result
    plus accumulated token usage from all LLM calls in this stage.

    The caller checks result.needs_clarification() to decide whether
    to pause and ask the user for answers, or proceed to advisors.
    """
    framer_model = get_skill_model("framer") or None
    stage_usage = TokenUsage()

    prompt = _framer_prompt(
        change_description,
        context_summary,
        clarification_answers,
    )

    result = await llm.complete_with_usage(prompt, model=framer_model)
    raw_response = result.text
    stage_usage += result.usage

    json_text = _extract_json(raw_response)

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        # Retry with a repair prompt
        repair_prompt = (
            "The previous response was not valid JSON. "
            "Please fix the JSON and return ONLY the corrected JSON block:\n\n"
            f"{raw_response}"
        )
        retry_result = await llm.complete_with_usage(repair_prompt, model=framer_model)
        raw_response = retry_result.text
        stage_usage += retry_result.usage
        json_text = _extract_json(raw_response)
        data = json.loads(json_text)

    _backfill_story_types(data)
    return FramedRequirement(**data), stage_usage
