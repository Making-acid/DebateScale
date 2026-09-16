"""Reference adapters: in-memory StorePort implementation for tests and demos."""

from __future__ import annotations

from copy import deepcopy
from typing import Optional

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


class InMemoryStore:
    durable = False

    def __init__(self) -> None:
        self._sessions: dict[str, ResearchSession] = {}
        self._plans: dict[tuple[str, Party], ResearchPlan] = {}
        self._plan_revisions: dict[tuple[str, Party], list[ResearchPlan]] = {}
        self._mutations: dict[str, list[Mutation]] = {}
        self._units: dict[str, ResearchUnit] = {}
        self._maps: dict[str, ResearchMapEntry] = {}
        self._sources: dict[str, Source] = {}
        self._issues: dict[str, Issue] = {}
        self._unit_owner: dict[str, tuple[str, Party]] = {}
        self._map_owner: dict[str, tuple[str, Party]] = {}
        self._source_owner: dict[str, str] = {}
        self._issue_owner: dict[str, str] = {}
        self._arguments: dict[str, Argument] = {}
        self._rebuttals: dict[str, Rebuttal] = {}
        self._evidence: dict[str, EvidenceRecord] = {}
        self._argument_owner: dict[str, tuple[str, Party]] = {}
        self._argument_revisions: dict[str, list[Argument]] = {}
        self._rebuttal_owner: dict[str, tuple[str, Party]] = {}
        self._evidence_owner: dict[str, tuple[str, Party]] = {}

    # --- session ---
    async def save_session(self, session: ResearchSession) -> None:
        self._sessions[session.session_id] = session

    async def load_session(self, session_id: str) -> Optional[ResearchSession]:
        return self._sessions.get(session_id)

    # --- dynamic plans ---
    async def save_plan(
        self, plan: ResearchPlan, session_id: str, agent: Party
    ) -> None:
        key = (session_id, agent)
        snapshot = deepcopy(plan)
        revisions = self._plan_revisions.setdefault(key, [])
        if not revisions or revisions[-1].version != snapshot.version:
            revisions.append(snapshot)
        else:
            revisions[-1] = snapshot
        self._plans[key] = deepcopy(plan)

    async def load_plan(
        self, session_id: str, agent: Party
    ) -> Optional[ResearchPlan]:
        plan = self._plans.get((session_id, agent))
        return deepcopy(plan) if plan is not None else None

    async def list_plan_revisions(
        self, session_id: str, agent: Party
    ) -> list[ResearchPlan]:
        return deepcopy(self._plan_revisions.get((session_id, agent), []))

    # --- mutation log ---
    async def append_mutation(self, mutation: Mutation) -> None:
        self._mutations.setdefault(mutation.session_id, []).append(mutation)

    async def list_mutations(self, session_id: str) -> list[Mutation]:
        return list(self._mutations.get(session_id, []))

    # --- units ---
    async def save_unit(self, unit: ResearchUnit, session_id: str, agent: Party) -> None:
        self._units[unit.unit_id] = unit
        self._unit_owner[unit.unit_id] = (session_id, agent)

    async def load_unit(self, unit_id: str) -> Optional[ResearchUnit]:
        return self._units.get(unit_id)

    async def list_units(self, session_id: str, agent: Party) -> list[ResearchUnit]:
        return [
            self._units[uid]
            for uid, (sid, a) in self._unit_owner.items()
            if sid == session_id and a is agent
        ]

    # --- map ---
    async def save_map_entry(
        self, entry: ResearchMapEntry, session_id: str, agent: Party
    ) -> None:
        self._maps[entry.map_id] = entry
        self._map_owner[entry.map_id] = (session_id, agent)

    async def load_map_entry(self, map_id: str) -> Optional[ResearchMapEntry]:
        return self._maps.get(map_id)

    async def list_map_entries(
        self, session_id: str, agent: Party
    ) -> list[ResearchMapEntry]:
        return [
            self._maps[mid]
            for mid, (sid, a) in self._map_owner.items()
            if sid == session_id and a is agent
        ]

    # --- sources ---
    async def save_source(self, source: Source, session_id: str) -> None:
        self._sources[source.source_id] = source
        self._source_owner[source.source_id] = session_id

    async def load_source(self, source_id: str) -> Optional[Source]:
        return self._sources.get(source_id)

    async def list_sources(self, session_id: str) -> list[Source]:
        return [
            self._sources[sid]
            for sid, sess in self._source_owner.items()
            if sess == session_id
        ]

    # --- issues ---
    async def save_issue(self, issue: Issue, session_id: str) -> None:
        self._issues[issue.issue_id] = issue
        self._issue_owner[issue.issue_id] = session_id

    async def load_issue(self, issue_id: str) -> Optional[Issue]:
        return self._issues.get(issue_id)

    async def list_issues(self, session_id: str) -> list[Issue]:
        return [
            self._issues[iid]
            for iid, sess in self._issue_owner.items()
            if sess == session_id
        ]

    # --- structured arguments ---
    async def save_argument(
        self, argument: Argument, session_id: str, agent: Party
    ) -> None:
        snapshot = deepcopy(argument)
        revisions = self._argument_revisions.setdefault(argument.argument_id, [])
        if not revisions or revisions[-1].version != snapshot.version:
            revisions.append(snapshot)
        else:
            revisions[-1] = snapshot
        self._arguments[argument.argument_id] = deepcopy(argument)
        self._argument_owner[argument.argument_id] = (session_id, agent)

    async def load_argument(self, argument_id: str) -> Optional[Argument]:
        argument = self._arguments.get(argument_id)
        return deepcopy(argument) if argument is not None else None

    async def list_arguments(self, session_id: str, agent: Party) -> list[Argument]:
        return [
            deepcopy(self._arguments[argument_id])
            for argument_id, (sid, owner) in self._argument_owner.items()
            if sid == session_id and owner is agent
        ]

    async def list_argument_revisions(self, argument_id: str) -> list[Argument]:
        return deepcopy(self._argument_revisions.get(argument_id, []))

    # --- rebuttals ---
    async def save_rebuttal(
        self, rebuttal: Rebuttal, session_id: str, agent: Party
    ) -> None:
        self._rebuttals[rebuttal.rebuttal_id] = rebuttal
        self._rebuttal_owner[rebuttal.rebuttal_id] = (session_id, agent)

    async def load_rebuttal(self, rebuttal_id: str) -> Optional[Rebuttal]:
        return self._rebuttals.get(rebuttal_id)

    async def list_rebuttals(self, session_id: str, agent: Party) -> list[Rebuttal]:
        return [
            self._rebuttals[rebuttal_id]
            for rebuttal_id, (sid, owner) in self._rebuttal_owner.items()
            if sid == session_id and owner is agent
        ]

    # --- inspected evidence ---
    async def save_evidence(
        self, evidence: EvidenceRecord, session_id: str, agent: Party
    ) -> None:
        self._evidence[evidence.evidence_id] = evidence
        self._evidence_owner[evidence.evidence_id] = (session_id, agent)

    async def load_evidence(self, evidence_id: str) -> Optional[EvidenceRecord]:
        return self._evidence.get(evidence_id)

    async def list_evidence(
        self, session_id: str, agent: Party
    ) -> list[EvidenceRecord]:
        return [
            self._evidence[evidence_id]
            for evidence_id, (sid, owner) in self._evidence_owner.items()
            if sid == session_id and owner is agent
        ]
