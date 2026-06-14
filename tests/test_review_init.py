"""Tests for the re-advise review init flow.

Acceptance criteria:
    Given I am on a History item page (loaded into session)
    When I click re-advise AND add context AND click send
    Then a new transcript is generated with:
        - A new plan_id (different hex, same slug pattern)
        - base_plan_id linking to the original plan
        - status = "review"
        - The original question from the user
        - All framer_messages copied from the original transcript
        - The framed_question copied from the original transcript
        - The re-advise feedback appended as a user message
    And the framing flow starts from there.

These tests exercise the backend logic that the daemon's
``POST /council/review/init`` endpoint calls.  They don't need
FastAPI or a running server -- they test the transcript + storage
modules directly, matching the exact sequence of operations the
endpoint performs.
"""

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from code_council.config import Settings
from code_council.storage import save_plan, load_plan
from code_council.transcript import (
    init_transcript,
    append_framer_message,
    set_framed_question,
    load_transcript,
)
from code_council.utils import generate_plan_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _test_settings(plan_dir: Path, transcript_dir: Path) -> Settings:
    """Create a Settings instance pointing to temp directories."""
    with mock.patch.dict(os.environ, {}, clear=True):
        s = Settings()
    s.code_council_save_plans = True
    s.code_council_plan_dir = str(plan_dir)
    s.code_council_transcript_dir = str(transcript_dir)
    return s


def _create_original_session(
    plan_id: str,
    transcript_dir: Path,
    plan_dir: Path,
    settings: Settings,
) -> None:
    """Simulate a completed first-time session: transcript + plan."""
    # Create transcript with full framer Q&A
    init_transcript(
        plan_id=plan_id,
        question="Want to build a cash deposit feature",
        transcript_dir=transcript_dir,
    )
    append_framer_message(
        plan_id=plan_id,
        role="user",
        text="Want to build a cash deposit feature",
        transcript_dir=transcript_dir,
    )
    append_framer_message(
        plan_id=plan_id,
        role="framer",
        text="What payment provider should we integrate with?",
        msg_id="1",
        choices=["Stripe", "PayPal", "Square"],
        transcript_dir=transcript_dir,
    )
    append_framer_message(
        plan_id=plan_id,
        role="user",
        text="Stripe",
        msg_id="1",
        transcript_dir=transcript_dir,
    )
    append_framer_message(
        plan_id=plan_id,
        role="framer",
        text="What currencies do you need to support?",
        msg_id="2",
        transcript_dir=transcript_dir,
    )
    append_framer_message(
        plan_id=plan_id,
        role="user",
        text="USD and EUR",
        msg_id="2",
        transcript_dir=transcript_dir,
    )
    set_framed_question(
        plan_id=plan_id,
        framed_question="Build cash deposit feature using Stripe supporting USD and EUR",
        transcript_dir=transcript_dir,
    )

    # Create plan with framed_requirement
    save_plan(
        plan_id=plan_id,
        change_description="Want to build a cash deposit feature",
        plan_data={"title": "Cash Deposit", "plan_id": plan_id},
        state_data={"status": "completed"},
        advisor_responses={"Executor": "Build it step by step."},
        context_summary="Python FastAPI project.",
        framed_requirement={
            "type": "story",
            "title": "Cash Deposit Feature",
            "description": "Build cash deposit feature using Stripe",
            "acceptance_criteria": ["Users can deposit USD", "Users can deposit EUR"],
            "out_of_scope": [],
            "assumptions": ["Stripe account exists"],
            "clarifications_needed": [],
            "stories": [],
        },
        settings=settings,
    )


