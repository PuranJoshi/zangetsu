"""Tests for code_council.transcript -- session transcript storage.

The transcript records the running dialogue of a bankai session:
original question, every framer exchange, and the final framed requirement.

Python lesson: tmp_path fixture
    Each test gets its own temporary directory so transcripts are isolated
    and auto-cleaned.  We pass ``transcript_dir=tmp_path`` to every
    function to avoid touching the real ``~/.code-council/transcripts/``.
"""

import json
from pathlib import Path

from code_council.transcript import (
    append_framer_message,
    init_transcript,
    load_transcript,
    set_framed_question,
)


class TestInitTranscript:
    def test_creates_file(self, tmp_path: Path) -> None:
        path = init_transcript(
            plan_id="abc123",
            question="Add user auth",
            transcript_dir=tmp_path,
        )
        assert path.is_file()
        data = json.loads(path.read_text())
        assert data["plan_id"] == "abc123"
        assert data["question"] == "Add user auth"
        assert data["framer_messages"] == []
        assert data["framed_question"] is None

    def test_creates_directory_if_missing(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "transcripts"
        path = init_transcript(
            plan_id="nested-1",
            question="test",
            transcript_dir=nested,
        )
        assert nested.is_dir()
        assert path.is_file()

    def test_includes_timestamp(self, tmp_path: Path) -> None:
        path = init_transcript(
            plan_id="ts-1",
            question="test",
            transcript_dir=tmp_path,
        )
        data = json.loads(path.read_text())
        assert "timestamp" in data
        assert "T" in data["timestamp"]  # ISO format check


class TestAppendFramerMessage:
    def test_appends_user_message(self, tmp_path: Path) -> None:
        init_transcript(plan_id="msg-1", question="q", transcript_dir=tmp_path)
        append_framer_message(
            plan_id="msg-1",
            role="user",
            text="I want cash deposits",
            transcript_dir=tmp_path,
        )
        data = load_transcript("msg-1", transcript_dir=tmp_path)
        assert data is not None
        assert len(data["framer_messages"]) == 1
        assert data["framer_messages"][0]["role"] == "user"
        assert data["framer_messages"][0]["text"] == "I want cash deposits"

    def test_appends_framer_question_with_choices(self, tmp_path: Path) -> None:
        init_transcript(plan_id="msg-2", question="q", transcript_dir=tmp_path)
        append_framer_message(
            plan_id="msg-2",
            role="framer",
            text="What provider?",
            msg_id="1",
            choices=["Stripe", "PayPal", "Square"],
            transcript_dir=tmp_path,
        )
        data = load_transcript("msg-2", transcript_dir=tmp_path)
        assert data is not None
        msg = data["framer_messages"][0]
        assert msg["role"] == "framer"
        assert msg["msg_id"] == "1"
        assert msg["choices"] == ["Stripe", "PayPal", "Square"]

    def test_appends_multiple_messages_in_order(self, tmp_path: Path) -> None:
        init_transcript(plan_id="msg-3", question="q", transcript_dir=tmp_path)
        append_framer_message(
            plan_id="msg-3",
            role="user",
            text="first",
            transcript_dir=tmp_path,
        )
        append_framer_message(
            plan_id="msg-3",
            role="framer",
            text="second",
            msg_id="1",
            transcript_dir=tmp_path,
        )
        append_framer_message(
            plan_id="msg-3",
            role="user",
            text="third",
            msg_id="1",
            transcript_dir=tmp_path,
        )
        data = load_transcript("msg-3", transcript_dir=tmp_path)
        assert data is not None
        assert len(data["framer_messages"]) == 3
        assert [m["text"] for m in data["framer_messages"]] == [
            "first",
            "second",
            "third",
        ]

    def test_skips_if_transcript_missing(self, tmp_path: Path) -> None:
        """Appending to a non-existent transcript should not crash."""
        append_framer_message(
            plan_id="nonexistent",
            role="user",
            text="hello",
            transcript_dir=tmp_path,
        )
        # No exception raised, no file created
        assert not (tmp_path / "transcript-nonexistent.json").exists()

    def test_omits_optional_fields_when_none(self, tmp_path: Path) -> None:
        init_transcript(plan_id="msg-4", question="q", transcript_dir=tmp_path)
        append_framer_message(
            plan_id="msg-4",
            role="user",
            text="answer",
            transcript_dir=tmp_path,
        )
        data = load_transcript("msg-4", transcript_dir=tmp_path)
        assert data is not None
        msg = data["framer_messages"][0]
        assert "msg_id" not in msg
        assert "choices" not in msg


class TestSetFramedQuestion:
    def test_sets_framed_question(self, tmp_path: Path) -> None:
        init_transcript(plan_id="fq-1", question="q", transcript_dir=tmp_path)
        set_framed_question(
            plan_id="fq-1",
            framed_question="Build a cash deposit feature with Stripe",
            transcript_dir=tmp_path,
        )
        data = load_transcript("fq-1", transcript_dir=tmp_path)
        assert data is not None
        assert data["framed_question"] == "Build a cash deposit feature with Stripe"

    def test_overwrites_previous_framed_question(self, tmp_path: Path) -> None:
        init_transcript(plan_id="fq-2", question="q", transcript_dir=tmp_path)
        set_framed_question(
            plan_id="fq-2",
            framed_question="v1",
            transcript_dir=tmp_path,
        )
        set_framed_question(
            plan_id="fq-2",
            framed_question="v2",
            transcript_dir=tmp_path,
        )
        data = load_transcript("fq-2", transcript_dir=tmp_path)
        assert data is not None
        assert data["framed_question"] == "v2"

    def test_skips_if_transcript_missing(self, tmp_path: Path) -> None:
        set_framed_question(
            plan_id="nonexistent",
            framed_question="test",
            transcript_dir=tmp_path,
        )
        assert not (tmp_path / "transcript-nonexistent.json").exists()


class TestLoadTranscript:
    def test_loads_existing(self, tmp_path: Path) -> None:
        init_transcript(plan_id="ld-1", question="q", transcript_dir=tmp_path)
        data = load_transcript("ld-1", transcript_dir=tmp_path)
        assert data is not None
        assert data["plan_id"] == "ld-1"

    def test_returns_none_for_missing(self, tmp_path: Path) -> None:
        assert load_transcript("nope", transcript_dir=tmp_path) is None

    def test_returns_none_for_corrupt(self, tmp_path: Path) -> None:
        (tmp_path / "transcript-bad.json").write_text("not json{{{")
        assert load_transcript("bad", transcript_dir=tmp_path) is None


class TestFullConversationFlow:
    """Integration test: simulate a full framer conversation."""

    def test_full_flow(self, tmp_path: Path) -> None:
        plan_id = "flow-1"

        # 1. Init with original question
        init_transcript(
            plan_id=plan_id,
            question="Want to build a cash deposit feature",
            transcript_dir=tmp_path,
        )

        # 2. Record original user message
        append_framer_message(
            plan_id=plan_id,
            role="user",
            text="Want to build a cash deposit feature",
            transcript_dir=tmp_path,
        )

        # 3. Framer asks clarification
        append_framer_message(
            plan_id=plan_id,
            role="framer",
            text="What payment provider should we integrate with?",
            msg_id="1",
            choices=["Stripe", "PayPal", "Square"],
            transcript_dir=tmp_path,
        )

        # 4. User answers
        append_framer_message(
            plan_id=plan_id,
            role="user",
            text="Stripe",
            msg_id="1",
            transcript_dir=tmp_path,
        )

        # 5. Framer asks another question
        append_framer_message(
            plan_id=plan_id,
            role="framer",
            text="What currencies do you need to support?",
            msg_id="2",
            transcript_dir=tmp_path,
        )

        # 6. User answers
        append_framer_message(
            plan_id=plan_id,
            role="user",
            text="USD and EUR",
            msg_id="2",
            transcript_dir=tmp_path,
        )

        # 7. Framer produces final requirement
        append_framer_message(
            plan_id=plan_id,
            role="framer",
            text="[FRAMED] Cash deposit feature with Stripe in USD/EUR",
            transcript_dir=tmp_path,
        )
        set_framed_question(
            plan_id=plan_id,
            framed_question="Build cash deposit feature using Stripe supporting USD and EUR",
            transcript_dir=tmp_path,
        )

        # Verify the full transcript
        data = load_transcript(plan_id, transcript_dir=tmp_path)
        assert data is not None
        assert data["question"] == "Want to build a cash deposit feature"
        assert len(data["framer_messages"]) == 6
        assert data["framed_question"] == (
            "Build cash deposit feature using Stripe supporting USD and EUR"
        )

        # Verify message ordering and structure
        roles = [m["role"] for m in data["framer_messages"]]
        assert roles == [
            "user",
            "framer",
            "user",
            "framer",
            "user",
            "framer",
        ]
