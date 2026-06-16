"""Tests for code_council.synthesizer -- plan synthesis from advisor outputs.

Python lesson: why test JSON parsing separately?
    The synthesizer receives raw LLM text and must extract valid JSON.
    LLMs are unreliable -- they might wrap JSON in code fences, add
    commentary before/after, or produce invalid JSON. Testing _extract_json
    separately covers these edge cases without needing a full LLM call.
"""

import pytest

from code_council.synthesizer import (
    ChangePlan,
    _extract_json,
    analyze_conflicts,
    synthesize_plan,
)


class TestExtractJson:
    def test_from_code_fence(self) -> None:
        text = 'Some text\n```json\n{"key": "value"}\n```\nMore text'
        assert _extract_json(text) == '{"key": "value"}'

    def test_raw_json(self) -> None:
        text = '{"key": "value"}'
        assert _extract_json(text) == '{"key": "value"}'

    def test_generic_fence(self) -> None:
        text = '```\n{"key": "value"}\n```'
        assert _extract_json(text) == '{"key": "value"}'


@pytest.mark.asyncio
async def test_synthesize_produces_valid_plan(fake_llm, fake_context) -> None:
    """FakeLLM returns canned JSON plan. Synthesizer should parse it."""
    plan = await synthesize_plan(
        change_description="Add a feature",
        advisor_responses={
            "Architect Advisor": "Fits well.",
            "Security Advisor": "No issues.",
            "Quality Advisor": "Add tests.",
            "Risk Advisor": "Low risk.",
            "Executor Advisor": "Start with main.py.",
            "Business Advisor": "High value.",
        },
        context=fake_context,
        plan_id="synth-test",
        llm=fake_llm,
    )
    assert isinstance(plan, ChangePlan)
    assert plan.plan_id == "synth-test"
    assert len(plan.affected_files) > 0
    assert len(plan.implementation_steps) > 0
    assert plan.risk_level in ("LOW", "MEDIUM", "HIGH")
    assert plan.estimated_effort in ("S", "M", "L", "XL")


@pytest.mark.asyncio
async def test_synthesize_preserves_advisor_responses(fake_llm, fake_context) -> None:
    """Raw advisor responses should be stored for audit."""
    responses = {"Architect Advisor": "Test response"}
    plan = await synthesize_plan(
        change_description="Test",
        advisor_responses=responses,
        context=fake_context,
        plan_id="audit-test",
        llm=fake_llm,
    )
    assert plan.raw_advisor_responses == responses


# ---------------------------------------------------------------------------
# Two-pass synthesis tests
# ---------------------------------------------------------------------------

SAMPLE_ADVISOR_RESPONSES = {
    "Architect Advisor": "Fits well.",
    "Security Advisor": "No issues.",
    "Quality Advisor": "Add tests.",
    "Risk Advisor": "Low risk.",
    "Executor Advisor": "Start with main.py.",
    "Business Advisor": "High value.",
}


@pytest.mark.asyncio
async def test_analyze_conflicts_returns_markdown(fake_llm, fake_context) -> None:
    """Pass 1 should return a markdown conflict analysis, not JSON."""
    analysis = await analyze_conflicts(
        change_description="Add a feature",
        advisor_responses=SAMPLE_ADVISOR_RESPONSES,
        context=fake_context,
        llm=fake_llm,
    )
    assert isinstance(analysis, str)
    assert "Advisor Position Summary" in analysis
    assert len(analysis) > 0


@pytest.mark.asyncio
async def test_analyze_conflicts_prompt_contains_advisor_names(
    fake_llm, fake_context
) -> None:
    """The analysis prompt should include all advisor names."""
    await analyze_conflicts(
        change_description="Add a feature",
        advisor_responses=SAMPLE_ADVISOR_RESPONSES,
        context=fake_context,
        llm=fake_llm,
    )
    # FakeLLM records the prompt
    analysis_prompt = fake_llm.prompts[-1]
    for name in SAMPLE_ADVISOR_RESPONSES:
        assert name in analysis_prompt


@pytest.mark.asyncio
async def test_two_pass_synthesis_makes_two_llm_calls(
    fake_llm, fake_context
) -> None:
    """Full two-pass flow should make exactly 2 LLM calls."""
    initial_count = fake_llm.call_count

    analysis = await analyze_conflicts(
        change_description="Add a feature",
        advisor_responses=SAMPLE_ADVISOR_RESPONSES,
        context=fake_context,
        llm=fake_llm,
    )
    plan = await synthesize_plan(
        change_description="Add a feature",
        advisor_responses=SAMPLE_ADVISOR_RESPONSES,
        context=fake_context,
        plan_id="two-pass-test",
        llm=fake_llm,
        conflict_analysis=analysis,
    )
    assert fake_llm.call_count - initial_count == 2
    assert isinstance(plan, ChangePlan)


@pytest.mark.asyncio
async def test_synthesis_prompt_contains_conflict_analysis(
    fake_llm, fake_context
) -> None:
    """When conflict_analysis is provided, it should appear in the synthesis prompt."""
    analysis = await analyze_conflicts(
        change_description="Add a feature",
        advisor_responses=SAMPLE_ADVISOR_RESPONSES,
        context=fake_context,
        llm=fake_llm,
    )
    await synthesize_plan(
        change_description="Add a feature",
        advisor_responses=SAMPLE_ADVISOR_RESPONSES,
        context=fake_context,
        plan_id="analysis-in-prompt-test",
        llm=fake_llm,
        conflict_analysis=analysis,
    )
    # The synthesis prompt is the last one recorded
    synthesis_prompt = fake_llm.prompts[-1]
    assert "CONFLICT ANALYSIS" in synthesis_prompt
    assert "Advisor Position Summary" in synthesis_prompt


@pytest.mark.asyncio
async def test_synthesize_without_analysis_still_works(
    fake_llm, fake_context
) -> None:
    """Backward compatibility: synthesize_plan without conflict_analysis."""
    plan = await synthesize_plan(
        change_description="Add a feature",
        advisor_responses=SAMPLE_ADVISOR_RESPONSES,
        context=fake_context,
        plan_id="no-analysis-test",
        llm=fake_llm,
    )
    assert isinstance(plan, ChangePlan)
    # Should not contain the analysis section
    synthesis_prompt = fake_llm.prompts[-1]
    assert "CONFLICT ANALYSIS" not in synthesis_prompt
