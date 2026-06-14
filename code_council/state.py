"""Plan state machine.

Manages the lifecycle of a change plan through its stages:
  framing -> drafting -> proposed -> reviewing -> agreed -> executing -> completed

Also supports: rejected (terminal), stalled (needs human intervention).

The FRAMING state is the requirements gate. The Framer must produce clear,
unambiguous requirements before any technical advisor runs. This prevents
the council from deliberating on poorly defined work.

Why a state machine?
    Without explicit states and transition rules, nothing stops the system
    from executing a plan that was never reviewed, or running advisors on
    vague requirements. The state machine makes illegal states unrepresentable.

Why str + Enum?
    PlanStatus inherits from both str and Enum. This means each value is a
    real string -- PlanStatus.FRAMING == "framing" is True. This makes JSON
    serialization trivial (no custom encoder needed) while still giving us
    the safety of an enum (typos caught at definition time, IDE autocomplete).
"""

from __future__ import annotations

import logging
from enum import Enum

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class PlanStatus(str, Enum):
    """Valid plan states.

    The lifecycle flows left to right:
        FRAMING -> DRAFTING -> PROPOSED -> REVIEWING -> AGREED -> EXECUTING -> COMPLETED

    REVIEWING can also branch to DRAFTING (re-plan), REJECTED, or STALLED.
    REJECTED and STALLED can restart to FRAMING.
    """

    FRAMING = "framing"         # Framer is defining requirements
    DRAFTING = "drafting"       # Advisors are running, plan not yet ready
    PROPOSED = "proposed"       # Plan synthesized, waiting for AI tool review
    REVIEWING = "reviewing"     # AI tool is reviewing the plan
    AGREED = "agreed"           # Both council and AI tool agree on the plan
    EXECUTING = "executing"     # AI tool is implementing the plan
    COMPLETED = "completed"     # Implementation finished
    REJECTED = "rejected"       # AI tool rejected and max rounds exceeded
    STALLED = "stalled"         # Needs human intervention


# Valid transitions: from_state -> set of allowed to_states.
#
# This dict IS the state machine. If a transition isn't listed here,
# it's illegal. Read it as: "from this state, you can go to these states."
VALID_TRANSITIONS: dict[PlanStatus, set[PlanStatus]] = {
    PlanStatus.FRAMING:   {PlanStatus.DRAFTING},
    PlanStatus.DRAFTING:  {PlanStatus.PROPOSED},
    PlanStatus.PROPOSED:  {PlanStatus.REVIEWING},
    PlanStatus.REVIEWING: {
        PlanStatus.AGREED,
        PlanStatus.DRAFTING,
        PlanStatus.FRAMING,
        PlanStatus.REJECTED,
        PlanStatus.STALLED,
    },
    PlanStatus.AGREED:    {PlanStatus.EXECUTING},
    PlanStatus.EXECUTING: {PlanStatus.COMPLETED},
    PlanStatus.COMPLETED: set(),                     # terminal -- nowhere to go
    PlanStatus.REJECTED:  {PlanStatus.FRAMING},      # can restart from scratch
    PlanStatus.STALLED:   {PlanStatus.FRAMING},      # can restart from scratch
}


class NegotiationRound(BaseModel):
    """Record of a single negotiation round.

    Pydantic BaseModel gives us:
    - Automatic type validation (concerns must be list[str], etc.)
    - .model_dump() for JSON serialization
    - Immutable-by-default fields (safer than plain dicts)
    """

    round_number: int
    concerns: list[str]
    suggestions: list[str]
    plan_changes_made: list[str]


class PlanState(BaseModel):
    """Tracks the current state and history of a plan.

    This is the runtime state object. It's created when a plan starts
    (via bankai) and updated as the plan moves through its lifecycle.

    Attributes:
        plan_id: Unique identifier for this plan.
        status: Current state in the lifecycle (starts at FRAMING).
        negotiation_round: How many negotiation rounds have happened.
        max_rounds: Maximum allowed negotiation rounds before stalling.
        negotiation_history: Full record of each negotiation round.
        error_message: Set when something goes wrong (for debugging).
    """

    plan_id: str
    status: PlanStatus = PlanStatus.FRAMING
    negotiation_round: int = 0
    max_rounds: int = 3
    negotiation_history: list[NegotiationRound] = []
    error_message: str = ""

    def transition(self, new_status: PlanStatus) -> None:
        """Transition to a new status.

        Raises ValueError if the transition is not allowed by the state
        machine. This is the core enforcement mechanism -- it makes
        illegal state transitions impossible at runtime.
        """
        allowed = VALID_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid transition: {self.status.value} -> {new_status.value}. "
                f"Valid targets: {[s.value for s in allowed]}"
            )
        logger.info(
            "Plan %s: %s -> %s", self.plan_id, self.status.value, new_status.value
        )
        self.status = new_status

    def can_negotiate(self) -> bool:
        """Check if another negotiation round is allowed."""
        return self.negotiation_round < self.max_rounds

    def record_negotiation(
        self,
        concerns: list[str],
        suggestions: list[str],
        plan_changes: list[str],
    ) -> None:
        """Record a completed negotiation round.

        This is called after a negotiation round completes -- the advisors
        re-ran with the AI tool's feedback, and the synthesizer produced
        an updated plan. We record what happened for audit purposes.
        """
        self.negotiation_round += 1
        self.negotiation_history.append(
            NegotiationRound(
                round_number=self.negotiation_round,
                concerns=concerns,
                suggestions=suggestions,
                plan_changes_made=plan_changes,
            )
        )
