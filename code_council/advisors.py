"""Code change advisors -- skill registry and parallel execution.

Advisors are auto-discovered from self-describing Markdown files in
code_council/skills/. Each .md file with YAML frontmatter declaring
type: advisor is registered as an advisor.

Adding a new advisor = dropping a new .md file into skills/.
Disabling an advisor = setting enabled: false in its frontmatter.
No Python code changes needed.

Python lesson: @dataclass vs Pydantic BaseModel
    We use @dataclass for AdvisorSkill (not Pydantic) because:
    1. It's internal data, not user-facing or serialized to JSON.
    2. Dataclasses are lighter -- no validation overhead.
    3. Pydantic is for boundaries (API input/output, config, storage).
       Internal data structures are fine as plain dataclasses.

Python lesson: Protocol
    LLMClient is a Protocol class. It defines an interface WITHOUT
    requiring inheritance. Any class that has a matching `complete()`
    method will satisfy the Protocol. This is "structural subtyping"
    (aka duck typing with type checker support). It means:
    - Real code uses OpenAICompatibleLLM (talks to the API)
    - Tests use FakeLLM (returns canned responses)
    - Neither needs to inherit from LLMClient

Python lesson: yaml.safe_load vs yaml.load
    Always use safe_load(). Regular load() can execute arbitrary Python
    code embedded in YAML (!!python/object constructors). safe_load()
    only parses basic YAML types (strings, numbers, lists, dicts).
    There's no reason to use load() unless you specifically need to
    deserialize Python objects from YAML, which is almost never.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from code_council.config import get_skill_model
from code_council.context import ProjectContext
from code_council.llm import LLMResult, TokenUsage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM Protocol
# ---------------------------------------------------------------------------

Message = dict[str, str]


class LLMClient(Protocol):
    """Minimal async LLM interface.

    Any class with a matching complete() method satisfies this Protocol.
    No inheritance required -- this is structural (duck) typing.
    """

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
# Skill data model
# ---------------------------------------------------------------------------

_SKILLS_DIR = Path(__file__).parent / "skills"


@dataclass
class AdvisorSkill:
    """A single advisor skill discovered from a .md file.

    Each field maps to a key in the YAML frontmatter:
        ---
        name: architect
        type: advisor
        display_name: Architect Advisor
        role_description: You are the Architect Advisor...
        temperature_rank: 4
        seed_offset: 4
        enabled: true
        ---
    """

    name: str
    """Internal name (e.g., 'architect'). Used for seed generation."""

    display_name: str
    """Human-readable name (e.g., 'Architect Advisor')."""

    role_description: str
    """Short role description injected into the prompt preamble."""

    skill_text: str
    """Full Markdown body (below frontmatter) -- the detailed skill prompt."""

    temperature_rank: int
    """Rank for temperature assignment (0 = lowest/most concrete)."""

    seed_offset: int
    """Offset added to the base seed for diversity."""

    enabled: bool = True
    """Whether this advisor is active."""

    model: str = ""
    """Optional LLM model override. If set, this advisor uses a different
    model than the global default. For example:
        architect.md -> model: gpt-4o
        business.md  -> model: claude-sonnet
        executor.md  -> model: (empty, uses default)
    Empty string means "use the default model from config.py".
    Only override when you have a specific reason -- avoid using
    expensive reasoning models unless explicitly needed.
    """

    source_path: str = ""
    """Path to the source .md file (for debugging/logging)."""


# ---------------------------------------------------------------------------
# Frontmatter parser
# ---------------------------------------------------------------------------


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a Markdown file.

    Expects the format:
        ---
        key: value
        ---
        Body text here

    Returns (frontmatter_dict, body_text).
    If no valid frontmatter found, returns ({}, full_text).

    Python lesson: str.find() vs str.index()
        find() returns -1 if not found. index() raises ValueError.
        Use find() when missing is expected (not an error).
        Use index() when missing is a bug.
    """
    text = text.strip()
    if not text.startswith("---"):
        return {}, text

    # Find the closing --- (start searching after the opening ---)
    end = text.find("---", 3)
    if end == -1:
        return {}, text

    yaml_text = text[3:end].strip()
    body = text[end + 3 :].strip()

    try:
        frontmatter = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse YAML frontmatter: %s", exc)
        return {}, text

    return frontmatter, body


# ---------------------------------------------------------------------------
# Skill discovery
# ---------------------------------------------------------------------------


