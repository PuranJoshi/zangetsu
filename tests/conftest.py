"""Shared test fixtures for code-council tests.

Python lesson: conftest.py
    This is a magic filename for pytest. Anything defined here is
    automatically available to ALL test files in this directory --
    no import needed. pytest finds it by convention.

    Fixtures defined here (like fake_llm, fake_context) can be used
    as function parameters in any test:

        def test_something(fake_llm):
            result = await fake_llm.complete("hello")

    pytest sees the parameter name, looks it up in conftest.py,
    calls the fixture function, and injects the result.

Python lesson: @pytest.fixture
    A fixture is a function that provides test data or setup.
    The decorator tells pytest "this isn't a test, it's a helper."
    Fixtures can have scopes:
        - "function" (default): fresh instance per test
        - "module": one instance per test file
        - "session": one instance for the entire test run
    We use "function" scope so each test gets its own clean FakeLLM.
"""

from __future__ import annotations

from typing import Any

import pytest

from code_council.context import ProjectContext, TechStack, TestPatterns
from code_council.llm import LLMResult, TokenUsage

# ---------------------------------------------------------------------------
# FakeLLM -- deterministic LLM stub for testing
# ---------------------------------------------------------------------------


class FakeLLM:
    """Deterministic LLM stub that returns canned responses.

    Instead of calling a real LLM API (which costs money and is
    non-deterministic), tests use this. It inspects the prompt to figure
    out what kind of response to return.

    It also records every call so tests can assert:
    - How many LLM calls were made
    - What prompts were sent
    - What temperature/seed was used

    Python lesson: why not unittest.mock.MagicMock?
        MagicMock auto-generates return values. That's convenient but
        dangerous -- your tests pass even if the return value is wrong
        type. FakeLLM returns realistic responses that match what the
        real LLM would return, so tests catch type/format bugs.
    """

    def __init__(self) -> None:
        self.call_count = 0
        self.prompts: list[str] = []
        self.call_params: list[dict[str, Any]] = []

    async def complete(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        seed: int | None = None,
        model: str | None = None,
    ) -> str:
        """Return a canned response based on prompt content.

        The response varies depending on what's in the prompt:
        - Synthesizer prompts -> valid JSON plan
        - Advisor prompts -> echo back the role name
        - Framer prompts -> valid JSON framed requirement
        - Everything else -> generic response
        """
        self.call_count += 1
        self.prompts.append(prompt)
        self.call_params.append(
            {
                "prompt_preview": prompt[:80],
                "temperature": temperature,
                "seed": seed,
                "model": model,
            }
        )

        # Conflict analysis prompt (Pass 1) -- return canned markdown analysis
        if "Conflict Analyst" in prompt or "conflict resolution document" in prompt:
            return (
                "## Advisor Position Summary\n\n"
                "- **Executor:** Start with main.py, add tests. Effort: S.\n"
                "- **Security:** No critical issues.\n"
                "- **Quality:** Add unit tests, use intent-revealing names.\n"
                "- **Business:** High value, well-scoped.\n"
                "- **Architect:** Fits existing patterns, no coupling concerns.\n"
                "- **Risk:** Low risk, self-contained change.\n\n"
                "## Points of Agreement\n\n"
                "All advisors agree the change is low-risk and well-scoped.\n\n"
                "## Conflicts\n\n"
                "No significant conflicts identified.\n\n"
                "## Critical Blockers\n\n"
                "None.\n\n"
                "## Emergent Insights\n\n"
                "None -- advisors are aligned on this straightforward change."
            )

        # Synthesizer prompt -- return valid JSON plan
        if "Plan Synthesizer" in prompt or "implementation_steps" in prompt:
            return """```json
{
    "title": "Test Change",
    "summary": "A test change for unit testing.",
    "affected_files": ["src/main.py", "tests/test_main.py"],
    "implementation_steps": [
        {
            "order": 1,
            "file_path": "src/main.py",
            "action": "modify",
            "description": "Add the new function.",
            "depends_on": []
        },
        {
            "order": 2,
            "file_path": "tests/test_main.py",
            "action": "modify",
            "description": "Add tests for the new function.",
            "depends_on": [1]
        }
    ],
    "architecture_notes": "Fits existing patterns.",
    "security_notes": "No security concerns.",
    "quality_notes": "Add unit tests.",
    "risk_assessment": "Low risk, self-contained change.",
    "execution_strategy": "Single PR, straightforward.",
    "acceptance_criteria": [
        "All existing tests pass",
        "New unit tests added"
    ],
    "estimated_effort": "S",
    "risk_level": "LOW"
}
```"""

        # Framer prompt -- return valid JSON framed requirement
        if "Requirements Framer" in prompt or "clarifications_needed" in prompt:
            return """```json
{
    "type": "story",
    "title": "Test Feature",
    "description": "A test feature for unit testing.",
    "acceptance_criteria": [
        "Given a user, when they do X, then Y happens"
    ],
    "out_of_scope": [],
    "assumptions": [],
    "clarifications_needed": [],
    "stories": []
}
```"""

        # Advisor prompts -- echo back the role for identification
        advisor_keywords = [
            "Architect Advisor",
            "Security Advisor",
            "Quality Advisor",
            "Risk Advisor",
            "Executor Advisor",
            "Business Advisor",
        ]
        for keyword in advisor_keywords:
            if keyword in prompt:
                return f"[{keyword}] Analysis of the proposed change."

        return "Generic LLM response."

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        seed: int | None = None,
        model: str | None = None,
    ) -> str:
        self.call_count += 1
        return "Chat response."

    # -- Extended API (token usage tracking) --------------------------------

    async def complete_with_usage(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        seed: int | None = None,
        model: str | None = None,
    ) -> LLMResult:
        """Like complete() but returns token usage metadata too."""
        text = await self.complete(
            prompt,
            temperature=temperature,
            seed=seed,
            model=model,
        )
        return LLMResult(
            text=text,
            usage=TokenUsage(
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
            ),
        )

    async def chat_with_usage(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        seed: int | None = None,
        model: str | None = None,
    ) -> LLMResult:
        text = await self.chat(
            messages,
            temperature=temperature,
            seed=seed,
            model=model,
        )
        return LLMResult(
            text=text,
            usage=TokenUsage(
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
            ),
        )


# ---------------------------------------------------------------------------
# Fixtures -- auto-injected into tests by pytest
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_llm() -> FakeLLM:
    """Fresh FakeLLM instance for each test."""
    return FakeLLM()


@pytest.fixture
def fake_context() -> ProjectContext:
    """Minimal ProjectContext for testing.

    This represents a simple Python/FastAPI project. Tests that need
    different contexts should construct their own ProjectContext.
    """
    return ProjectContext(
        project_path="/tmp/test-project",
        directory_tree="src/\n  main.py\n  utils.py\ntests/\n  test_main.py",
        tech_stack=TechStack(
            languages=["Python"],
            frameworks=["FastAPI"],
            build_tools=["hatchling"],
            package_manager="pip",
            runtime="python3.11",
        ),
        config_files={"pyproject.toml": '[project]\nname = "test"'},
        relevant_files={"src/main.py": "def hello():\n    return 'world'"},
        test_patterns=TestPatterns(
            test_framework="pytest",
            test_directories=["tests/"],
            test_file_pattern="test_*.py",
            example_test_files=["tests/test_main.py"],
        ),
        summary="A simple Python FastAPI project.",
    )
