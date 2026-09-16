"""Source: a piece of raw material in the shared Source Pool."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .common import Party


@dataclass
class Source:
    """Shared raw material. Sources are shared; interpretations are not."""

    source_id: str
    url: str = ""
    title: str = ""
    content: str = field(default="")
    metadata: dict[str, Any] = field(default_factory=dict)
    discovered_by: Optional[Party] = None
    investigated_by: list[Party] = field(default_factory=list)
    source_type: str = ""
    is_primary: Optional[bool] = None
