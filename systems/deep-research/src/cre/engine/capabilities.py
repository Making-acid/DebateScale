"""Machine-readable description of the capabilities attached to an engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..ports.search import SearchPort
from ..ports.store import StorePort
from ..ports.tools import ToolPort
from ..ports.transcription import TranscriptionPort


@dataclass(frozen=True)
class EngineCapabilities:
    """Stable capability manifest that a UI, CLI, or plugin host can inspect."""

    contract_version: str = "2"
    dual_position_research: bool = True
    model_owned_dynamic_planning: bool = True
    durable_checkpoints: bool = False
    web_search: bool = False
    source_reading: bool = False
    audio_transcription: bool = False
    external_tools: tuple[str, ...] = ()
    research_profiles: tuple[str, ...] = ("standard", "deep")
    output_formats: tuple[str, ...] = ("structured",)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def deep_research_gaps(self) -> list[str]:
        gaps = []
        if not self.web_search:
            gaps.append("web_search")
        if not self.source_reading:
            gaps.append("source_reading")
        if not self.durable_checkpoints:
            gaps.append("durable_checkpoints")
        return gaps


def inspect_capabilities(
    store: StorePort, search: SearchPort | None, tools: ToolPort | None,
    transcriber: TranscriptionPort | None = None,
) -> EngineCapabilities:
    external: list[str] = []
    if tools is not None:
        for item in tools.list_tools():
            function = item.get("function", {})
            name = function.get("name")
            if isinstance(name, str) and name:
                external.append(name)
    return EngineCapabilities(
        durable_checkpoints=bool(getattr(store, "durable", False)),
        web_search=search is not None,
        source_reading=search is not None and callable(getattr(search, "read", None)),
        audio_transcription=transcriber is not None,
        external_tools=tuple(dict.fromkeys(external)),
    )
