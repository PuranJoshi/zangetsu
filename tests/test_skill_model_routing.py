"""Tests for per-skill model routing.

Each skill .md file can optionally specify a `model` field in its YAML
frontmatter. This lets you use different LLM models for different advisors:
    - architect.md: model: gpt-4o
    - business.md: model: claude-sonnet
    - executor.md: no model (uses the default from config)

Model resolution order (highest priority first):
    1. Environment variable CODE_COUNCIL_MODEL_<SKILL_NAME>
    2. YAML frontmatter ``model:`` field in the skill .md file
    3. Global CODE_COUNCIL_MODEL default (used when model is empty)

Python lesson: optional fields with defaults
    AdvisorSkill.model defaults to "" (empty string). The runner checks:
    if the skill has a model, use it; otherwise fall back to the global
    config.code_council_model. This is the "override with fallback" pattern.
"""

import os
from pathlib import Path

import pytest

from code_council.advisors import discover_advisor_skills, run_advisors
from code_council.config import get_skill_model
from code_council.framer import frame_request
from code_council.synthesizer import analyze_conflicts, synthesize_plan


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
    @pytest.fixture(autouse=True)
    def _clear_model_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Remove any CODE_COUNCIL_MODEL_* env vars so tests are isolated."""
        for key in list(os.environ):
            if key.startswith("CODE_COUNCIL_MODEL_"):
                monkeypatch.delenv(key)

    def test_skill_with_model_override(self, tmp_path: Path) -> None:
        """A skill with model: in frontmatter should have it set."""
        _write_skill_with_model(tmp_path, "architect.md", name="architect", model="gpt-4o")
        skills = discover_advisor_skills(tmp_path)
        assert len(skills) == 1
        assert skills[0].model == "gpt-4o"

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
            model="gpt-4o",
            temperature_rank=0,
        )
        _write_skill_with_model(
            tmp_path,
            "business.md",
            name="business",
            model="claude-sonnet",
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
        assert models["architect"] == "gpt-4o"
        assert models["business"] == "claude-sonnet"
        assert models["executor"] == ""


class TestEnvVarModelOverride:
    """Environment variable CODE_COUNCIL_MODEL_<SKILL> overrides frontmatter."""

    @pytest.fixture(autouse=True)
    def _clear_model_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Remove any CODE_COUNCIL_MODEL_* env vars so tests are isolated."""
        for key in list(os.environ):
            if key.startswith("CODE_COUNCIL_MODEL_"):
                monkeypatch.delenv(key)

    def test_env_var_overrides_frontmatter(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Env var should take priority over frontmatter model."""
        _write_skill_with_model(
            tmp_path, "architect.md", name="architect", model="frontmatter-model"
        )
        monkeypatch.setenv("CODE_COUNCIL_MODEL_ARCHITECT", "env-model")
        skills = discover_advisor_skills(tmp_path)
        assert skills[0].model == "env-model"

    def test_env_var_sets_model_when_frontmatter_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Env var should set model even when frontmatter has no model field."""
        _write_skill_with_model(tmp_path, "executor.md", name="executor")
        monkeypatch.setenv("CODE_COUNCIL_MODEL_EXECUTOR", "env-only-model")
        skills = discover_advisor_skills(tmp_path)
        assert skills[0].model == "env-only-model"

    def test_frontmatter_used_when_no_env_var(self, tmp_path: Path) -> None:
        """Without env var, frontmatter model should be used."""
        _write_skill_with_model(
            tmp_path, "architect.md", name="architect", model="frontmatter-model"
        )
        skills = discover_advisor_skills(tmp_path)
        assert skills[0].model == "frontmatter-model"

    def test_env_var_case_insensitive_skill_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Skill name is uppercased for env var lookup."""
        _write_skill_with_model(tmp_path, "risk.md", name="risk")
        monkeypatch.setenv("CODE_COUNCIL_MODEL_RISK", "risk-model")
        skills = discover_advisor_skills(tmp_path)
        assert skills[0].model == "risk-model"


class TestGetSkillModel:
    """Unit tests for the get_skill_model config helper."""

    def test_returns_value_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CODE_COUNCIL_MODEL_ARCHITECT", "gpt-4o")
        assert get_skill_model("architect") == "gpt-4o"

    def test_returns_empty_when_not_set(self) -> None:
        os.environ.pop("CODE_COUNCIL_MODEL_NONEXISTENT", None)
        assert get_skill_model("nonexistent") == ""

    def test_uppercases_skill_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CODE_COUNCIL_MODEL_BUSINESS", "claude-sonnet")
        assert get_skill_model("business") == "claude-sonnet"

    def test_non_advisor_skills(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_skill_model works for all pipeline skills, not just advisors."""
        monkeypatch.setenv("CODE_COUNCIL_MODEL_FRAMER", "gpt-4o-mini")
        monkeypatch.setenv("CODE_COUNCIL_MODEL_SYNTHESIZER", "gpt-4o")
        monkeypatch.setenv("CODE_COUNCIL_MODEL_DECISION_GATE", "gpt-4o")
        assert get_skill_model("framer") == "gpt-4o-mini"
        assert get_skill_model("synthesizer") == "gpt-4o"
        assert get_skill_model("decision_gate") == "gpt-4o"


class TestModelPassedToLLM:
    """Verify model override is actually forwarded to LLM.complete() calls."""

    @pytest.fixture(autouse=True)
    def _clear_model_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Remove any CODE_COUNCIL_MODEL_* env vars so tests are isolated."""
        for key in list(os.environ):
            if key.startswith("CODE_COUNCIL_MODEL_"):
                monkeypatch.delenv(key)

    @pytest.mark.asyncio
    async def test_advisor_with_model_passes_to_llm(
        self, tmp_path: Path, fake_llm, fake_context
    ) -> None:
        """An advisor with a model override should pass it to llm.complete()."""
        _write_skill_with_model(
            tmp_path,
            "architect.md",
            name="architect",
            model="gpt-4o",
            temperature_rank=0,
        )
        _write_skill_with_model(
            tmp_path,
            "executor.md",
            name="executor",
            temperature_rank=1,
        )

        await run_advisors(
            change_description="Add a feature",
            context=fake_context,
            llm=fake_llm,
            plan_id="test-plan-123",
            skills_dir=tmp_path,
        )

        # FakeLLM records call_params with model field.
        # Find the call for architect (has model) and executor (no model).
        models_used = [p["model"] for p in fake_llm.call_params]
        assert "gpt-4o" in models_used, "Architect advisor should pass model='gpt-4o' to LLM"
        assert None in models_used, (
            "Executor advisor (no model override) should pass model=None to LLM"
        )


class TestConfigSkillMismatch:
    """Edge cases: config and skill files out of sync.

    These test what happens when a user changes one side
    (env var or skill file) but forgets the other.
    """

    @pytest.fixture(autouse=True)
    def _clear_model_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Remove any CODE_COUNCIL_MODEL_* env vars so tests are isolated."""
        for key in list(os.environ):
            if key.startswith("CODE_COUNCIL_MODEL_"):
                monkeypatch.delenv(key)

    def test_env_var_set_for_nonexistent_skill(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Env var for a skill that doesn't exist is silently ignored.

        User sets CODE_COUNCIL_MODEL_ARCHITECT but there's no architect.md.
        Discovery should return zero skills (no crash).
        """
        monkeypatch.setenv("CODE_COUNCIL_MODEL_ARCHITECT", "gpt-4o")
        # Only write an executor skill, no architect skill file
        _write_skill_with_model(tmp_path, "executor.md", name="executor")
        skills = discover_advisor_skills(tmp_path)
        assert len(skills) == 1
        assert skills[0].name == "executor"
        assert skills[0].model == ""

    def test_env_var_typo_does_not_affect_skill(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A typo in the env var name (e.g. ARCHTIECT) has no effect.

        The skill uses the global default (empty model) because the
        correct env var name is never matched.
        """
        monkeypatch.setenv("CODE_COUNCIL_MODEL_ARCHTIECT", "gpt-4o")  # typo
        _write_skill_with_model(tmp_path, "architect.md", name="architect")
        skills = discover_advisor_skills(tmp_path)
        assert skills[0].model == ""

    def test_frontmatter_model_without_env_var_still_works(
        self,
        tmp_path: Path,
    ) -> None:
        """User sets model in frontmatter but forgets the env var.

        The frontmatter value should be used -- env var is not required.
        """
        _write_skill_with_model(
            tmp_path,
            "architect.md",
            name="architect",
            model="gpt-4o",
        )
        skills = discover_advisor_skills(tmp_path)
        assert skills[0].model == "gpt-4o"

    def test_env_var_for_disabled_skill_is_ignored(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """User sets env var but the skill has enabled: false.

        The skill should not be discovered at all, so the env var
        model override has no effect.
        """
        monkeypatch.setenv("CODE_COUNCIL_MODEL_ARCHITECT", "gpt-4o")
        # Write a disabled skill
        lines = [
            "---",
            "name: architect",
            "type: advisor",
            "display_name: Architect Advisor",
            "role_description: You are the architect advisor.",
            "temperature_rank: 0",
            "seed_offset: 0",
            "enabled: false",
            "---",
            "",
            "# Architect Advisor",
            "Skill body.",
        ]
        (tmp_path / "architect.md").write_text("\n".join(lines))
        skills = discover_advisor_skills(tmp_path)
        assert len(skills) == 0

    @pytest.mark.asyncio
    async def test_env_var_model_reaches_framer_llm(
        self,
        fake_llm,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """User sets CODE_COUNCIL_MODEL_FRAMER -- it should reach llm.complete().

        Verifies the non-advisor pipeline stage picks up the env var.
        """
        monkeypatch.setenv("CODE_COUNCIL_MODEL_FRAMER", "gpt-4o")
        await frame_request(
            change_description="Add a login page",
            context_summary="Python FastAPI project",
            llm=fake_llm,
        )
        models_used = [p["model"] for p in fake_llm.call_params]
        assert "gpt-4o" in models_used

    @pytest.mark.asyncio
    async def test_env_var_model_reaches_synthesizer_llm(
        self,
        fake_llm,
        fake_context,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """User sets CODE_COUNCIL_MODEL_SYNTHESIZER -- it should reach llm.complete()."""
        monkeypatch.setenv("CODE_COUNCIL_MODEL_SYNTHESIZER", "gpt-4o")
        advisor_responses = {"Test Advisor": "Looks good."}
        await synthesize_plan(
            change_description="Add a feature",
            advisor_responses=advisor_responses,
            context=fake_context,
            plan_id="test-plan-456",
            llm=fake_llm,
        )
        models_used = [p["model"] for p in fake_llm.call_params]
        assert "gpt-4o" in models_used

    @pytest.mark.asyncio
    async def test_env_var_model_reaches_analysis_llm(
        self,
        fake_llm,
        fake_context,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """User sets CODE_COUNCIL_MODEL_SYNTHESIZER_ANALYSIS -- it should reach llm.complete()."""
        monkeypatch.setenv("CODE_COUNCIL_MODEL_SYNTHESIZER_ANALYSIS", "gpt-4o")
        advisor_responses = {"Test Advisor": "Looks good."}
        await analyze_conflicts(
            change_description="Add a feature",
            advisor_responses=advisor_responses,
            context=fake_context,
            llm=fake_llm,
        )
        models_used = [p["model"] for p in fake_llm.call_params]
        assert "gpt-4o" in models_used

    @pytest.mark.asyncio
    async def test_no_env_var_means_global_default(
        self,
        fake_llm,
        fake_context,
    ) -> None:
        """Without any env var or frontmatter, model=None is passed to LLM.

        The LLM client then uses its global CODE_COUNCIL_MODEL default.
        """
        advisor_responses = {"Test Advisor": "Looks good."}
        await synthesize_plan(
            change_description="Add a feature",
            advisor_responses=advisor_responses,
            context=fake_context,
            plan_id="test-plan-789",
            llm=fake_llm,
        )
        models_used = [p["model"] for p in fake_llm.call_params]
        assert all(m is None for m in models_used), (
            "Without env var, all calls should pass model=None (global default)"
        )
