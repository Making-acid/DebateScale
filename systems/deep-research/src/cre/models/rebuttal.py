"""Rebuttals aimed at exact opponent arguments and revisions."""

from __future__ import annotations

from dataclasses import dataclass, field

from .common import Party, RebuttalStatus


@dataclass
class Rebuttal:
    rebuttal_id: str
    target_agent: Party
    target_argument_id: str
    target_version: int
    title: str = ""
    reconstruction: str = ""
    attack_type: str = ""
    attack: str = ""
    why_it_matters: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    likely_response: str = ""
    current_effect: str = ""
    status: RebuttalStatus = RebuttalStatus.ACTIVE

    def missing_fields(self) -> list[str]:
        return [
            name
            for name in ("title", "reconstruction", "attack_type", "attack", "why_it_matters")
            if not getattr(self, name).strip()
        ]
