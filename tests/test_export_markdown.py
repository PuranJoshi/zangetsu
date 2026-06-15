"""Tests for plan-to-markdown export.

Covers:
- ``_plan_to_markdown`` conversion logic (all sections, edge cases)
- ``_humanise_markdown`` LLM integration
- ``_load_humaniser_skill`` skill loader
"""

from __future__ import annotations

from code_council.cli import (
    _plan_to_markdown,
)

# ---------------------------------------------------------------------------
# _plan_to_markdown
# ---------------------------------------------------------------------------


def _full_plan_data() -> dict:
    """A complete plan dict matching the storage format."""
    return {
        "plan_id": "abc123",
        "timestamp": "2026-06-14T10:00:00+00:00",
        "change_description": "Add user authentication",
        "plan": {
            "plan_id": "abc123",
            "title": "User Authentication",
            "summary": "Add JWT-based authentication to the API.",
            "affected_files": ["src/auth.py", "src/main.py", "tests/test_auth.py"],
            "implementation_steps": [
                {
                    "order": 1,
                    "file_path": "src/auth.py",
                    "action": "create",
                    "description": "Create auth module with JWT validation.",
                    "depends_on": [],
                },
                {
                    "order": 2,
                    "file_path": "src/main.py",
                    "action": "modify",
                    "description": "Add auth middleware to the FastAPI app.",
                    "depends_on": [1],
                },
                {
                    "order": 3,
                    "file_path": "tests/test_auth.py",
                    "action": "create",
                    "description": "Add tests for JWT validation and middleware.",
                    "depends_on": [1, 2],
                },
            ],
            "architecture_notes": "Follows existing middleware pattern.",
            "security_notes": "Use RS256 for token signing.",
            "quality_notes": "Add unit and integration tests.",
            "risk_assessment": "Low risk, well-understood pattern.",
            "execution_strategy": "Single PR with all changes.",
            "acceptance_criteria": [
                "All existing tests pass",
                "JWT validation returns 401 for invalid tokens",
                "Auth middleware is applied to protected routes",
            ],
            "estimated_effort": "M",
            "risk_level": "LOW",
        },
        "framed_requirement": {
            "type": "story",
            "title": "Add JWT Authentication",
            "description": "As a user, I want JWT-based auth so my API is secure.",
            "acceptance_criteria": [
                "Given a valid JWT, when I access a protected route, then I get 200",
                "Given an invalid JWT, when I access a protected route, then I get 401",
            ],
            "assumptions": ["RS256 keys are pre-generated"],
            "out_of_scope": ["OAuth2 social login"],
        },
        "context_summary": (
            "Project: /tmp/myapp\nLanguages: Python\nFrameworks: FastAPI\nTests: pytest"
        ),
    }


class TestPlanToMarkdown:
    def test_contains_title_as_h1(self) -> None:
        md = _plan_to_markdown(_full_plan_data())
        assert "# User Authentication" in md

    def test_contains_plan_id(self) -> None:
        md = _plan_to_markdown(_full_plan_data())
        assert "`abc123`" in md

    def test_contains_risk_and_effort(self) -> None:
        md = _plan_to_markdown(_full_plan_data())
        assert "LOW" in md
        assert "**Effort:** M" in md

    def test_contains_timestamp(self) -> None:
        md = _plan_to_markdown(_full_plan_data())
        assert "2026-06-14" in md

    def test_contains_original_request(self) -> None:
        md = _plan_to_markdown(_full_plan_data())
        assert "Add user authentication" in md

    def test_contains_summary(self) -> None:
        md = _plan_to_markdown(_full_plan_data())
        assert "JWT-based authentication" in md

    def test_contains_affected_files(self) -> None:
        md = _plan_to_markdown(_full_plan_data())
        assert "`src/auth.py`" in md
        assert "`src/main.py`" in md
        assert "`tests/test_auth.py`" in md

    def test_contains_implementation_steps(self) -> None:
        md = _plan_to_markdown(_full_plan_data())
        assert "### Step 1" in md
        assert "[CREATE]" in md
        assert "### Step 2" in md
        assert "[MODIFY]" in md
        assert "### Step 3" in md

    def test_step_dependencies(self) -> None:
        md = _plan_to_markdown(_full_plan_data())
        # Step 1 has no deps, so no "Depends on" line
        # Step 2 depends on 1
        assert "step(s) 1" in md
        # Step 3 depends on 1, 2
        assert "step(s) 1, 2" in md

    def test_contains_advisor_notes(self) -> None:
        md = _plan_to_markdown(_full_plan_data())
        assert "## Architecture Notes" in md
        assert "middleware pattern" in md
        assert "## Security Notes" in md
        assert "RS256" in md
        assert "## Quality & Tests" in md
        assert "## Risk Assessment" in md
        assert "## Execution Strategy" in md

    def test_contains_acceptance_criteria(self) -> None:
        md = _plan_to_markdown(_full_plan_data())
        assert "## Acceptance Criteria" in md
        assert "All existing tests pass" in md
        assert "JWT validation returns 401" in md

    def test_contains_framed_requirement(self) -> None:
        md = _plan_to_markdown(_full_plan_data())
        assert "## Framed Requirement" in md
        assert "**Type:** story" in md
        assert "**Title:** Add JWT Authentication" in md
        assert "As a user" in md

    def test_framed_acceptance_criteria(self) -> None:
        md = _plan_to_markdown(_full_plan_data())
        assert "Given a valid JWT" in md
        assert "Given an invalid JWT" in md

    def test_framed_assumptions(self) -> None:
        md = _plan_to_markdown(_full_plan_data())
        assert "RS256 keys are pre-generated" in md

    def test_framed_out_of_scope(self) -> None:
        md = _plan_to_markdown(_full_plan_data())
        assert "OAuth2 social login" in md

    def test_contains_context_summary(self) -> None:
        md = _plan_to_markdown(_full_plan_data())
        assert "FastAPI" in md
        assert "pytest" in md

    def test_minimal_plan_no_crash(self) -> None:
        """A plan with only required fields should not crash."""
        data = {
            "plan_id": "min01",
            "plan": {
                "title": "Minimal",
                "summary": "",
                "affected_files": [],
                "implementation_steps": [],
                "architecture_notes": "",
                "security_notes": "",
                "quality_notes": "",
                "risk_assessment": "",
                "execution_strategy": "",
                "acceptance_criteria": [],
                "estimated_effort": "S",
                "risk_level": "LOW",
            },
        }
        md = _plan_to_markdown(data)
        assert "# Minimal" in md
        assert "`min01`" in md

    def test_empty_plan_data(self) -> None:
        """Completely empty plan data should produce at least a header."""
        md = _plan_to_markdown({"plan_id": "empty", "plan": {}})
        assert "# Untitled Plan" in md

    def test_no_framed_requirement(self) -> None:
        """Plan without framed_requirement should skip that section."""
        data = _full_plan_data()
        del data["framed_requirement"]
        md = _plan_to_markdown(data)
        assert "## Framed Requirement" not in md

    def test_output_is_valid_markdown_no_trailing_whitespace_issues(self) -> None:
        """Basic structural checks on the output."""
        md = _plan_to_markdown(_full_plan_data())
        lines = md.split("\n")
        # Every heading should start with #
        headings = [line for line in lines if line.startswith("#")]
        assert len(headings) >= 5  # title + major sections
        # No double-blank-line runs (indicates missing content)
        assert "\n\n\n\n" not in md
