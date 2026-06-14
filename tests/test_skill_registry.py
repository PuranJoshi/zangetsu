"""Tests for skill registry -- YAML frontmatter discovery from .md files.

This is the extensibility engine. Each .md file in skills/ with YAML
frontmatter is auto-discovered as an advisor or synthesizer skill.

Python lesson: YAML frontmatter
    Markdown files can start with metadata between --- delimiters:
        ---
        name: architect
        type: advisor
        ---
        # Architect Advisor
        ...
    The YAML block is parsed into a dict. The body below it is the
    skill prompt text. This pattern is common in static site generators
    (Jekyll, Hugo, Astro) and we're reusing it for skill definitions.

Python lesson: fixtures vs helper functions
    In these tests, we use a helper function _write_skill() instead of
    a pytest fixture. Fixtures are good for setup/teardown that many
    tests share. Helpers are better when each test needs slightly
    different input -- we'd need a parameterized fixture otherwise,
    which is more complex than a simple function call.
"""

from pathlib import Path

import pytest

from code_council.advisors import (
    AdvisorSkill,
    _parse_frontmatter,
    discover_advisor_skills,
    discover_synthesizer_skill,
    _advisor_temperature,
    _advisor_seed,
)


def _write_skill(
    skills_dir: Path,
    filename: str,
    *,
    name: str = "test",
    skill_type: str = "advisor",
    display_name: str = "Test Advisor",
    role_description: str = "You are a test advisor.",
    temperature_rank: int = 0,
    seed_offset: int = 0,
    enabled: bool = True,
    body: str = "# Test\n\nSkill body content.",
) -> Path:
    """Write a skill .md file with frontmatter to a temp directory."""
    frontmatter = (
        f"---\n"
        f"name: {name}\n"
        f"type: {skill_type}\n"
        f"display_name: {display_name}\n"
        f"role_description: {role_description}\n"
        f"temperature_rank: {temperature_rank}\n"
        f"seed_offset: {seed_offset}\n"
        f"enabled: {str(enabled).lower()}\n"
        f"---\n\n"
        f"{body}"
    )
    path = skills_dir / filename
    path.write_text(frontmatter)
    return path


class TestParseFrontmatter:
    """Test the low-level YAML frontmatter parser."""

    def test_parses_valid_frontmatter(self) -> None:
        text = "---\nname: foo\ntype: advisor\n---\n\n# Body"
        fm, body = _parse_frontmatter(text)
        assert fm["name"] == "foo"
        assert fm["type"] == "advisor"
        assert "# Body" in body

    def test_no_frontmatter_returns_empty_dict(self) -> None:
        text = "# Just a markdown file\n\nNo frontmatter here."
        fm, body = _parse_frontmatter(text)
        assert fm == {}
        assert "Just a markdown" in body

    def test_invalid_yaml_returns_empty_dict(self) -> None:
        text = "---\n: invalid: yaml: {{{\n---\n\nBody"
        fm, body = _parse_frontmatter(text)
        assert fm == {}


