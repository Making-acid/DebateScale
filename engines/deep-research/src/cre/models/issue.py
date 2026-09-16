"""Issue: the cross-review protocol between the two research agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .common import IssueResolution, IssueState, Party, TargetRef


@dataclass
class Issue:
    """A work order between parties (A/B/H).

    Lifecycle (``state``) is separate from outcome (``resolution``):
    ``state=closed`` + ``resolution=disagreement`` means the issue no longer needs
    work, but the parties did not converge.
    """

    issue_id: str
    from_agent: Party
    to_agent: Party
    target: TargetRef
    priority: str
    title: str = ""
    body: str = field(default="")
    state: IssueState = IssueState.OPEN
    resolution: Optional[IssueResolution] = None
