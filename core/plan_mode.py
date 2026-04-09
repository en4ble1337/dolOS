"""Plan Mode state container (Gap 3).

When active, the agent proposes a numbered plan instead of executing tools.
The pending plan is stored here until ``/approve`` sends each step for execution.

Usage
-----
    from core.plan_mode import PlanModeState

    plan_state = PlanModeState()
    plan_state.enter()          # activate plan mode
    plan_state.store_plan([...])# called by agent after parsing LLM response
    plan_state.pending_plan     # list of step strings
    plan_state.exit()           # deactivate and clear
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlanModeState:
    """Tracks the agent's plan mode lifecycle.

    Attributes:
        active:       True while the agent is in plan-proposal mode.
        pending_plan: Ordered list of step strings produced by the LLM,
                      waiting for ``/approve`` to execute them.
    """

    active: bool = False
    pending_plan: list[str] = field(default_factory=list)

    def enter(self) -> None:
        """Activate plan mode and reset any existing pending plan."""
        self.active = True
        self.pending_plan = []

    def exit(self) -> None:
        """Deactivate plan mode and clear the pending plan."""
        self.active = False
        self.pending_plan = []

    def store_plan(self, steps: list[str]) -> None:
        """Store parsed plan steps.

        Args:
            steps: Ordered list of step descriptions extracted from the LLM
                   response (typically parsed from numbered list lines).
        """
        self.pending_plan = list(steps)