def discover_advisor_skills(
    skills_dir: Path | None = None,
) -> list[AdvisorSkill]:
    """Scan the skills directory and return all enabled advisor skills.

    This is the core extensibility mechanism. It reads every .md file,
    parses YAML frontmatter, and builds AdvisorSkill instances for files
    where type == "advisor" and enabled == true.

    Returns skills sorted by temperature_rank (ascending) for
    deterministic ordering regardless of filesystem order.
    """
    skills_dir = skills_dir or _SKILLS_DIR
    if not skills_dir.is_dir():
        logger.warning("Skills directory not found: %s", skills_dir)
        return []

    skills: list[AdvisorSkill] = []

    # sorted() ensures filesystem ordering doesn't affect results.
    # glob("*.md") returns all markdown files in the directory.
    for path in sorted(skills_dir.glob("*.md")):
        try:
            text = path.read_text()
        except OSError as exc:
            logger.warning("Failed to read skill file %s: %s", path, exc)
            continue

        frontmatter, body = _parse_frontmatter(text)

        # Skip files without frontmatter or wrong type
        if frontmatter.get("type") != "advisor":
            continue

        # Skip disabled skills
        if not frontmatter.get("enabled", True):
            logger.info("Skipping disabled skill: %s", path.name)
            continue

        # Validate required field: name
        name = frontmatter.get("name", "")
        if not name:
            logger.warning("Skill file %s missing 'name' in frontmatter", path)
            continue

        # Model resolution: env var > frontmatter > empty (global default).
        # CODE_COUNCIL_MODEL_<SKILL_NAME> takes highest priority, then
        # the model field in YAML frontmatter, then the global default.
        env_model = get_skill_model(name)
        frontmatter_model = frontmatter.get("model", "")
        resolved_model = env_model or frontmatter_model

        skill = AdvisorSkill(
            name=name,
            display_name=frontmatter.get("display_name", name.title()),
            role_description=frontmatter.get("role_description", ""),
            skill_text=body,
            temperature_rank=int(frontmatter.get("temperature_rank", 0)),
            seed_offset=int(frontmatter.get("seed_offset", 0)),
            enabled=True,
            model=resolved_model,
            source_path=str(path),
        )
        skills.append(skill)

    skills.sort(key=lambda s: s.temperature_rank)

    logger.info(
        "Discovered %d advisor skills: %s",
        len(skills),
        [s.name for s in skills],
    )
    return skills


def discover_synthesizer_skill(
    skills_dir: Path | None = None,
) -> str:
    """Load the synthesizer skill (type: synthesizer) from the skills directory.

    Returns the Markdown body of the first enabled synthesizer file,
    or an empty string if none found.
    """
    skills_dir = skills_dir or _SKILLS_DIR
    if not skills_dir.is_dir():
        return ""

    for path in sorted(skills_dir.glob("*.md")):
        try:
            text = path.read_text()
        except OSError:
            continue

        frontmatter, body = _parse_frontmatter(text)
        if frontmatter.get("type") == "synthesizer" and frontmatter.get("enabled", True):
            return body

    logger.warning("No synthesizer skill found in %s", skills_dir)
    return ""


def discover_analysis_skill(
    skills_dir: Path | None = None,
) -> str:
    """Load the conflict analysis skill (type: synthesizer_analysis).

    Returns the Markdown body of the first enabled synthesizer_analysis
    file, or an empty string if none found.  Used by the two-pass
    synthesis pipeline as the Pass 1 prompt.
    """
    skills_dir = skills_dir or _SKILLS_DIR
    if not skills_dir.is_dir():
        return ""

    for path in sorted(skills_dir.glob("*.md")):
        try:
            text = path.read_text()
        except OSError:
            continue

        frontmatter, body = _parse_frontmatter(text)
        if frontmatter.get("type") == "synthesizer_analysis" and frontmatter.get("enabled", True):
            return body

    logger.warning("No synthesizer_analysis skill found in %s", skills_dir)
    return ""


# ---------------------------------------------------------------------------
# Diversity controls
# ---------------------------------------------------------------------------


def _advisor_temperature(rank: int, total_advisors: int, spread: float) -> float:
    """Return a temperature for an advisor based on rank, total count, and spread.

    Temperatures are evenly spaced from (1.0 - spread) to 1.0.
    Adapts automatically to however many advisors are active.

    Example with spread=0.4 and 5 advisors:
        rank 0 -> 0.6  (most concrete)
        rank 1 -> 0.7
        rank 2 -> 0.8
        rank 3 -> 0.9
        rank 4 -> 1.0  (most divergent)

    Python lesson: why round()?
        Floating point arithmetic isn't exact. 1.0 - 0.4 + (0.4 * 3 / 4)
        might give 0.8999999999 instead of 0.9. round(x, 3) cleans this up.
    """
    if spread <= 0.0 or total_advisors <= 1:
        return 1.0
    return round(1.0 - spread + (spread * rank / (total_advisors - 1)), 3)


