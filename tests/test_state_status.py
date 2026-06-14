"""Tests for PlanStatus enum -- the valid states a plan can be in.

Python lesson: str + Enum
    PlanStatus(str, Enum) means each member IS a string.
    So PlanStatus.FRAMING == "framing" is True.
    This matters for JSON -- when you serialize a PlanState to JSON,
    the status field becomes a plain string automatically.
    Without the str mixin, you'd get <PlanStatus.FRAMING: 'framing'>.
"""

from code_council.state import PlanStatus


class TestPlanStatus:
    def test_framing_status_exists(self) -> None:
        """FRAMING is the first state -- requirements definition phase."""
        assert PlanStatus.FRAMING == "framing"

    def test_all_statuses_defined(self) -> None:
        """All 9 states should be defined. If you add a new state,
        add it to this set -- the test will remind you."""
        expected = {
            "framing", "drafting", "proposed", "reviewing",
            "agreed", "executing", "completed", "rejected", "stalled",
        }
        actual = {s.value for s in PlanStatus}
        assert actual == expected

    def test_status_is_string(self) -> None:
        """Each status value should be usable as a plain string.
        This is the str + Enum trick -- no custom serializer needed.

        Note: In Python 3.11+, f-strings use __format__ which shows the
        enum name (PlanStatus.FRAMING). Use .value to get the plain string.
        But equality with plain strings still works because of the str mixin.
        """
        assert isinstance(PlanStatus.FRAMING, str)
        assert PlanStatus.FRAMING == "framing"  # equality works
        assert PlanStatus.FRAMING.value == "framing"  # .value is explicit
