"""Model-owned, revisable research plan for one fixed debate position."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ResearchPlan:
    """A public decision record, not a hard-coded workflow or raw chain of thought."""

    plan_id: str
    phase: str = ""
    version: int = 1
    question_interpretation: str = ""
    winning_condition: str = ""
    strategy: str = ""
    route_hypotheses: list[str] = field(default_factory=list)
    next_actions: list[dict] = field(default_factory=list)
    stopping_conditions: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    abandoned: list[str] = field(default_factory=list)
    remaining_work: str = ""
    progress_assessment: str = ""
    estimated_remaining_actions: int = -1
    status: str = "active"
    change_reason: str = ""

    def missing_fields(self) -> list[str]:
        missing = []
        for name in ("phase", "question_interpretation", "winning_condition", "strategy"):
            if not str(getattr(self, name, "")).strip():
                missing.append(name)
        if not self.next_actions and self.status != "ready_to_conclude":
            missing.append("next_actions")
        if not self.stopping_conditions:
            missing.append("stopping_conditions")
        return missing
