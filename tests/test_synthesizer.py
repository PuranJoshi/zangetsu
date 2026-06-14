"""Tests for code_council.synthesizer -- plan synthesis from advisor outputs.

Python lesson: why test JSON parsing separately?
    The synthesizer receives raw LLM text and must extract valid JSON.
    LLMs are unreliable -- they might wrap JSON in code fences, add
    commentary before/after, or produce invalid JSON. Testing _extract_json
    separately covers these edge cases without needing a full LLM call.
"""

import pytest

from code_council.synthesizer import (
    synthesize_plan,
    ChangePlan,
    _extract_json,
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