def _simulate_review_init(
    base_plan_id: str,
    change_description: str,
    feedback: str,
    transcript_dir: Path,
    settings: Settings,
) -> dict:
    """Replicate the exact logic of POST /council/review/init.

    This mirrors daemon.py's init_review_session() so we can test
    the transcript creation without needing FastAPI running.
    """
    new_plan_id = generate_plan_id(change_description)

    # Load original transcript
    original_transcript = load_transcript(
        base_plan_id,
        transcript_dir=transcript_dir,
    )

    # Create new review transcript
    init_transcript(
        plan_id=new_plan_id,
        question=change_description,
        transcript_dir=transcript_dir,
        base_plan_id=base_plan_id,
        status="review",
    )

    # Copy framer_messages from original
    if original_transcript:
        for msg in original_transcript.get("framer_messages", []):
            append_framer_message(
                plan_id=new_plan_id,
                role=msg.get("role", "user"),
                text=msg.get("text", ""),
                msg_id=msg.get("msg_id"),
                choices=msg.get("choices"),
                transcript_dir=transcript_dir,
            )
        framed_q = original_transcript.get("framed_question")
        if framed_q:
            set_framed_question(
                plan_id=new_plan_id,
                framed_question=framed_q,
                transcript_dir=transcript_dir,
            )

    # Append feedback
    append_framer_message(
        plan_id=new_plan_id,
        role="user",
        text=f"[RE-ADVISE FEEDBACK]: {feedback}",
        transcript_dir=transcript_dir,
    )

    # Load framed_requirement from original plan
    framed_requirement = None
    original_plan = load_plan(base_plan_id, settings=settings)
    if original_plan and original_plan.get("framed_requirement"):
        framed_requirement = original_plan["framed_requirement"]

    return {
        "plan_id": new_plan_id,
        "base_plan_id": base_plan_id,
        "framed_question": (
            original_transcript.get("framed_question")
            if original_transcript
            else None
        ),
        "framed_requirement": framed_requirement,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReviewInitCreatesTranscript:
    """The review init flow must create a new transcript with all context."""

    def test_new_transcript_has_different_plan_id(self, tmp_path: Path) -> None:
        transcript_dir = tmp_path / "transcripts"
        plan_dir = tmp_path / "plans"
        settings = _test_settings(plan_dir, transcript_dir)
        original_id = "abc123-cash-deposit"

        _create_original_session(original_id, transcript_dir, plan_dir, settings)
        result = _simulate_review_init(
            base_plan_id=original_id,
            change_description="Want to build a cash deposit feature",
            feedback="Add support for GBP too",
            transcript_dir=transcript_dir,
            settings=settings,
        )

        assert result["plan_id"] != original_id
        assert len(result["plan_id"]) > 0

    def test_new_transcript_has_base_plan_id(self, tmp_path: Path) -> None:
        transcript_dir = tmp_path / "transcripts"
        plan_dir = tmp_path / "plans"
        settings = _test_settings(plan_dir, transcript_dir)
        original_id = "abc123-cash-deposit"

        _create_original_session(original_id, transcript_dir, plan_dir, settings)
        result = _simulate_review_init(
            base_plan_id=original_id,
            change_description="Want to build a cash deposit feature",
            feedback="Add support for GBP too",
            transcript_dir=transcript_dir,
            settings=settings,
        )

        new_transcript = load_transcript(result["plan_id"], transcript_dir=transcript_dir)
        assert new_transcript is not None
        assert new_transcript["base_plan_id"] == original_id

    def test_new_transcript_has_review_status(self, tmp_path: Path) -> None:
        transcript_dir = tmp_path / "transcripts"
        plan_dir = tmp_path / "plans"
        settings = _test_settings(plan_dir, transcript_dir)
        original_id = "abc123-cash-deposit"

        _create_original_session(original_id, transcript_dir, plan_dir, settings)
        result = _simulate_review_init(
            base_plan_id=original_id,
            change_description="Want to build a cash deposit feature",
            feedback="Add support for GBP too",
            transcript_dir=transcript_dir,
            settings=settings,
        )

        new_transcript = load_transcript(result["plan_id"], transcript_dir=transcript_dir)
        assert new_transcript is not None
        assert new_transcript["status"] == "review"

    def test_new_transcript_has_original_question(self, tmp_path: Path) -> None:
        transcript_dir = tmp_path / "transcripts"
        plan_dir = tmp_path / "plans"
        settings = _test_settings(plan_dir, transcript_dir)
        original_id = "abc123-cash-deposit"

        _create_original_session(original_id, transcript_dir, plan_dir, settings)
        result = _simulate_review_init(
            base_plan_id=original_id,
            change_description="Want to build a cash deposit feature",
            feedback="Add support for GBP too",
            transcript_dir=transcript_dir,
            settings=settings,
        )

        new_transcript = load_transcript(result["plan_id"], transcript_dir=transcript_dir)
        assert new_transcript is not None
        assert new_transcript["question"] == "Want to build a cash deposit feature"

    def test_new_transcript_copies_all_framer_messages(self, tmp_path: Path) -> None:
        transcript_dir = tmp_path / "transcripts"
        plan_dir = tmp_path / "plans"
        settings = _test_settings(plan_dir, transcript_dir)
        original_id = "abc123-cash-deposit"

        _create_original_session(original_id, transcript_dir, plan_dir, settings)

        original_transcript = load_transcript(original_id, transcript_dir=transcript_dir)
        assert original_transcript is not None
        original_msg_count = len(original_transcript["framer_messages"])

        result = _simulate_review_init(
            base_plan_id=original_id,
            change_description="Want to build a cash deposit feature",
            feedback="Add support for GBP too",
            transcript_dir=transcript_dir,
            settings=settings,
        )

        new_transcript = load_transcript(result["plan_id"], transcript_dir=transcript_dir)
        assert new_transcript is not None

        # All original messages + 1 feedback message
        assert len(new_transcript["framer_messages"]) == original_msg_count + 1

        # First N messages match the originals exactly
        for i in range(original_msg_count):
            orig = original_transcript["framer_messages"][i]
            copied = new_transcript["framer_messages"][i]
            assert copied["role"] == orig["role"]
            assert copied["text"] == orig["text"]

    def test_new_transcript_copies_framed_question(self, tmp_path: Path) -> None:
        transcript_dir = tmp_path / "transcripts"
        plan_dir = tmp_path / "plans"
        settings = _test_settings(plan_dir, transcript_dir)
        original_id = "abc123-cash-deposit"

        _create_original_session(original_id, transcript_dir, plan_dir, settings)
        result = _simulate_review_init(
            base_plan_id=original_id,
            change_description="Want to build a cash deposit feature",
            feedback="Add support for GBP too",
            transcript_dir=transcript_dir,
            settings=settings,
        )

        new_transcript = load_transcript(result["plan_id"], transcript_dir=transcript_dir)
        assert new_transcript is not None
        assert new_transcript["framed_question"] == (
            "Build cash deposit feature using Stripe supporting USD and EUR"
        )

    def test_feedback_appended_as_last_message(self, tmp_path: Path) -> None:
        transcript_dir = tmp_path / "transcripts"
        plan_dir = tmp_path / "plans"
        settings = _test_settings(plan_dir, transcript_dir)
        original_id = "abc123-cash-deposit"

        _create_original_session(original_id, transcript_dir, plan_dir, settings)
        result = _simulate_review_init(
            base_plan_id=original_id,
            change_description="Want to build a cash deposit feature",
            feedback="Add support for GBP too",
            transcript_dir=transcript_dir,
            settings=settings,
        )

        new_transcript = load_transcript(result["plan_id"], transcript_dir=transcript_dir)
        assert new_transcript is not None

        last_msg = new_transcript["framer_messages"][-1]
        assert last_msg["role"] == "user"
        assert "[RE-ADVISE FEEDBACK]" in last_msg["text"]
        assert "Add support for GBP too" in last_msg["text"]

    def test_response_includes_framed_requirement_from_plan(
        self, tmp_path: Path
    ) -> None:
        transcript_dir = tmp_path / "transcripts"
        plan_dir = tmp_path / "plans"
        settings = _test_settings(plan_dir, transcript_dir)
        original_id = "abc123-cash-deposit"

        _create_original_session(original_id, transcript_dir, plan_dir, settings)
        result = _simulate_review_init(
            base_plan_id=original_id,
            change_description="Want to build a cash deposit feature",
            feedback="Add support for GBP too",
            transcript_dir=transcript_dir,
            settings=settings,
        )

        assert result["framed_requirement"] is not None
        assert result["framed_requirement"]["title"] == "Cash Deposit Feature"

    def test_response_includes_framed_question(self, tmp_path: Path) -> None:
        transcript_dir = tmp_path / "transcripts"
        plan_dir = tmp_path / "plans"
        settings = _test_settings(plan_dir, transcript_dir)
        original_id = "abc123-cash-deposit"

        _create_original_session(original_id, transcript_dir, plan_dir, settings)
        result = _simulate_review_init(
            base_plan_id=original_id,
            change_description="Want to build a cash deposit feature",
            feedback="Add support for GBP too",
            transcript_dir=transcript_dir,
            settings=settings,
        )

        assert result["framed_question"] == (
            "Build cash deposit feature using Stripe supporting USD and EUR"
        )


class TestReviewInitNoOriginalTranscript:
    """When the original was created via web UI (no transcript), handle gracefully."""

    def test_works_without_original_transcript(self, tmp_path: Path) -> None:
        transcript_dir = tmp_path / "transcripts"
        plan_dir = tmp_path / "plans"
        settings = _test_settings(plan_dir, transcript_dir)
        original_id = "web-plan-no-transcript"

        # Only create a plan, no transcript (simulates web UI flow)
        save_plan(
            plan_id=original_id,
            change_description="Add JWT auth",
            plan_data={"title": "JWT Auth", "plan_id": original_id},
            state_data={"status": "completed"},
            advisor_responses={"Executor": "Steps here."},
            context_summary="Node.js project.",
            framed_requirement={
                "type": "story",
                "title": "JWT Auth",
                "description": "Add JWT authentication",
                "acceptance_criteria": [],
                "out_of_scope": [],
                "assumptions": [],
                "clarifications_needed": [],
                "stories": [],
            },
            settings=settings,
        )

        result = _simulate_review_init(
            base_plan_id=original_id,
            change_description="Add JWT auth",
            feedback="Also add refresh tokens",
            transcript_dir=transcript_dir,
            settings=settings,
        )

        # Should still create a valid transcript
        new_transcript = load_transcript(result["plan_id"], transcript_dir=transcript_dir)
        assert new_transcript is not None
        assert new_transcript["base_plan_id"] == original_id
        assert new_transcript["status"] == "review"
        # Only the feedback message (no copied messages)
        assert len(new_transcript["framer_messages"]) == 1
        assert "[RE-ADVISE FEEDBACK]" in new_transcript["framer_messages"][0]["text"]
        # No framed_question from transcript (but framed_requirement from plan)
        assert new_transcript["framed_question"] is None
        assert result["framed_requirement"] is not None
        assert result["framed_requirement"]["title"] == "JWT Auth"


class TestReviewInitPreservesMessageStructure:
    """Copied messages must preserve msg_id and choices."""

    def test_msg_ids_and_choices_preserved(self, tmp_path: Path) -> None:
        transcript_dir = tmp_path / "transcripts"
        plan_dir = tmp_path / "plans"
        settings = _test_settings(plan_dir, transcript_dir)
        original_id = "struct-test"

        _create_original_session(original_id, transcript_dir, plan_dir, settings)
        result = _simulate_review_init(
            base_plan_id=original_id,
            change_description="Want to build a cash deposit feature",
            feedback="Reconsider approach",
            transcript_dir=transcript_dir,
            settings=settings,
        )

        new_transcript = load_transcript(result["plan_id"], transcript_dir=transcript_dir)
        assert new_transcript is not None

        # The second message was a framer question with msg_id and choices
        framer_msg = new_transcript["framer_messages"][1]
        assert framer_msg["role"] == "framer"
        assert framer_msg["msg_id"] == "1"
        assert framer_msg["choices"] == ["Stripe", "PayPal", "Square"]


class TestReviewInitNoPlanCreated:
    """Re-advise init must NOT create a plan -- only a transcript."""

    def test_no_plan_file_created(self, tmp_path: Path) -> None:
        transcript_dir = tmp_path / "transcripts"
        plan_dir = tmp_path / "plans"
        settings = _test_settings(plan_dir, transcript_dir)
        original_id = "abc123-cash-deposit"

        _create_original_session(original_id, transcript_dir, plan_dir, settings)
        result = _simulate_review_init(
            base_plan_id=original_id,
            change_description="Want to build a cash deposit feature",
            feedback="Add GBP support",
            transcript_dir=transcript_dir,
            settings=settings,
        )

        new_plan_id = result["plan_id"]
        # The new plan_id should NOT have a plan file yet
        assert load_plan(new_plan_id, settings=settings) is None
        # But the transcript should exist
        assert load_transcript(new_plan_id, transcript_dir=transcript_dir) is not None


class TestTranscriptBaseAndStatus:
    """Verify the new base_plan_id and status fields on init_transcript."""

    def test_first_plan_has_null_base_plan_id(self, tmp_path: Path) -> None:
        init_transcript(
            plan_id="first-plan",
            question="Build something",
            transcript_dir=tmp_path,
        )
        data = load_transcript("first-plan", transcript_dir=tmp_path)
        assert data is not None
        assert data["base_plan_id"] is None
        assert data["status"] == "active"

    def test_review_transcript_has_base_and_status(self, tmp_path: Path) -> None:
        init_transcript(
            plan_id="review-plan",
            question="Revised build",
            transcript_dir=tmp_path,
            base_plan_id="original-123",
            status="review",
        )
        data = load_transcript("review-plan", transcript_dir=tmp_path)
        assert data is not None
        assert data["base_plan_id"] == "original-123"
        assert data["status"] == "review"


class TestStorageBasePlanId:
    """Verify base_plan_id is saved and retrieved from plan files."""

    def test_save_plan_with_base_plan_id(self, tmp_path: Path) -> None:
        settings = _test_settings(tmp_path, tmp_path)
        save_plan(
            plan_id="review-v2",
            change_description="Revised auth",
            plan_data={"title": "Auth v2"},
            state_data={"status": "completed"},
            advisor_responses={},
            context_summary="",
            base_plan_id="original-auth",
            settings=settings,
        )
        data = load_plan("review-v2", settings=settings)
        assert data is not None
        assert data["base_plan_id"] == "original-auth"

    def test_save_plan_without_base_plan_id(self, tmp_path: Path) -> None:
        settings = _test_settings(tmp_path, tmp_path)
        save_plan(
            plan_id="first-plan",
            change_description="New feature",
            plan_data={"title": "Feature"},
            state_data={"status": "completed"},
            advisor_responses={},
            context_summary="",
            settings=settings,
        )
        data = load_plan("first-plan", settings=settings)
        assert data is not None
        assert data["base_plan_id"] is None

    def test_list_plans_includes_base_plan_id(self, tmp_path: Path) -> None:
        settings = _test_settings(tmp_path, tmp_path)
        save_plan(
            plan_id="linked-plan",
            change_description="Linked",
            plan_data={"title": "Linked"},
            state_data={"status": "completed"},
            advisor_responses={},
            context_summary="",
            base_plan_id="parent-123",
            settings=settings,
        )
        from code_council.storage import list_recent_plans
        plans = list_recent_plans(settings=settings)
        assert len(plans) == 1
        assert plans[0]["base_plan_id"] == "parent-123"


class TestGeneratePlanId:
    """Ensure generate_plan_id produces valid, unique IDs."""

    def test_format(self) -> None:
        pid = generate_plan_id("Add user authentication")
        parts = pid.split("-", 1)
        assert len(parts) == 2
        assert len(parts[0]) == 12  # hex prefix

    def test_unique(self) -> None:
        a = generate_plan_id("same description")
        b = generate_plan_id("same description")
        assert a != b  # different UUIDs
