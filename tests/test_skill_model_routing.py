"""Tests for per-skill model routing.

Each skill .md file can optionally specify a `model` field in its YAML
frontmatter. This lets you use different LLM models for different advisors:
    - architect.md: model: claude-opus (strong reasoning)
    - business.md: model: gpt-4o (good product thinking)
    - executor.md: no model (uses the default from config)

Python lesson: optional fields with defaults
    AdvisorSkill.model defaults to "" (empty string). The runner checks:
    if the skill has a model, use it; otherwise fall back to the global
    config.code_council_model. This is the "override with fallback" pattern.
"""

from pathlib import Path

from code_council.advisors import discover_advisor_skills


def _write_skill_with_model(
    skills_dir: Path,
    filename: str,
    *,
    name: str,
    model: str = "",
    temperature_rank: int = 0,
) -> Path:
    """Write a skill file, optionally with a model override."""
    lines = [
        "---",
        f"name: {name}",
        "type: advisor",
        f"display_name: {name.title()} Advisor",
        f"role_description: You are the {name} advisor.",
        f"temperature_rank: {temperature_rank}",
        f"seed_offset: {temperature_rank}",
        "enabled: true",
    ]
    if model:
        lines.append(f"model: {model}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {name.title()} Advisor")
    lines.append("Skill body.")

    path = skills_dir / filename
    path.write_text("\n".join(lines))
    return path


class TestModelFieldDiscovery:
    def test_skill_with_model_override(self, tmp_path: Path) -> None:
        """A skill with model: in frontmatter should have it set."""
        _write_skill_with_model(tmp_path, "architect.md", name="architect", model="claude-opus")
        skills = discover_advisor_skills(tmp_path)
        assert len(skills) == 1
        assert skills[0].model == "claude-opus"

    def test_skill_without_model_gets_empty(self, tmp_path: Path) -> None:
        """A skill without model: should default to empty string."""
        _write_skill_with_model(tmp_path, "executor.md", name="executor")
        skills = discover_advisor_skills(tmp_path)
        assert len(skills) == 1
        assert skills[0].model == ""

    def test_mixed_models(self, tmp_path: Path) -> None:
        """Different skills can specify different models."""
        _write_skill_with_model(
            tmp_path,
            "architect.md",
            name="architect",
            model="claude-opus",
            temperature_rank=0,
        )
        _write_skill_with_model(
            tmp_path,
            "business.md",
            name="business",
            model="gpt-4o",
            temperature_rank=1,
        )
        _write_skill_with_model(
            tmp_path,
            "executor.md",
            name="executor",
            temperature_rank=2,  # no model override
        )
        skills = discover_advisor_skills(tmp_path)
        assert len(skills) == 3
        models = {s.name: s.model for s in skills}
        assert models["architect"] == "claude-opus"
        assert models["business"] == "gpt-4o"
        assert models["executor"] == ""
