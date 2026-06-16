"""Tests for LLM data structures and FakeLLM.

We can't test OpenAICompatibleLLM without real API credentials, but we CAN test:
1. TokenUsage and LLMResult dataclasses behave correctly
2. FakeLLM returns the right responses for different prompt types
3. FakeLLM records call metadata properly

Python lesson: testing your test infrastructure
    FakeLLM is used by every other test file. If it has a bug, ALL
    tests give misleading results. Testing FakeLLM itself is like
    calibrating your measuring instrument before measuring.
"""

import pytest

from code_council.llm import LLMResult, TokenUsage
from tests.conftest import FakeLLM


class TestTokenUsage:
    def test_defaults_to_zero(self) -> None:
        usage = TokenUsage()
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0

    def test_custom_values(self) -> None:
        usage = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        assert usage.total_tokens == 150


class TestLLMResult:
    def test_text_and_usage(self) -> None:
        result = LLMResult(text="hello", usage=TokenUsage(total_tokens=10))
        assert result.text == "hello"
        assert result.usage.total_tokens == 10

    def test_default_usage(self) -> None:
        """Each LLMResult should get its own TokenUsage instance.
        This tests the default_factory pattern -- without it, all
        instances would share one TokenUsage object (mutable default bug)."""
        r1 = LLMResult(text="a")
        r2 = LLMResult(text="b")
        r1.usage.total_tokens = 999
        assert r2.usage.total_tokens == 0  # should NOT be 999


class TestFakeLLMResponses:
    """Verify FakeLLM returns the right canned response per prompt type."""

    @pytest.mark.asyncio
    async def test_synthesizer_returns_json(self) -> None:
        llm = FakeLLM()
        result = await llm.complete("You are the Plan Synthesizer for a Code Council.")
        assert '"title"' in result
        assert '"implementation_steps"' in result

    @pytest.mark.asyncio
    async def test_framer_returns_json(self) -> None:
        llm = FakeLLM()
        result = await llm.complete("You are the Requirements Framer")
        assert '"type"' in result
        assert '"acceptance_criteria"' in result

    @pytest.mark.asyncio
    async def test_advisor_returns_role_echo(self) -> None:
        llm = FakeLLM()
        result = await llm.complete("You are the Architect Advisor on a Code Council.")
        assert "Architect Advisor" in result

    @pytest.mark.asyncio
    async def test_generic_prompt(self) -> None:
        llm = FakeLLM()
        result = await llm.complete("What is 2+2?")
        assert result == "Generic LLM response."


class TestFakeLLMTracking:
    """Verify FakeLLM records call metadata."""

    @pytest.mark.asyncio
    async def test_counts_calls(self) -> None:
        llm = FakeLLM()
        await llm.complete("one")
        await llm.complete("two")
        assert llm.call_count == 2

    @pytest.mark.asyncio
    async def test_records_prompts(self) -> None:
        llm = FakeLLM()
        await llm.complete("test prompt here")
        assert "test prompt here" in llm.prompts

    @pytest.mark.asyncio
    async def test_records_params(self) -> None:
        llm = FakeLLM()
        await llm.complete("x", temperature=0.7, seed=42)
        assert llm.call_params[0]["temperature"] == 0.7
        assert llm.call_params[0]["seed"] == 42

    @pytest.mark.asyncio
    async def test_complete_with_usage(self) -> None:
        llm = FakeLLM()
        result = await llm.complete_with_usage("hello")
        assert result.text == "Generic LLM response."
        assert result.usage.total_tokens == 150
