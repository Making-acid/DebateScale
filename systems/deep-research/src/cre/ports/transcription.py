"""Port for turning selected audio/video material into inspectable text."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str
    speaker: str = ""


@dataclass
class TranscriptDocument:
    content: str = ""
    segments: list[TranscriptSegment] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class TranscriptionPort(Protocol):
    def supports(self, url: str) -> bool: ...

    async def transcribe(
        self, url: str, *, language: str = "", max_duration_seconds: int = 7200
    ) -> TranscriptDocument: ...
