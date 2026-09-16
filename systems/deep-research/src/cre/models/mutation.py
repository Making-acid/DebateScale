"""Mutation: the append-only event log, the engine's source of truth."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .common import EngineAction, Party, TargetRef


@dataclass
class Mutation:
    """One persistent-state change.

    The mutation log is the source of truth: Blackboard files, the Semantic Diff,
    and the Issue Archive are all projections of it. ``what_changed`` + ``why``
    carry the semantic diff (the cognitive version history), while Git carries the
    literal text history.
    """

    mutation_id: str
    seq: int
    session_id: str
    pass_no: int
    agent: Party
    action: EngineAction
    what_changed: str = ""
    why: str = ""
    target: Optional[TargetRef] = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
