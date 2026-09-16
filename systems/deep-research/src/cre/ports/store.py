"""Store port: persistence of the engine's durable state.

The runtime is mechanical and state is durable; this port is the seam where a
filesystem, database, or in-memory backend plugs in. ``unit_id`` / ``map_id`` /
``issue_id`` / ``source_id`` are globally unique, so loads need no session id;
save methods take session (and agent where relevant) so the backend can track
ownership (e.g. directory layout ``session/agent/unit.md``).
"""

from __future__ import annotations

from typing import Optional, Protocol

from ..models import (
    Argument,
    EvidenceRecord,
    Issue,
    Mutation,
    Party,
    ResearchMapEntry,
    ResearchPlan,
    ResearchSession,
    ResearchUnit,
    Rebuttal,
    Source,
)


class StorePort(Protocol):
    # --- session ---
    async def save_session(self, session: ResearchSession) -> None: ...

    async def load_session(self, session_id: str) -> Optional[ResearchSession]: ...

    # --- model-owned dynamic plan (one current plan per position) ---
    async def save_plan(
        self, plan: ResearchPlan, session_id: str, agent: Party
    ) -> None: ...

    async def load_plan(
        self, session_id: str, agent: Party
    ) -> Optional[ResearchPlan]: ...

    async def list_plan_revisions(
        self, session_id: str, agent: Party
    ) -> list[ResearchPlan]: ...

    # --- mutation log (append-only) ---
    async def append_mutation(self, mutation: Mutation) -> None: ...

    async def list_mutations(self, session_id: str) -> list[Mutation]: ...

    # --- blackboard: units (per agent) ---
    async def save_unit(self, unit: ResearchUnit, session_id: str, agent: Party) -> None: ...

    async def load_unit(self, unit_id: str) -> Optional[ResearchUnit]: ...

    async def list_units(self, session_id: str, agent: Party) -> list[ResearchUnit]: ...

    # --- blackboard: map (per agent) ---
    async def save_map_entry(
        self, entry: ResearchMapEntry, session_id: str, agent: Party
    ) -> None: ...

    async def load_map_entry(self, map_id: str) -> Optional[ResearchMapEntry]: ...

    async def list_map_entries(
        self, session_id: str, agent: Party
    ) -> list[ResearchMapEntry]: ...

    # --- sources (shared within session) ---
    async def save_source(self, source: Source, session_id: str) -> None: ...

    async def load_source(self, source_id: str) -> Optional[Source]: ...

    async def list_sources(self, session_id: str) -> list[Source]: ...

    # --- issues ---
    async def save_issue(self, issue: Issue, session_id: str) -> None: ...

    async def load_issue(self, issue_id: str) -> Optional[Issue]: ...

    async def list_issues(self, session_id: str) -> list[Issue]: ...

    # --- current case: structured arguments (per agent) ---
    async def save_argument(
        self, argument: Argument, session_id: str, agent: Party
    ) -> None: ...

    async def load_argument(self, argument_id: str) -> Optional[Argument]: ...

    async def list_arguments(self, session_id: str, agent: Party) -> list[Argument]: ...

    async def list_argument_revisions(self, argument_id: str) -> list[Argument]: ...

    # --- rebuttals (owned by the attacking agent) ---
    async def save_rebuttal(
        self, rebuttal: Rebuttal, session_id: str, agent: Party
    ) -> None: ...

    async def load_rebuttal(self, rebuttal_id: str) -> Optional[Rebuttal]: ...

    async def list_rebuttals(self, session_id: str, agent: Party) -> list[Rebuttal]: ...

    # --- inspected evidence interpretations (per agent) ---
    async def save_evidence(
        self, evidence: EvidenceRecord, session_id: str, agent: Party
    ) -> None: ...

    async def load_evidence(self, evidence_id: str) -> Optional[EvidenceRecord]: ...

    async def list_evidence(
        self, session_id: str, agent: Party
    ) -> list[EvidenceRecord]: ...