def _advisor_seed(seed_offset: int, plan_id: str) -> int:
    """Deterministic seed derived from plan_id and advisor seed_offset.

    Why hash the plan_id?
        Different plans should get different seeds (so advisors give
        varied responses across plans). But the SAME plan should get
        the SAME seeds (reproducibility). SHA-256 gives us a stable
        integer from any string.

    Why add seed_offset?
        So each advisor on the same plan gets a different seed.
        Architect gets base+4, Security gets base+1, etc.
    """
    base = int(hashlib.sha256(plan_id.encode()).hexdigest()[:8], 16)
    return base + seed_offset


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def _format_context(ctx: ProjectContext) -> str:
    """Format a ProjectContext into a text block for injection into prompts."""
    parts = [
        "## Project Context\n",
        f"**Path:** {ctx.project_path}",
        f"**Languages:** {', '.join(ctx.tech_stack.languages)}",
        f"**Frameworks:** {', '.join(ctx.tech_stack.frameworks)}",
        f"**Build:** {', '.join(ctx.tech_stack.build_tools)}",
        f"**Tests:** {ctx.test_patterns.test_framework} "
        f"({', '.join(ctx.test_patterns.test_directories)})",
        "",
        "### Directory Structure",
        f"```\n{ctx.directory_tree}\n```",
    ]

    if ctx.config_files:
        parts.append("\n### Config Files")
        for name, content in ctx.config_files.items():
            parts.append(f"\n**{name}:**\n```\n{content}\n```")

    if ctx.relevant_files:
        parts.append("\n### Relevant Source Files")
        for path, content in ctx.relevant_files.items():
            parts.append(f"\n**{path}:**\n```\n{content}\n```")

    if ctx.code_comments:
        parts.append("\n### Implementation Notes & Design Comments")
        parts.append("Key comments, docstrings, and design rationale extracted from the codebase:")
        for path, comments in ctx.code_comments.items():
            if comments:
                parts.append(f"\n**{path}:**")
                for comment in comments:
                    parts.append(f"- {comment}")

    return "\n".join(parts)


