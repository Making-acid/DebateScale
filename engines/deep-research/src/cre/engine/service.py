"""Stable, UI-independent facade for Continuous Research Engine."""

from __future__ import annotations

import uuid
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


@dataclass(frozen=True)
class ResearchRequest:
    question: str
    position_a: str = ""
    position_b: str = ""
    profile: str = "deep"
    session_id: str = ""


def research_budget(profile: str) -> ResearchBudget:
    if profile == "standard":
        return ResearchBudget(
            max_tool_calls_per_pass=36, max_tokens_per_pass=400_000,
            max_failed_tool_calls_per_pass=10,
            max_parallel_research_actions_per_turn=2,
            max_model_turns_per_pass=48,
            max_unproductive_turns_per_pass=5,
            max_tokens_without_state_progress=45_000,
            min_token_reserve_per_model_turn=16_000,
            max_cycles=1, min_sources_per_agent=0,
            min_examined_sources_per_agent=0, min_core_arguments_per_agent=3,
            min_rebuttals_per_agent=2,
        )
    if profile == "deep":
        return ResearchBudget(
            max_tool_calls_per_pass=72, max_tokens_per_pass=500_000,
            max_failed_tool_calls_per_pass=18,
            max_parallel_research_actions_per_turn=2,
            max_model_turns_per_pass=90,
            max_unproductive_turns_per_pass=7,
            max_tokens_without_state_progress=70_000,
            min_token_reserve_per_model_turn=20_000,
            max_cycles=2, min_sources_per_agent=0,
            min_examined_sources_per_agent=0, min_core_arguments_per_agent=4,
            min_rebuttals_per_agent=3,
        )
    raise ValueError(f"unknown research profile: {profile}")


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
            session_id=session_id, question=question,
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
