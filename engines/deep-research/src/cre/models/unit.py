"""Research Unit: the medium-grained unit of "what I currently know/think"."""

from __future__ import annotations

from dataclasses import dataclass, field

from .common import UnitStatus


@dataclass
class ResearchUnit:
    """A self-contained chunk of cognition.

    ``unit_id`` is immutable (e.g. ``ru_a_0017``). The file backing a unit may be
    renamed freely; issues reference ``unit_id``, never a path.

    Control fields (unit_id / status / source_ids) live in frontmatter; the
    cognitive content lives in ``content`` (Markdown body).
    """

    unit_id: str
    status: UnitStatus = UnitStatus.TENTATIVE
    source_ids: list[str] = field(default_factory=list)
    content: str = ""