def _advisor_prompt(
    skill: AdvisorSkill,
    change_description: str,
    context: ProjectContext,
    negotiation_feedback: str = "",
) -> str:
    """Build the full prompt for a single advisor."""
    parts = []

    if skill.skill_text:
        parts.append(f"## Advisor Skill Reference\n\n{skill.skill_text}\n\n---\n")

    parts.append(_format_context(context))
    parts.append("\n---\n")
    parts.append(f"{skill.role_description}\n\n")
    parts.append(
        "A user wants to make the following change to this codebase:\n\n"
        "---\n"
        f"{change_description}\n"
        "---\n\n"
    )

    if negotiation_feedback:
        parts.append(
            "## AI Tool Feedback (from previous review)\n\n"
            "The AI coding tool reviewed the previous plan and raised "
            "these concerns. Factor them into your analysis:\n\n"
            f"{negotiation_feedback}\n\n---\n\n"
        )

    parts.append(
        "Analyze this change from your specific perspective. "
        "Be direct and specific to THIS codebase -- reference actual "
        "files, patterns, and conventions you see in the project context. "
        "Do not give generic advice.\n\n"
        "Keep your response between 150-300 words. No preamble. "
        "Go straight into your analysis."
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Run advisors (parallel)
# ---------------------------------------------------------------------------


async def run_advisors(
    change_description: str,
    context: ProjectContext,
    llm: LLMClient,
    plan_id: str,
    temperature_spread: float = 0.4,
    negotiation_feedback: str = "",
    skills_dir: Path | None = None,
) -> tuple[dict[str, str], dict[str, dict[str, Any]], dict[str, float], TokenUsage]:
    """Run all discovered advisors in parallel and return their responses.

    Returns ``(advisor_responses, advisor_params, timing, token_usage)``.

    Python lesson: asyncio.gather()
        gather() runs multiple coroutines concurrently. It waits for ALL
        of them to finish, then returns results in the same order.
        This is how we run 5-6 advisors in parallel -- each makes an
        independent LLM call, so there's no reason to wait sequentially.
        Total wall-clock time ≈ slowest advisor, not sum of all.
    """
    skills = discover_advisor_skills(skills_dir)
    if not skills:
        raise RuntimeError("No advisor skills found. Check the skills/ directory.")

    total = len(skills)

    # Compute per-advisor temperature and seed
    advisor_params: dict[str, dict[str, Any]] = {}
    for skill in skills:
        advisor_params[skill.display_name] = {
            "temperature": _advisor_temperature(
                skill.temperature_rank,
                total,
                temperature_spread,
            ),
            "seed": _advisor_seed(skill.seed_offset, plan_id),
        }

    async def _run_one(skill: AdvisorSkill) -> tuple[str, str, TokenUsage]:
        prompt = _advisor_prompt(
            skill,
            change_description,
            context,
            negotiation_feedback,
        )
        params = advisor_params[skill.display_name]
        result = await llm.complete_with_usage(
            prompt,
            temperature=params["temperature"],
            seed=params["seed"],
            model=skill.model or None,
        )
        return skill.display_name, result.text, result.usage

    t0 = time.monotonic()
    results = await asyncio.gather(*[_run_one(s) for s in skills])
    duration = time.monotonic() - t0

    advisor_responses: dict[str, str] = {}
    stage_usage = TokenUsage()
    for name, text, usage in results:
        advisor_responses[name] = text
        stage_usage += usage

    timing = {"start": t0, "duration": round(duration, 3)}

    return advisor_responses, advisor_params, timing, stage_usage


# ---------------------------------------------------------------------------
# Discover decision gate skill
# ---------------------------------------------------------------------------


def discover_decision_gate_skill(
    skills_dir: Path | None = None,
) -> str:
    """Load the decision gate skill (type: decision_gate) from skills/.

    Returns the Markdown body of the first enabled decision_gate file,
    or an empty string if none found.
    """
    skills_dir = skills_dir or _SKILLS_DIR
    if not skills_dir.is_dir():
        return ""

    for path in sorted(skills_dir.glob("*.md")):
        try:
            text = path.read_text()
        except OSError:
            continue

        frontmatter, body = _parse_frontmatter(text)
        if frontmatter.get("type") == "decision_gate" and frontmatter.get("enabled", True):
            return body

    logger.warning("No decision gate skill found in %s", skills_dir)
    return ""


# ---------------------------------------------------------------------------
# Council review: advisors review the synthesized plan
# ---------------------------------------------------------------------------


def _plan_review_prompt(
    skill: AdvisorSkill,
    plan_summary: str,
) -> str:
    """Build a prompt for an advisor to review a synthesized plan."""
    parts = []

    if skill.skill_text:
        parts.append(f"## Your Advisor Skill\n\n{skill.skill_text}\n\n---\n")

    parts.append(f"{skill.role_description}\n\n")
    parts.append(
        "A synthesized implementation plan has been produced. Review it "
        "from your specific perspective.\n\n"
        "---\n"
        f"{plan_summary}\n"
        "---\n\n"
        "If the plan is sound from your perspective, respond with "
        "exactly: PROCEED\n\n"
        "If you have concerns, list them as prioritised recommendations. "
        "For each recommendation:\n"
        "- **Priority**: HIGH / MEDIUM / LOW\n"
        "- **Recommendation**: What to change and why\n\n"
        "Be specific to THIS plan. Do not repeat what the plan already "
        "covers. Only raise issues the plan missed or got wrong.\n\n"
        "Keep your response under 200 words. No preamble."
    )
    return "\n".join(parts)


def _format_plan_for_review(plan_data: dict[str, Any]) -> str:
    """Format a ChangePlan dict into a text summary for advisor review."""
    lines = [
        f"# {plan_data.get('title', 'Untitled Plan')}",
        "",
        plan_data.get("summary", ""),
        "",
    ]

    steps = plan_data.get("implementation_steps", [])
    if steps:
        lines.append("## Implementation Steps")
        lines.append("")
        for step in steps:
            deps = step.get("depends_on", [])
            dep_str = f" (depends on: {deps})" if deps else ""
            lines.append(
                f"{step.get('order', '?')}. **{step.get('file_path', '?')}** "
                f"({step.get('action', '?')}){dep_str}"
            )
            lines.append(f"   {step.get('description', '')}")
            lines.append("")

    criteria = plan_data.get("acceptance_criteria", [])
    if criteria:
        lines.append("## Acceptance Criteria")
        lines.append("")
        for ac in criteria:
            lines.append(f"- {ac}")
        lines.append("")

    for key, label in [
        ("architecture_notes", "Architecture Notes"),
        ("security_notes", "Security Notes"),
        ("quality_notes", "Quality Notes"),
        ("risk_assessment", "Risk Assessment"),
        ("execution_strategy", "Execution Strategy"),
    ]:
        val = plan_data.get(key, "")
        if val:
            lines.append(f"## {label}")
            lines.append("")
            lines.append(val)
            lines.append("")

    lines.append(
        f"Risk: {plan_data.get('risk_level', '?')} | "
        f"Effort: {plan_data.get('estimated_effort', '?')}"
    )
    return "\n".join(lines)


async def review_plan(
    plan_data: dict[str, Any],
    llm: LLMClient,
    plan_id: str,
    temperature_spread: float = 0.4,
    skills_dir: Path | None = None,
) -> tuple[dict[str, str], dict[str, float], TokenUsage]:
    """Each advisor reviews the synthesized plan and returns feedback.

    Returns ``(advisor_reviews, timing, token_usage)``. Each review is
    either "PROCEED" or a list of prioritised recommendations.
    """
    skills = discover_advisor_skills(skills_dir)
    if not skills:
        raise RuntimeError("No advisor skills found. Check the skills/ directory.")

    plan_summary = _format_plan_for_review(plan_data)
    total = len(skills)

    async def _review_one(skill: AdvisorSkill) -> tuple[str, str, TokenUsage]:
        prompt = _plan_review_prompt(skill, plan_summary)
        temp = _advisor_temperature(
            skill.temperature_rank,
            total,
            temperature_spread,
        )
        seed = _advisor_seed(skill.seed_offset, plan_id)
        result = await llm.complete_with_usage(
            prompt,
            temperature=temp,
            seed=seed,
            model=skill.model or None,
        )
        return skill.display_name, result.text, result.usage

    t0 = time.monotonic()
    results = await asyncio.gather(*[_review_one(s) for s in skills])
    duration = time.monotonic() - t0

    advisor_reviews: dict[str, str] = {}
    stage_usage = TokenUsage()
    for name, text, usage in results:
        advisor_reviews[name] = text
        stage_usage += usage

    timing = {"start": t0, "duration": round(duration, 3)}

    return advisor_reviews, timing, stage_usage


# ---------------------------------------------------------------------------
# Decision gate: Business + Architect decide on recommendations
# ---------------------------------------------------------------------------


def _decision_gate_prompt(
    plan_data: dict[str, Any],
    advisor_reviews: dict[str, str],
) -> str:
    """Build the prompt for the Business+Architect decision gate."""
    skill_text = discover_decision_gate_skill()
    plan_summary = _format_plan_for_review(plan_data)

    reviews_section = "\n\n".join(f"**{name}:**\n{text}" for name, text in advisor_reviews.items())

    parts = []
    if skill_text:
        parts.append(f"{skill_text}\n\n---\n")

    parts.append(
        "## Plan Under Review\n\n"
        f"{plan_summary}\n\n---\n\n"
        "## Advisor Reviews\n\n"
        f"{reviews_section}\n\n---\n\n"
        "Make your decision. Return valid JSON only. No commentary "
        "outside the JSON block."
    )
    return "\n".join(parts)


async def decide_changes(
    plan_data: dict[str, Any],
    advisor_reviews: dict[str, str],
    llm: LLMClient,
) -> tuple[dict[str, Any], TokenUsage]:
    """Business+Architect decision gate on advisor recommendations.

    Returns ``(decision, token_usage)``. The decision dict contains
    verdict, rationale, and per-recommendation decisions.
    """
    import json as _json

    gate_model = get_skill_model("decision_gate") or None
    stage_usage = TokenUsage()

    prompt = _decision_gate_prompt(plan_data, advisor_reviews)
    result = await llm.complete_with_usage(prompt, temperature=0.7, model=gate_model)
    raw_response = result.text
    stage_usage += result.usage

    # Extract JSON from response
    json_text = raw_response.strip()
    if "```json" in json_text:
        start = json_text.index("```json") + 7
        end = json_text.index("```", start)
        json_text = json_text[start:end].strip()
    elif "```" in json_text:
        start = json_text.index("```") + 3
        end = json_text.index("```", start)
        json_text = json_text[start:end].strip()

    try:
        decision = _json.loads(json_text)
    except _json.JSONDecodeError:
        # Retry once
        repair_prompt = (
            "The previous response was not valid JSON. "
            "Fix it and return ONLY the corrected JSON:\n\n"
            f"{raw_response}"
        )
        retry_result = await llm.complete_with_usage(repair_prompt, model=gate_model)
        raw_response = retry_result.text
        stage_usage += retry_result.usage
        json_text = raw_response.strip()
        if "```json" in json_text:
            start = json_text.index("```json") + 7
            end = json_text.index("```", start)
            json_text = json_text[start:end].strip()
        elif "```" in json_text:
            start = json_text.index("```") + 3
            end = json_text.index("```", start)
            json_text = json_text[start:end].strip()
        decision = _json.loads(json_text)

    return decision, stage_usage
