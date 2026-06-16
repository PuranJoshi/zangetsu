"""Tests for code_council.framer -- requirements gate.

The Framer takes a raw feature request and produces structured requirements
(Jira-style: epic/story/task/bug). It asks clarifying questions when the
request is ambiguous. No advisor runs until the Framer signs off.

Python lesson: json.loads in tests
    The Framer returns JSON. We parse it in tests to verify the structure.
    json.loads() returns a dict, which is easier to assert against than
    string matching. Always parse JSON in tests rather than using 'in'.
"""

import pytest

from code_council.framer import (
    FramedRequirement,
    _extract_json,
    _framer_prompt,
    _framer_system_prompt,
    _load_framer_skill,
    frame_request,
)


class TestFramedRequirement:
    """Test the Pydantic model that holds framed requirements."""

    def test_minimal_story(self) -> None:
        req = FramedRequirement(
            type="story",
            title="Add login",
            description="Users can log in with email/password",
            acceptance_criteria=["Given valid creds, when login, then 200"],
        )
        assert req.type == "story"
        assert len(req.acceptance_criteria) == 1

    def test_epic_with_stories(self) -> None:
        req = FramedRequirement(
            type="epic",
            title="User auth",
            description="Full authentication system",
            acceptance_criteria=[],
            stories=[
                FramedRequirement(
                    type="story",
                    title="Login",
                    description="Email/password login",
                    acceptance_criteria=["Returns JWT on success"],
                ),
            ],
        )
        assert req.type == "epic"
        assert len(req.stories) == 1

    def test_has_clarifications(self) -> None:
        req = FramedRequirement(
            type="story",
            title="Add feature",
            description="Vague request",
            acceptance_criteria=[],
            clarifications_needed=["What kind of feature?"],
        )
        assert req.needs_clarification()

    def test_no_clarifications(self) -> None:
        req = FramedRequirement(
            type="task",
            title="Clear task",
            description="Very specific task",
            acceptance_criteria=["Tests pass"],
        )
        assert not req.needs_clarification()


class TestExtractJson:
    def test_extracts_from_code_fence(self) -> None:
        text = 'Text\n```json\n{"type": "story"}\n```\nMore'
        assert _extract_json(text) == '{"type": "story"}'

    def test_handles_raw_json(self) -> None:
        text = '{"type": "bug"}'
        assert _extract_json(text) == '{"type": "bug"}'

    def test_handles_generic_code_fence(self) -> None:
        text = 'Text\n```\n{"type": "task"}\n```\nMore'
        assert _extract_json(text) == '{"type": "task"}'


class TestFramerPrompt:
    def test_includes_change_description(self) -> None:
        prompt = _framer_prompt("add authentication to the API")
        assert "add authentication to the API" in prompt

    def test_includes_context_summary(self) -> None:
        system = _framer_system_prompt("Python FastAPI project with JWT")
        assert "Python FastAPI project" in system

    def test_includes_previous_clarifications(self) -> None:
        prompt = _framer_prompt(
            "feature",
            clarification_answers="OAuth2 with Google provider",
        )
        assert "OAuth2 with Google" in prompt


class TestLoadFramerSkill:
    def test_loads_skill_from_real_skills_dir(self) -> None:
        """The real framer.md should exist and be loadable."""
        skill_text = _load_framer_skill()
        assert "Requirements Framer" in skill_text


@pytest.mark.asyncio
async def test_frame_request_returns_valid_requirement(fake_llm) -> None:
    """End-to-end: frame_request should return a FramedRequirement.

    Uses the FakeLLM from conftest.py which returns canned JSON for
    framer prompts.
    """
    result, usage = await frame_request(
        change_description="Add user authentication",
        context_summary="Python FastAPI project",
        llm=fake_llm,
    )
    assert isinstance(result, FramedRequirement)
    assert result.type in ("epic", "story", "task", "bug")
    assert result.title != ""
    assert usage.total_tokens > 0
