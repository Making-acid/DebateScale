"""LLM port: the one place the engine talks to a model.

The engine only needs a single atomic capability: run one inference turn, possibly
returning tool calls. Everything else (which tools, which engine action) is the
engine's job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMTurn:
    """One model turn: text and/or requested tool calls, plus usage."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: LLMUsage = field(default_factory=LLMUsage)
    # Opaque assistant fields that a provider requires on the next turn, such as
    # DeepSeek's reasoning_content. Runtime preserves them without interpreting.
    continuation: dict[str, Any] = field(default_factory=dict)


class LLMPort(Protocol):
    """A single inference turn against some model provider.

    ``messages`` follows the OpenAI-compatible shape (``{"role", "content", ...}``).
    ``tools`` is an optional list of OpenAI-format function schemas. The model may
    answer with text, tool calls, or both.
    """

    async def run(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> LLMTurn: ...
