"""Tool port: general-purpose tools the agent uses freely inside a Pass.

Unlike search (a dedicated port), this covers browsing/reading pages, code, MCP,
and any other data source. A Tool is a Pass-internal capability, NOT an engine
action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolResult:
    ok: bool = True
    content: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolPort(Protocol):
    """A registry of Pass-internal tools, callable by name.

    ``list_tools`` returns OpenAI-format function schemas so the engine can offer
    them to the model. ``call`` executes one tool.
    """

    def list_tools(self) -> list[dict[str, Any]]: ...

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolResult: ...
