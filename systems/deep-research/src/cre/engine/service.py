"""Stable, UI-independent facade for Continuous Research Engine."""

from __future__ import annotations

import uuid
import copy
from dataclasses import dataclass
from typing import Callable, Optional

from ..models import ResearchBudget, ResearchSession, SessionStatus
from ..ports.llm import LLMPort
from ..ports.search import SearchPort
from ..ports.store import StorePort
from ..ports.tools import ToolPort
from ..ports.transcription import TranscriptionPort
from .mutation_log import now_iso
from .runtime import Runtime
from .capabilities import EngineCapabilities, inspect_capabilities
from .profiles import research_policy


@dataclass(frozen=True)
class ResearchRequest:
    question: str
    position_a: str = ""
    position_b: str = ""
    profile: str = "deep"
    session_id: str = ""


def research_budget(profile: str) -> ResearchBudget:
    # A session owns its budget snapshot; callers must never mutate the shared
    # immutable profile definition through a returned dataclass.
    return copy.deepcopy(research_policy(profile).budget)


class ResearchEngine:
    """Complete orchestration entry point shared by every host and frontend."""

    def __init__(self, *, store: StorePort, llm_a: LLMPort, llm_b: LLMPort,
                 search: Optional[SearchPort] = None, tools: Optional[ToolPort] = None,
                 transcriber: Optional[TranscriptionPort] = None,
                 progress_callback: Optional[Callable[[dict], None]] = None) -> None:
        self.store = store
        self._search = search
        self._tools = tools
        self._transcriber = transcriber
        self.runtime = Runtime(
            store=store, llm=llm_a, llm_b=llm_b, search=search, tools=tools,
            progress_callback=progress_callback, transcriber=transcriber,
        )

    def capabilities(self) -> EngineCapabilities:
        """Describe the installed engine capabilities without starting a run."""
        return inspect_capabilities(
            self.store, self._search, self._tools, self._transcriber
        )

    async def create(self, request: ResearchRequest) -> ResearchSession:
        question = request.question.strip()
        if len(question) < 4:
            raise ValueError("research question is too short")
        session_id = request.session_id or f"research-{uuid.uuid4().hex[:12]}"
        if await self.store.load_session(session_id) is not None:
            raise ValueError(f"session already exists: {session_id}")
        timestamp = now_iso()
        session = ResearchSession(
            session_id=session_id, question=question, profile=request.profile,
            position_a=request.position_a.strip() or f"支持命题：{question}",
            position_b=request.position_b.strip() or f"反对命题：{question}",
            status=SessionStatus.CREATED, budget=research_budget(request.profile),
            created_at=timestamp, updated_at=timestamp,
        )
        await self.store.save_session(session)
        return session

    async def run(self, session_id: str) -> ResearchSession:
        """Run or resume a durable session from its last committed checkpoint."""
        return await self.runtime.run(session_id)

    async def create_and_run(self, request: ResearchRequest) -> ResearchSession:
        session = await self.create(request)
        return await self.run(session.session_id)
