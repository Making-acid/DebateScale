"""Shared enums and small value types for the CRE data model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Party(str, Enum):
    """An actor that can own state or file an issue."""

    A = "A"
    B = "B"
    HUMAN = "H"


class UnitStatus(str, Enum):
    TENTATIVE = "tentative"
    STABLE = "stable"


class ArgumentStatus(str, Enum):
    """Whether a position argument is still being built or can carry a case."""

    DRAFT = "draft"
    DEFENSIBLE = "defensible"
    WITHDRAWN = "withdrawn"


class RebuttalStatus(str, Enum):
    """Lifecycle of a rebuttal against a specific argument revision."""

    ACTIVE = "active"
    ANSWERED = "answered"
    SURVIVES = "survives"
    WITHDRAWN = "withdrawn"


class EvidenceStatus(str, Enum):
    """The research depth reached for a source-backed evidence claim."""

    EXAMINED = "examined"
    ADMITTED = "admitted"
    REJECTED = "rejected"


class MapStatus(str, Enum):
    ACTIVE = "active"
    DORMANT = "dormant"
    RESOLVED = "resolved"


class IssueState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class IssueResolution(str, Enum):
    RESOLVED = "resolved"
    WITHDRAWN = "withdrawn"
    CLARIFIED = "clarified"
    UNRESOLVED = "unresolved"
    DISAGREEMENT = "disagreement"
    SUPERSEDED = "superseded"


class TargetType(str, Enum):
    PLAN = "plan"
    UNIT = "unit"
    MAP = "map"
    SOURCE = "source"
    ISSUE = "issue"
    BLACKBOARD = "blackboard"
    ARGUMENT = "argument"
    REBUTTAL = "rebuttal"
    EVIDENCE = "evidence"


class EngineAction(str, Enum):
    """The six persistent-state actions. Tool calls are NOT engine actions."""

    UPDATE_PLAN = "update_plan"
    UPDATE_UNIT = "update_unit"
    UPDATE_MAP = "update_map"
    CREATE_ISSUE = "create_issue"
    RESPOND_ISSUE = "respond_issue"
    CLOSE_ISSUE = "close_issue"
    CONCLUDE_PASS = "conclude_pass"
    UPDATE_ARGUMENT = "update_argument"
    UPDATE_REBUTTAL = "update_rebuttal"
    RECORD_EVIDENCE = "record_evidence"


class SessionStatus(str, Enum):
    CREATED = "created"
    EXPANSION = "expansion"
    COLLISION = "collision"
    CONTINUOUS = "continuous"
    CANDIDATE_STABLE = "candidate_stable"
    STABILITY_CHECK = "stability_check"
    STABLE_FOR_REVIEW = "stable_for_review"
    HUMAN_REVIEW = "human_review"
    SNAPSHOT = "snapshot"


@dataclass(frozen=True)
class TargetRef:
    """A polymorphic reference to an entity, possibly a section inside it."""

    type: TargetType
    id: str
    section: Optional[str] = None
