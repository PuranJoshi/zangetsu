"""Plan synthesis from advisor outputs.

Receives all advisor analyses and produces a structured ChangePlan
with affected files, implementation steps, sequencing, risks, and
acceptance criteria.

Python lesson: Pydantic for API boundaries
    ChangePlan is a Pydantic BaseModel because it's the main output
    of the system -- it gets serialized to JSON, saved to disk, and
    displayed to the user. Pydantic gives us:
    - Automatic validation (risk_level must be a string, etc.)
    - .model_dump() for JSON serialization
    - Clear field documentation via docstrings
"""

from __future__ import annotations

import json
import logging
from typing import Protocol

from pydantic import BaseModel

from code_council.advisors import discover_analysis_skill, discover_synthesizer_skill
from code_council.context import ProjectContext

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    async def complete(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> str: ...


# ---------------------------------------------------------------------------
# ChangePlan data model
# ---------------------------------------------------------------------------


class ImplementationStep(BaseModel):
    """A single step in the implementation plan."""

    order: int
    """Execution order (1-based)."""

    file_path: str
    """Relative path to the file being changed."""

    action: str
    """What to do: 'create', 'modify', 'delete', 'rename'."""

    description: str
    """What specifically to change in this file and why."""

    depends_on: list[int] = []
    """Step numbers that must be completed before this one."""

    story: str = ""
    """Short user-story label grouping related steps (e.g. 'Auth setup')."""


class IncrementalChange(BaseModel):
    """A JIRA-style task representing a shippable slice of work."""

    type: str = "story"
    """Jira type: story | task | bug"""

    title: str
    """Short descriptive title (e.g. 'Add user auth middleware')."""

    description: str
    """What this change does and why."""

    acceptance_criteria: list[str] = []
    """Human-readable behaviour descriptions (Given/When/Then or plain English)."""

    steps: list[int] = []
    """Implementation step order numbers belonging to this change."""


class ChangePlan(BaseModel):
    """Structured implementation plan produced by the synthesizer.

    This is the main output of the bankai pipeline -- what you copy
    into your AI coding agent as implementation instructions.
    """

    plan_id: str
    title: str
    summary: str
    change_description: str

    affected_files: list[str]
    implementation_steps: list[ImplementationStep]
    incremental_changes: list[IncrementalChange] = []

    architecture_notes: str
    security_notes: str
    quality_notes: str
    risk_assessment: str
    execution_strategy: str

    acceptance_criteria: list[str]
    estimated_effort: str
    """S / M / L / XL"""

    risk_level: str
    """LOW / MEDIUM / HIGH"""

    negotiation_round: int = 0
    raw_advisor_responses: dict[str, str] = {}


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------


def _extract_json(text: str) -> str:
    """Extract JSON from a response that may contain markdown code fences."""
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


def _analysis_prompt(
    change_description: str,
    advisor_responses: dict[str, str],
    context: ProjectContext,
) -> str:
    """Build the prompt for Pass 1: conflict analysis.

    This prompt asks the LLM to read all advisor outputs, identify
    agreements and conflicts, and produce a structured markdown
    document resolving disagreements -- before the plan is generated.
    """
    skill_text = discover_analysis_skill()

    advisor_section = "\n\n".join(
        f"**{name}:**\n{text}" for name, text in advisor_responses.items()
    )

    tech_summary = (
        f"Languages: {', '.join(context.tech_stack.languages)}, "
        f"Frameworks: {', '.join(context.tech_stack.frameworks)}, "
        f"Tests: {context.test_patterns.test_framework}"
    )

    parts = []
    if skill_text:
        parts.append(f"{skill_text}\n\n---\n")

    parts.append(
        "You are the Conflict Analyst for a Code Council. Your job is to "
        "read all advisor analyses, identify where they agree and disagree, "
        "and produce a structured conflict resolution document.\n\n"
        f"**Project:** {context.project_path}\n"
        f"**Stack:** {tech_summary}\n\n"
        "The user wants to make this change:\n\n"
        "---\n"
        f"{change_description}\n"
        "---\n\n"
        f"ADVISOR ANALYSES:\n\n{advisor_section}\n\n"
        "---\n\n"
        "Produce the conflict analysis as structured markdown. "
        "Do NOT produce JSON or implementation steps."
    )
    return "\n".join(parts)


def _synthesizer_prompt(
    change_description: str,
    advisor_responses: dict[str, str],
    context: ProjectContext,
    conflict_analysis: str = "",
) -> str:
    """Build the prompt for the plan synthesizer.

    When *conflict_analysis* is provided (two-pass mode), it is included
    as a ``CONFLICT ANALYSIS`` section before the raw advisor outputs so
    the synthesizer can use it as its primary reasoning input.
    """
    skill_text = discover_synthesizer_skill()

    advisor_section = "\n\n".join(
        f"**{name}:**\n{text}" for name, text in advisor_responses.items()
    )

    tech_summary = (
        f"Languages: {', '.join(context.tech_stack.languages)}, "
        f"Frameworks: {', '.join(context.tech_stack.frameworks)}, "
        f"Tests: {context.test_patterns.test_framework}"
    )

    parts = []
    if skill_text:
        parts.append(f"{skill_text}\n\n---\n")

    analysis_block = ""
    if conflict_analysis:
        analysis_block = (
            "CONFLICT ANALYSIS (from Pass 1 -- use as primary reasoning input):\n\n"
            f"{conflict_analysis}\n\n"
            "---\n\n"
        )

    parts.append(
        "You are the Plan Synthesizer for a Code Council. Your job is to "
        "take the analyses from code advisors and produce a single, "
        "structured implementation plan.\n\n"
        f"**Project:** {context.project_path}\n"
        f"**Stack:** {tech_summary}\n\n"
        "The user wants to make this change:\n\n"
        "---\n"
        f"{change_description}\n"
        "---\n\n"
        f"{analysis_block}"
        f"ADVISOR ANALYSES:\n\n{advisor_section}\n\n"
        "---\n\n"
        "Produce the implementation plan as valid JSON:\n\n"
        "```json\n"
        "{\n"
        '  "title": "Short title",\n'
        '  "summary": "One paragraph summary",\n'
        '  "affected_files": ["path/to/file.py", "path/to/other.py"],\n'
        '  "incremental_changes": [\n'
        '    {"type": "story", "title": "Set up database models",\n'
        '     "description": "Create the ORM models for user and session",\n'
        '     "acceptance_criteria": [\n'
        '      "Given a new user registers, when the data is persisted, '
        'then a user record exists with email and password hash",\n'
        '      "Given a user logs in, when a session is created, '
        'then the session references the user and has an expiry time"],\n'
        '     "steps": [1, 2]},\n'
        '    {"type": "task", "title": "Wire up API endpoint",\n'
        '     "description": "Add the REST handler for login",\n'
        '     "acceptance_criteria": [\n'
        '      "When a user submits valid credentials to the login endpoint, '
        'they receive an authentication token"],\n'
        '     "steps": [3]}\n'
        "  ],\n"
        '  "implementation_steps": [\n'
        '    {"order": 1, "file_path": "path/to/file.py", "action": "modify",\n'
        '     "description": "What to change", "depends_on": [],\n'
        '     "story": "Set up database models"},\n'
        '    {"order": 2, "file_path": "path/to/other.py", "action": "create",\n'
        '     "description": "What to create", "depends_on": [1],\n'
        '     "story": "Set up database models"},\n'
        '    {"order": 3, "file_path": "path/to/handler.py", "action": "create",\n'
        '     "description": "Wire up the endpoint", "depends_on": [2],\n'
        '     "story": "Wire up API endpoint"}\n'
        "  ],\n"
        '  "architecture_notes": "...",\n'
        '  "security_notes": "...",\n'
        '  "quality_notes": "...",\n'
        '  "risk_assessment": "...",\n'
        '  "execution_strategy": "...",\n'
        '  "acceptance_criteria": [\n'
        '    "A user can register, log in, and receive a session token"],\n'
        '  "estimated_effort": "M",\n'
        '  "risk_level": "MEDIUM"\n'
        "}\n"
        "```\n\n"
        "IMPORTANT RULES:\n"
        "- `depends_on` must be a list of integer step numbers "
        "(the `order` field), NOT file paths. For example, if step 2 "
        'depends on step 1, use `"depends_on": [1]`.\n'
        "- `story` on each step groups it into a user story. Use the "
        "same label as the matching `incremental_changes` entry.\n"
        "- `incremental_changes` breaks the work into small, shippable "
        "JIRA-style tasks (story/task/bug). Each one should be independently "
        "completable and verifiable. Include human-readable acceptance "
        "criteria in Given/When/Then or plain English that describe "
        "observable behaviour -- NOT test file paths, test function names, "
        "or code-level assertions. The `steps` array lists "
        "which implementation_step order numbers belong to that change. "
        "Order them so earlier changes have no dependency on later ones.\n"
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# depends_on repair
# ---------------------------------------------------------------------------


def _fix_depends_on(data: dict) -> dict:
    """Ensure ``depends_on`` contains integer step numbers, not file paths.

    Some LLMs return file paths in ``depends_on`` instead of the ``order``
    integers.  This helper detects that and converts them using a
    file_path -> order lookup built from the steps themselves.  Entries
    that cannot be resolved are dropped with a warning.
    """
    steps = data.get("implementation_steps")
    if not steps:
        return data

    # Build file_path -> order lookup
    path_to_order: dict[str, int] = {}
    for step in steps:
        fp = step.get("file_path")
        order = step.get("order")
        if fp and order is not None:
            path_to_order[fp] = order

    for step in steps:
        raw_deps = step.get("depends_on", [])
        if not raw_deps:
            continue

        fixed: list[int] = []
        for dep in raw_deps:
            if isinstance(dep, int):
                fixed.append(dep)
            elif isinstance(dep, str):
                # Try to parse as int first (e.g. "1")
                try:
                    fixed.append(int(dep))
                except ValueError:
                    # Assume it's a file path -- resolve to step order
                    order = path_to_order.get(dep)
                    if order is not None:
                        fixed.append(order)
                    else:
                        logger.warning(
                            "depends_on entry %r in step %s could not be "
                            "resolved to a step number -- dropping it",
                            dep,
                            step.get("order"),
                        )
        step["depends_on"] = fixed

    return data


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------


async def analyze_conflicts(
    change_description: str,
    advisor_responses: dict[str, str],
    context: ProjectContext,
    llm: LLMClient,
) -> str:
    """Pass 1: Analyze advisor outputs and resolve conflicts.

    Reads all advisor analyses and produces a structured markdown
    document identifying agreements, conflicts, resolutions, and
    emergent insights.  The returned text is fed into
    ``synthesize_plan`` as the *conflict_analysis* parameter so the
    plan synthesizer can focus on structured output.
    """
    prompt = _analysis_prompt(change_description, advisor_responses, context)
    return await llm.complete(prompt)


async def synthesize_plan(
    change_description: str,
    advisor_responses: dict[str, str],
    context: ProjectContext,
    plan_id: str,
    llm: LLMClient,
    negotiation_round: int = 0,
    conflict_analysis: str = "",
) -> ChangePlan:
    """Synthesize a ChangePlan from advisor responses.

    Two-pass synthesis:

    1. If *conflict_analysis* is provided, it is injected into the
       synthesizer prompt so the LLM can use pre-computed reasoning
       about advisor agreements, conflicts, and resolutions.
    2. The LLM produces structured JSON matching the ``ChangePlan``
       schema.  Retries once if JSON is invalid.

    Callers should call ``analyze_conflicts`` first and pass the result
    as *conflict_analysis*.  If omitted, the synthesizer falls back to
    single-pass mode (backward-compatible).
    """
    prompt = _synthesizer_prompt(change_description, advisor_responses, context, conflict_analysis)
    raw_response = await llm.complete(prompt)
    json_text = _extract_json(raw_response)

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        repair_prompt = (
            "The previous response was not valid JSON. "
            "Fix it and return ONLY the corrected JSON:\n\n"
            f"{raw_response}"
        )
        raw_response = await llm.complete(repair_prompt)
        json_text = _extract_json(raw_response)
        data = json.loads(json_text)

    # Build a lookup from file_path -> order so we can fix depends_on
    # values that are file paths instead of step numbers.
    data = _fix_depends_on(data)

    return ChangePlan(
        plan_id=plan_id,
        change_description=change_description,
        negotiation_round=negotiation_round,
        raw_advisor_responses=advisor_responses,
        **data,
    )
