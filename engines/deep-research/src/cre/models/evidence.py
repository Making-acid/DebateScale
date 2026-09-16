"""Agent-owned interpretation of an inspected source."""

from __future__ import annotations

from dataclasses import dataclass

from .common import EvidenceStatus


@dataclass
class EvidenceRecord:
    evidence_id: str
    source_id: str
    argument_id: str = ""
    proposition: str = ""
    finding: str = ""
    method: str = ""
    limitations: str = ""
    relation: str = "supports"
    provenance: str = ""
    status: EvidenceStatus = EvidenceStatus.EXAMINED
