"""Structured position arguments: the primary product of the engine."""

from __future__ import annotations

from dataclasses import dataclass, field

from .common import ArgumentStatus


@dataclass
class Argument:
    """A debate-ready proof structure, not a prose speech.

    ``warrant`` stores the inferential steps between claim and impact. Evidence
    records bind inspected sources to a specific step. ``version`` increments on
    every update so historical rebuttals keep their original context.
    """

    argument_id: str
    title: str = ""
    claim: str = ""
    burden: str = ""
    criterion: str = ""
    warrant: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    # Search material that helped discover, sharpen, or stress-test the argument
    # (for example a prior debate, forum objection, analogy, or judge comment).
    # Unlike evidence_ids, these sources do not certify a factual premise.
    material_source_ids: list[str] = field(default_factory=list)
    # reasoning: the claim stands on definitions, warrants, counterexamples,
    # analogies or value judgment; mixed/empirical: at least one load-bearing
    # factual premise must be checked against external material.
    support_type: str = "mixed"
    evidence_need: list[str] = field(default_factory=list)
    impact: str = ""
    scope: str = ""
    # The model's own contribution beyond repeating a stock case: a new link,
    # comparison, boundary, framing, counterexample, or defensive repair. This
    # is an argumentative claim to be tested, not a claim of historical novelty.
    original_contribution: str = ""
    vulnerabilities: list[str] = field(default_factory=list)
    defense: list[str] = field(default_factory=list)
    status: ArgumentStatus = ArgumentStatus.DRAFT
    version: int = 1

    def missing_proof_fields(self) -> list[str]:
        missing: list[str] = []
        for name in ("title", "claim", "burden", "impact", "scope"):
            if not getattr(self, name).strip():
                missing.append(name)
        if len(self.warrant) < 2:
            missing.append("warrant(>=2 steps)")
        if self.support_type not in {"reasoning", "mixed", "empirical"}:
            missing.append("support_type")
        if self.support_type in {"mixed", "empirical"} and not self.evidence_ids:
            missing.append("evidence_ids")
        return missing
