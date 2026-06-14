"""Tests for the ``--load`` resume logic.

Validates that ``_resolve_load_context`` correctly picks the resume
point (plan vs transcript, synthesis vs confirmation), and that
``_extract_qa_pairs`` reconstructs Q&A from transcript messages.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from code_council.cli import (
    _extract_qa_pairs,
    _generate_plan_id,
    _resolve_load_context,
    _RESUME_CONFIRMATION,
    _RESUME_SYNTHESIS,
)
from code_council.config import Settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _test_settings(tmp_path: Path) -> Settings:
    """Create a Settings instance pointing to temp directories."""
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()

    with mock.patch.dict(os.environ, {}, clear=True):
        s = Settings()
    s.code_council_save_plans = True
    s.code_council_plan_dir = str(plans_dir)
    s.code_council_transcript_dir = str(transcripts_dir)
    return s


def _write_plan(settings: Settings, plan_id: str, data: dict) -> None:
    """Write a plan JSON file."""
    path = Path(settings.code_council_plan_dir) / f"plan-{plan_id}.json"
    path.write_text(json.dumps(data, indent=2))


def _write_transcript(settings: Settings, plan_id: str, data: dict) -> None:
    """Write a transcript JSON file."""
    path = Path(settings.code_council_transcript_dir) / f"transcript-{plan_id}.json"
    path.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# _generate_plan_id
# ---------------------------------------------------------------------------


class TestGeneratePlanId:
    def test_format_hex_dash_slug(self) -> None:
        pid = _generate_plan_id("Add user authentication")
        parts = pid.split("-", 1)
        assert len(parts) == 2
        # hex part is 12 hex chars
        assert len(parts[0]) == 12
        assert all(c in "0123456789abcdef" for c in parts[0])
        # slug part is lowercase words
        assert parts[1] == "add-user-authentication"

    def test_truncates_to_four_content_words(self) -> None:
        pid = _generate_plan_id("I want to build a cash deposit feature now")
        slug = pid.split("-", 1)[1]
        # Stop words stripped; keeps first 4 meaningful words
        assert slug == "build-cash-deposit-feature"

    def test_strips_special_characters(self) -> None:
        pid = _generate_plan_id("Add JWT auth! (v2) -- for the API")
        slug = pid.split("-", 1)[1]
        # special chars removed, only alphanumeric words kept
        assert "!" not in slug
        assert "(" not in slug
        assert "--" not in slug

    def test_empty_description_fallback(self) -> None:
        pid = _generate_plan_id("")
        slug = pid.split("-", 1)[1]
        assert slug == "plan"

    def test_unique_ids(self) -> None:
        """Two calls with the same description produce different IDs."""
        id1 = _generate_plan_id("Same description")
        id2 = _generate_plan_id("Same description")
        assert id1 != id2  # different UUID hex prefixes

    def test_slug_is_lowercase(self) -> None:
        pid = _generate_plan_id("ADD USER AUTH")
        slug = pid.split("-", 1)[1]
        assert slug == slug.lower()


# ---------------------------------------------------------------------------
# _resolve_load_context
# ---------------------------------------------------------------------------


class TestResolveLoadContext:
    """Tests for the multi-source context resolution logic."""

    def test_returns_none_when_nothing_found(self, tmp_path: Path) -> None:
        settings = _test_settings(tmp_path)
        result = _resolve_load_context("nonexistent", settings)
        assert result is None

    def test_plan_with_advisor_responses_resumes_at_synthesis(
        self, tmp_path: Path,
    ) -> None:
        settings = _test_settings(tmp_path)
        _write_plan(settings, "abc123", {
            "plan_id": "abc123",
            "change_description": "Add auth",
            "framed_requirement": {
                "type": "story",
                "title": "Add Auth",
                "description": "Add authentication",
            },
            "advisor_responses": {
                "Architect Advisor": "Use JWT.",
                "Security Advisor": "Validate tokens.",
            },
            "context_summary": "Python FastAPI project.",
        })

        result = _resolve_load_context("abc123", settings)
        assert result is not None
        assert result["source"] == "plan"
        assert result["resume_point"] == _RESUME_SYNTHESIS
        assert result["description"] == "Add auth"
        assert result["advisor_responses"]["Architect Advisor"] == "Use JWT."
        assert result["framed_data"]["title"] == "Add Auth"

    def test_plan_with_framed_but_no_advisors_resumes_at_confirmation(
        self, tmp_path: Path,
    ) -> None:
        settings = _test_settings(tmp_path)
        _write_plan(settings, "def456", {
            "plan_id": "def456",
            "change_description": "Add payments",
            "framed_requirement": {
                "type": "epic",
                "title": "Add Payments",
                "description": "Add payment processing",
            },
            # No advisor_responses key
        })

        result = _resolve_load_context("def456", settings)
        assert result is not None
        assert result["source"] == "plan"
        assert result["resume_point"] == _RESUME_CONFIRMATION
        assert result["framed_data"]["title"] == "Add Payments"

    def test_plan_without_framed_falls_through_to_transcript(
        self, tmp_path: Path,
    ) -> None:
        """A plan with no framed_requirement should fall through to
        check for a transcript."""
        settings = _test_settings(tmp_path)
        # Plan without framed_requirement
        _write_plan(settings, "ghi789", {
            "plan_id": "ghi789",
            "change_description": "Legacy plan",
        })
        # Transcript exists for same ID
        _write_transcript(settings, "ghi789", {
            "plan_id": "ghi789",
            "question": "Add legacy feature",
            "framer_messages": [
                {"role": "user", "text": "Add legacy feature"},
                {"role": "framer", "text": "What provider?", "msg_id": "1"},
                {"role": "user", "text": "Stripe", "msg_id": "1"},
            ],
            "framed_question": "Add legacy feature with Stripe",
        })

        result = _resolve_load_context("ghi789", settings)
        assert result is not None
        assert result["source"] == "transcript"
        assert result["description"] == "Add legacy feature"
        assert len(result["all_answers"]) == 1
        assert "Stripe" in result["all_answers"][0]

    def test_transcript_only_with_qa_pairs(self, tmp_path: Path) -> None:
        settings = _test_settings(tmp_path)
        _write_transcript(settings, "tx001", {
            "plan_id": "tx001",
            "question": "Build a dashboard",
            "framer_messages": [
                {"role": "user", "text": "Build a dashboard"},
                {"role": "framer", "text": "What metrics?", "msg_id": "1"},
                {"role": "user", "text": "Revenue and signups", "msg_id": "1"},
                {"role": "framer", "text": "What framework?", "msg_id": "2"},
                {"role": "user", "text": "React", "msg_id": "2"},
            ],
            "framed_question": "Dashboard with revenue/signup metrics in React",
        })

        result = _resolve_load_context("tx001", settings)
        assert result is not None
        assert result["source"] == "transcript"
        assert result["resume_point"] == _RESUME_CONFIRMATION
        assert result["description"] == "Build a dashboard"
        assert len(result["all_answers"]) == 2

    def test_transcript_with_no_qa_pairs(self, tmp_path: Path) -> None:
        """A transcript with only the initial user message (no Q&A)."""
        settings = _test_settings(tmp_path)
        _write_transcript(settings, "tx002", {
            "plan_id": "tx002",
            "question": "Build something simple",
            "framer_messages": [
                {"role": "user", "text": "Build something simple"},
            ],
            "framed_question": None,
        })

        result = _resolve_load_context("tx002", settings)
        assert result is not None
        assert result["source"] == "transcript"
        assert result["all_answers"] == []
        # No Q&A pairs -> not RESUME_CONFIRMATION
        assert result["resume_point"] != _RESUME_CONFIRMATION

    def test_plan_takes_priority_over_transcript(
        self, tmp_path: Path,
    ) -> None:
        """When both a plan and transcript exist, the plan should win."""
        settings = _test_settings(tmp_path)

        _write_plan(settings, "both01", {
            "plan_id": "both01",
            "change_description": "Feature X",
            "framed_requirement": {
                "type": "task",
                "title": "Feature X",
                "description": "Implement feature X",
            },
            "advisor_responses": {"Executor Advisor": "Step 1: do it."},
        })

        _write_transcript(settings, "both01", {
            "plan_id": "both01",
            "question": "Feature X",
            "framer_messages": [{"role": "user", "text": "Feature X"}],
            "framed_question": "Implement feature X",
        })

        result = _resolve_load_context("both01", settings)
        assert result is not None
        assert result["source"] == "plan"
        assert result["resume_point"] == _RESUME_SYNTHESIS


# ---------------------------------------------------------------------------
# _extract_qa_pairs
# ---------------------------------------------------------------------------


class TestExtractQAPairs:
    def test_empty_messages(self) -> None:
        assert _extract_qa_pairs([]) == []

    def test_single_qa_pair(self) -> None:
        messages = [
            {"role": "framer", "text": "What provider?", "msg_id": "1"},
            {"role": "user", "text": "Stripe", "msg_id": "1"},
        ]
        pairs = _extract_qa_pairs(messages)
        assert len(pairs) == 1
        assert "What provider?" in pairs[0]
        assert "Stripe" in pairs[0]

    def test_multiple_qa_pairs(self) -> None:
        messages = [
            {"role": "framer", "text": "Q1?", "msg_id": "1"},
            {"role": "user", "text": "A1", "msg_id": "1"},
            {"role": "framer", "text": "Q2?", "msg_id": "2"},
            {"role": "user", "text": "A2", "msg_id": "2"},
        ]
        pairs = _extract_qa_pairs(messages)
        assert len(pairs) == 2
        assert "Q1?" in pairs[0]
        assert "A1" in pairs[0]
        assert "Q2?" in pairs[1]
        assert "A2" in pairs[1]

    def test_user_messages_without_msg_id_are_skipped(self) -> None:
        """Initial user messages (the feature request) have no msg_id."""
        messages = [
            {"role": "user", "text": "Build a dashboard"},
            {"role": "framer", "text": "What metrics?", "msg_id": "1"},
            {"role": "user", "text": "Revenue", "msg_id": "1"},
        ]
        pairs = _extract_qa_pairs(messages)
        assert len(pairs) == 1
        assert "Revenue" in pairs[0]

    def test_unpaired_framer_question_no_answer(self) -> None:
        """A framer question with no matching user answer produces no pair."""
        messages = [
            {"role": "framer", "text": "Unanswered?", "msg_id": "1"},
        ]
        pairs = _extract_qa_pairs(messages)
        assert len(pairs) == 0

    def test_framer_messages_without_msg_id_skipped(self) -> None:
        """Framer messages like [FRAMED] have no msg_id -- not Q&A."""
        messages = [
            {"role": "framer", "text": "[FRAMED] My Feature\nType: story"},
        ]
        pairs = _extract_qa_pairs(messages)
        assert len(pairs) == 0
