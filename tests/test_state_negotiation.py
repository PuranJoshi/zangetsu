"""Tests for negotiation tracking on PlanState.

Negotiation is the back-and-forth between the council and the AI tool.
If the AI tool says "this plan is infeasible", the council re-runs
advisors with the feedback and tries again -- up to max_rounds times.

Python lesson: Pydantic default_factory
    In PlanState, `negotiation_history: list[NegotiationRound] = []`
    Pydantic handles mutable defaults safely -- each instance gets
    its own list. In plain Python classes you'd need
    `field(default_factory=list)` to avoid the shared-mutable-default bug.
"""

from code_council.state import PlanState


class TestCanNegotiate:
    def test_can_negotiate_when_under_max(self) -> None:
        state = PlanState(plan_id="test", max_rounds=3)
        assert state.can_negotiate()

    def test_cannot_negotiate_at_max(self) -> None:
        state = PlanState(plan_id="test", max_rounds=1)
        state.record_negotiation(["concern"], ["suggestion"], ["changed X"])
        assert not state.can_negotiate()

    def test_can_negotiate_boundary(self) -> None:
        """At max_rounds=2, can negotiate after 1 round but not after 2."""
        state = PlanState(plan_id="test", max_rounds=2)
        state.record_negotiation(["c1"], ["s1"], ["p1"])
        assert state.can_negotiate()  # round 1 of 2 -- still room
        state.record_negotiation(["c2"], ["s2"], ["p2"])
        assert not state.can_negotiate()  # round 2 of 2 -- done


class TestRecordNegotiation:
    def test_increments_round(self) -> None:
        state = PlanState(plan_id="test")
        assert state.negotiation_round == 0
        state.record_negotiation(["c1"], ["s1"], ["p1"])
        assert state.negotiation_round == 1

    def test_appends_to_history(self) -> None:
        state = PlanState(plan_id="test")
        state.record_negotiation(["c1"], ["s1"], ["p1"])
        assert len(state.negotiation_history) == 1

    def test_history_preserves_data(self) -> None:
        state = PlanState(plan_id="test")
        state.record_negotiation(["concern A"], ["suggest B"], ["changed C"])
        entry = state.negotiation_history[0]
        assert entry.round_number == 1
        assert entry.concerns == ["concern A"]
        assert entry.suggestions == ["suggest B"]
        assert entry.plan_changes_made == ["changed C"]

    def test_multiple_rounds_tracked(self) -> None:
        state = PlanState(plan_id="test")
        state.record_negotiation(["c1"], ["s1"], ["p1"])
        state.record_negotiation(["c2"], ["s2"], ["p2"])
        assert state.negotiation_round == 2
        assert len(state.negotiation_history) == 2
        assert state.negotiation_history[0].round_number == 1
        assert state.negotiation_history[1].round_number == 2
