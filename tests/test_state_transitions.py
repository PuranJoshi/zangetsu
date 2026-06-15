"""Tests for plan state transitions -- the rules of the state machine.

The state machine enforces the lifecycle:
    framing -> drafting -> proposed -> reviewing -> agreed -> executing -> completed

Key rules tested here:
    - Plans start in FRAMING (the requirements gate)
    - Can't skip states (must go through each step in order)
    - REVIEWING is the branching point (can go to 4 different states)
    - COMPLETED is terminal (no way out)
    - REJECTED and STALLED can restart to FRAMING

Python lesson: pytest.raises
    `with pytest.raises(ValueError, match="Invalid"):` is a context manager.
    It catches the exception and checks:
    1. The exception type matches (ValueError)
    2. The message matches the regex ("Invalid")
    If the code inside does NOT raise, the test fails.
"""

import pytest

from code_council.state import PlanState, PlanStatus


class TestHappyPath:
    """The normal path through the state machine."""

    def test_initial_state_is_framing(self) -> None:
        state = PlanState(plan_id="test")
        assert state.status == PlanStatus.FRAMING

    def test_framing_to_drafting(self) -> None:
        state = PlanState(plan_id="test")
        state.transition(PlanStatus.DRAFTING)
        assert state.status == PlanStatus.DRAFTING

    def test_full_lifecycle(self) -> None:
        """framing -> drafting -> proposed -> reviewing -> agreed
        -> executing -> completed"""
        state = PlanState(plan_id="test")
        state.transition(PlanStatus.DRAFTING)
        state.transition(PlanStatus.PROPOSED)
        state.transition(PlanStatus.REVIEWING)
        state.transition(PlanStatus.AGREED)
        state.transition(PlanStatus.EXECUTING)
        state.transition(PlanStatus.COMPLETED)
        assert state.status == PlanStatus.COMPLETED


class TestInvalidTransitions:
    """Transitions that must be rejected."""

    def test_cannot_skip_framing_to_proposed(self) -> None:
        state = PlanState(plan_id="test")
        with pytest.raises(ValueError, match="Invalid transition"):
            state.transition(PlanStatus.PROPOSED)

    def test_cannot_skip_framing_to_agreed(self) -> None:
        state = PlanState(plan_id="test")
        with pytest.raises(ValueError, match="Invalid transition"):
            state.transition(PlanStatus.AGREED)

    def test_cannot_skip_drafting_to_reviewing(self) -> None:
        state = PlanState(plan_id="test")
        state.transition(PlanStatus.DRAFTING)
        with pytest.raises(ValueError, match="Invalid transition"):
            state.transition(PlanStatus.REVIEWING)

    def test_completed_cannot_restart_to_framing(self) -> None:
        state = PlanState(plan_id="test")
        for s in [
            PlanStatus.DRAFTING, PlanStatus.PROPOSED, PlanStatus.REVIEWING,
            PlanStatus.AGREED, PlanStatus.EXECUTING, PlanStatus.COMPLETED,
        ]:
            state.transition(s)
        with pytest.raises(ValueError, match="Invalid transition"):
            state.transition(PlanStatus.FRAMING)


class TestReviewingBranches:
    """REVIEWING is where the plan can branch in 4 directions."""

    def _get_to_reviewing(self) -> PlanState:
        """Helper to advance a plan to REVIEWING state."""
        state = PlanState(plan_id="test")
        state.transition(PlanStatus.DRAFTING)
        state.transition(PlanStatus.PROPOSED)
        state.transition(PlanStatus.REVIEWING)
        return state

    def test_can_agree(self) -> None:
        state = self._get_to_reviewing()
        state.transition(PlanStatus.AGREED)
        assert state.status == PlanStatus.AGREED

    def test_can_send_back_to_drafting(self) -> None:
        state = self._get_to_reviewing()
        state.transition(PlanStatus.DRAFTING)
        assert state.status == PlanStatus.DRAFTING

    def test_can_reject(self) -> None:
        state = self._get_to_reviewing()
        state.transition(PlanStatus.REJECTED)
        assert state.status == PlanStatus.REJECTED

    def test_can_stall(self) -> None:
        state = self._get_to_reviewing()
        state.transition(PlanStatus.STALLED)
        assert state.status == PlanStatus.STALLED


class TestCouncilReview:
    """COMPLETED plans can be council-reviewed, producing a revised plan."""

    def _get_to_completed(self) -> PlanState:
        """Helper to advance a plan to COMPLETED state."""
        state = PlanState(plan_id="test")
        for s in [
            PlanStatus.DRAFTING, PlanStatus.PROPOSED, PlanStatus.REVIEWING,
            PlanStatus.AGREED, PlanStatus.EXECUTING, PlanStatus.COMPLETED,
        ]:
            state.transition(s)
        return state

    def test_completed_to_council_reviewed(self) -> None:
        state = self._get_to_completed()
        state.transition(PlanStatus.COUNCIL_REVIEWED)
        assert state.status == PlanStatus.COUNCIL_REVIEWED

    def test_council_reviewed_can_proceed_to_executing(self) -> None:
        state = self._get_to_completed()
        state.transition(PlanStatus.COUNCIL_REVIEWED)
        state.transition(PlanStatus.EXECUTING)
        assert state.status == PlanStatus.EXECUTING

    def test_council_reviewed_can_go_back_to_reviewing(self) -> None:
        state = self._get_to_completed()
        state.transition(PlanStatus.COUNCIL_REVIEWED)
        state.transition(PlanStatus.REVIEWING)
        assert state.status == PlanStatus.REVIEWING

    def test_council_reviewed_cannot_skip_to_framing(self) -> None:
        state = self._get_to_completed()
        state.transition(PlanStatus.COUNCIL_REVIEWED)
        with pytest.raises(ValueError, match="Invalid transition"):
            state.transition(PlanStatus.FRAMING)


class TestRecovery:
    """REJECTED and STALLED plans can restart from scratch."""

    def test_rejected_restarts_to_framing(self) -> None:
        state = PlanState(plan_id="test")
        state.transition(PlanStatus.DRAFTING)
        state.transition(PlanStatus.PROPOSED)
        state.transition(PlanStatus.REVIEWING)
        state.transition(PlanStatus.REJECTED)
        state.transition(PlanStatus.FRAMING)
        assert state.status == PlanStatus.FRAMING

    def test_stalled_restarts_to_framing(self) -> None:
        state = PlanState(plan_id="test")
        state.transition(PlanStatus.DRAFTING)
        state.transition(PlanStatus.PROPOSED)
        state.transition(PlanStatus.REVIEWING)
        state.transition(PlanStatus.STALLED)
        state.transition(PlanStatus.FRAMING)
        assert state.status == PlanStatus.FRAMING
