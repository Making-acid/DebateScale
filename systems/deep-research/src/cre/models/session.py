"""ResearchSession: the durable state of one continuous research run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .common import Party, SessionStatus


@dataclass
class ResearchBudget:
    """Hard caps enforced by the runtime (Pass-internal).

    These are mechanical ceilings to prevent runaway research. The agent decides
    *when* to conclude within these caps (soft convergence).
    """

    max_tool_calls_per_pass: int = 50
    # Transport/search failures have their own bounded cushion. A failed page read
    # should not consume the same allowance as a useful inspected source, but it
    # must still be capped to prevent an endless retry loop.
    max_failed_tool_calls_per_pass: int = 16
    max_parallel_research_actions_per_turn: int = 4
    max_tokens_per_pass: int = 200_000
    # Some compatible providers omit usage data. This independent ceiling keeps
    # an unstructured/text-only model response from creating an endless pass.
    max_model_turns_per_pass: int = 120
    # Behavioral circuit breakers stop repeated deliberation without case progress.
    max_unproductive_turns_per_pass: int = 7
    max_tokens_without_state_progress: int = 70_000
    min_token_reserve_per_model_turn: int = 12_000
    # Scripted fixtures may disable this; production profiles keep it enabled.
    argument_first_gate: bool = True
    max_passes: Optional[int] = None
    max_cycles: Optional[int] = None
    # Minimum completion floor for a production-strength Pass One. Tests and
    # deliberately small demos may lower these explicitly; a real run should not.
    min_sources_per_agent: int = 24
    min_examined_sources_per_agent: int = 12
    min_core_arguments_per_agent: int = 3
    min_rebuttals_per_agent: int = 2


@dataclass
class ResearchSession:
    """The engine's durable unit: one research question and its evolution."""

    session_id: str
    question: str
    profile: str = "deep"
    position_a: str = ""
    position_b: str = ""
    status: SessionStatus = SessionStatus.CREATED
    agents: list[Party] = field(default_factory=lambda: [Party.A, Party.B])
    current_cycle: int = 0
    next_agent: Party = Party.A
    # Durable per-phase commits. A host may restart the process after one party
    # finishes; Runtime resumes only the missing party instead of repeating work.
    phase_progress: dict[str, list[str]] = field(default_factory=dict)
    # Durable protocol attempts which must survive an empty search result and a
    # host restart.  Values are party ids, keyed by the attempted obligation.
    protocol_attempts: dict[str, list[str]] = field(default_factory=dict)
    budget: ResearchBudget = field(default_factory=ResearchBudget)
    created_at: str = ""
    updated_at: str = ""

    def position_for(self, agent: Party) -> str:
        """Return the standpoint assigned to an agent.

        A debate position is an input to research, not a conclusion the agent is
        free to abandon.  Defaults keep non-debate demos backwards compatible.
        """

        if agent is Party.A:
            return self.position_a or f"Support the proposition: {self.question}"
        if agent is Party.B:
            return self.position_b or f"Oppose the proposition: {self.question}"
        return "Human reviewer"
