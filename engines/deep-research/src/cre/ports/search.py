"""Search port: internet search, the primary source of new material."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class SearchResult:
    title: str = ""
    url: str = ""
    snippet: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceDocument:
    """A fetched source body, distinct from a search-result lead."""

    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class SearchPort(Protocol):
    async def search(self, query: str, n: int = 10) -> list[SearchResult]: ...

    # Optional at runtime for backward compatibility. Production Deep Research
    # adapters should implement it; without source reading, evidence cannot pass
    # the default investigation floor.
    async def read(self, url: str) -> SourceDocument: ...
