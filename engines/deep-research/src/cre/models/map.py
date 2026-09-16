"""Research Map entry: the future-facing view of "what's left to study"."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .common import MapStatus


@dataclass
class ResearchMapEntry:
    """A direction / open question in the research space.

    ``importance`` / ``coverage`` / ``uncertainty`` are **Agent-facing metadata**:
    the runtime stores and forwards them but must never write semantic rules
    against them.
    """

    map_id: str
    title: str
    status: MapStatus = MapStatus.ACTIVE
    importance: Optional[str] = None
    coverage: Optional[str] = None
    uncertainty: Optional[str] = None
    note: str = field(default="")
    proof_obligation: str = field(default="")
    externally_blocked: bool = False
    blocker_reason: str = field(default="")