class TestDiscoverAdvisorSkills:
    """Test that .md files with type: advisor are discovered."""

    def test_discovers_single_skill(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "architect.md", name="architect")
        skills = discover_advisor_skills(tmp_path)
        assert len(skills) == 1
        assert skills[0].name == "architect"

    def test_discovers_multiple_skills(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "architect.md", name="architect", temperature_rank=1)
        _write_skill(tmp_path, "security.md", name="security", temperature_rank=0)
        skills = discover_advisor_skills(tmp_path)
        assert len(skills) == 2

    def test_sorted_by_temperature_rank(self, tmp_path: Path) -> None:
        """Skills should be returned sorted by temperature_rank (ascending).
        This ensures deterministic ordering regardless of filesystem order."""
        _write_skill(tmp_path, "risk.md", name="risk", temperature_rank=5)
        _write_skill(tmp_path, "executor.md", name="executor", temperature_rank=0)
        _write_skill(tmp_path, "quality.md", name="quality", temperature_rank=2)
        skills = discover_advisor_skills(tmp_path)
        ranks = [s.temperature_rank for s in skills]
        assert ranks == [0, 2, 5]

    def test_skips_disabled_skills(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "active.md", name="active", enabled=True)
        _write_skill(tmp_path, "disabled.md", name="disabled", enabled=False)
        skills = discover_advisor_skills(tmp_path)
        assert len(skills) == 1
        assert skills[0].name == "active"

    def test_skips_non_advisor_type(self, tmp_path: Path) -> None:
        """Files with type: synthesizer should NOT appear in advisor list."""
        _write_skill(tmp_path, "advisor.md", name="arch", skill_type="advisor")
        _write_skill(tmp_path, "synth.md", name="synth", skill_type="synthesizer")
        skills = discover_advisor_skills(tmp_path)
        assert len(skills) == 1
        assert skills[0].name == "arch"

    def test_skips_files_without_frontmatter(self, tmp_path: Path) -> None:
        (tmp_path / "plain.md").write_text("# Just markdown\nNo frontmatter.")
        _write_skill(tmp_path, "real.md", name="real")
        skills = discover_advisor_skills(tmp_path)
        assert len(skills) == 1

    def test_empty_directory_returns_empty(self, tmp_path: Path) -> None:
        skills = discover_advisor_skills(tmp_path)
        assert skills == []

    def test_missing_directory_returns_empty(self, tmp_path: Path) -> None:
        skills = discover_advisor_skills(tmp_path / "nonexistent")
        assert skills == []

    def test_skill_text_is_body_below_frontmatter(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "test.md", name="test", body="# My Skill\n\nDetailed instructions.")
        skills = discover_advisor_skills(tmp_path)
        assert "# My Skill" in skills[0].skill_text
        assert "Detailed instructions" in skills[0].skill_text

    def test_skips_files_missing_name(self, tmp_path: Path) -> None:
        """Frontmatter without a 'name' field should be skipped."""
        bad = "---\ntype: advisor\n---\n\nNo name field."
        (tmp_path / "bad.md").write_text(bad)
        skills = discover_advisor_skills(tmp_path)
        assert skills == []


class TestDiscoverSynthesizerSkill:
    """Test that the synthesizer skill (type: synthesizer) is found."""

    def test_finds_synthesizer(self, tmp_path: Path) -> None:
        _write_skill(
            tmp_path, "synthesizer.md",
            name="synthesizer", skill_type="synthesizer",
            body="# Synthesizer\n\nMerge advisor outputs.",
        )
        text = discover_synthesizer_skill(tmp_path)
        assert "# Synthesizer" in text

    def test_ignores_advisors(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "architect.md", name="arch", skill_type="advisor")
        text = discover_synthesizer_skill(tmp_path)
        assert text == ""

    def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        assert discover_synthesizer_skill(tmp_path) == ""


class TestTemperatureCalculation:
    """Temperature spreads advisors from (1.0 - spread) to 1.0."""

    def test_single_advisor_gets_default(self) -> None:
        """With only 1 advisor, temperature should be 1.0."""
        assert _advisor_temperature(rank=0, total_advisors=1, spread=0.4) == 1.0

    def test_zero_spread_all_get_default(self) -> None:
        assert _advisor_temperature(rank=0, total_advisors=5, spread=0.0) == 1.0
        assert _advisor_temperature(rank=4, total_advisors=5, spread=0.0) == 1.0

    def test_five_advisors_spread_correctly(self) -> None:
        """With spread=0.4 and 5 advisors: 0.6, 0.7, 0.8, 0.9, 1.0"""
        temps = [_advisor_temperature(r, 5, 0.4) for r in range(5)]
        assert temps[0] == 0.6
        assert temps[4] == 1.0
        # All unique
        assert len(set(temps)) == 5

    def test_six_advisors_adapts(self) -> None:
        """Temperature spacing adapts to N advisors."""
        temps = [_advisor_temperature(r, 6, 0.4) for r in range(6)]
        assert temps[0] == 0.6
        assert temps[5] == 1.0
        assert len(set(temps)) == 6


class TestSeedGeneration:
    def test_deterministic(self) -> None:
        """Same inputs should produce same seed."""
        a = _advisor_seed(seed_offset=3, plan_id="abc")
        b = _advisor_seed(seed_offset=3, plan_id="abc")
        assert a == b

    def test_different_offsets_different_seeds(self) -> None:
        seeds = [_advisor_seed(seed_offset=i, plan_id="test") for i in range(5)]
        assert len(set(seeds)) == 5

    def test_different_plan_ids_different_seeds(self) -> None:
        a = _advisor_seed(seed_offset=0, plan_id="plan-a")
        b = _advisor_seed(seed_offset=0, plan_id="plan-b")
        assert a != b
