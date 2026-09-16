"""Durable single-session StorePort implementation.

The engine writes one atomic JSON snapshot after every persistent mutation. Hosts
may replace it with PostgreSQL or another StorePort, while the standalone package
still gets crash-safe checkpoints out of the box.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..models import (
    Argument, EvidenceRecord, Issue, Mutation, Party, ResearchMapEntry,
    ResearchPlan, ResearchSession, ResearchUnit, Rebuttal, Source,
)
from ..serialization import from_dict, to_dict
from .in_memory_store import InMemoryStore


class JsonFileStore(InMemoryStore):
    """An atomic durable store scoped to one engine session."""

    format_version = 1
    durable = True

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self.path = Path(path)
        self._load_snapshot()

    def _snapshot(self) -> dict:
        def owned(objects: dict, owners: dict) -> list[dict]:
            return [
                {"session_id": sid, "agent": agent.value, "value": to_dict(objects[obj_id])}
                for obj_id, (sid, agent) in owners.items()
            ]

        return {
            "format_version": self.format_version,
            "sessions": [to_dict(item) for item in self._sessions.values()],
            "plans": [
                {"session_id": sid, "agent": agent.value, "value": to_dict(plan)}
                for (sid, agent), plan in self._plans.items()
            ],
            "plan_revisions": {
                f"{sid}::{agent.value}": [to_dict(item) for item in rows]
                for (sid, agent), rows in self._plan_revisions.items()
            },
            "mutations": [to_dict(item) for rows in self._mutations.values() for item in rows],
            "units": owned(self._units, self._unit_owner),
            "maps": owned(self._maps, self._map_owner),
            "sources": [
                {"session_id": sid, "value": to_dict(self._sources[obj_id])}
                for obj_id, sid in self._source_owner.items()
            ],
            "issues": [
                {"session_id": sid, "value": to_dict(self._issues[obj_id])}
                for obj_id, sid in self._issue_owner.items()
            ],
            "arguments": owned(self._arguments, self._argument_owner),
            "argument_revisions": {
                obj_id: [to_dict(item) for item in rows]
                for obj_id, rows in self._argument_revisions.items()
            },
            "rebuttals": owned(self._rebuttals, self._rebuttal_owner),
            "evidence": owned(self._evidence, self._evidence_owner),
        }

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self._snapshot(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.path)

    def _load_snapshot(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"engine state is unreadable: {self.path}") from exc
        if data.get("format_version") != self.format_version:
            raise ValueError("unsupported engine-state format")

        for raw in data.get("sessions", []):
            item = from_dict(ResearchSession, raw)
            self._sessions[item.session_id] = item
        for raw in data.get("mutations", []):
            item = from_dict(Mutation, raw)
            self._mutations.setdefault(item.session_id, []).append(item)

        def load_owned(rows: list, cls: type, objects: dict, owners: dict, id_name: str) -> None:
            for row in rows:
                item = from_dict(cls, row["value"])
                obj_id = getattr(item, id_name)
                objects[obj_id] = item
                owners[obj_id] = (row["session_id"], Party(row["agent"]))

        load_owned(data.get("units", []), ResearchUnit, self._units, self._unit_owner, "unit_id")
        load_owned(data.get("maps", []), ResearchMapEntry, self._maps, self._map_owner, "map_id")
        load_owned(data.get("arguments", []), Argument, self._arguments, self._argument_owner, "argument_id")
        load_owned(data.get("rebuttals", []), Rebuttal, self._rebuttals, self._rebuttal_owner, "rebuttal_id")
        load_owned(data.get("evidence", []), EvidenceRecord, self._evidence, self._evidence_owner, "evidence_id")
        for row in data.get("sources", []):
            item = from_dict(Source, row["value"])
            self._sources[item.source_id] = item
            self._source_owner[item.source_id] = row["session_id"]
        for row in data.get("issues", []):
            item = from_dict(Issue, row["value"])
            self._issues[item.issue_id] = item
            self._issue_owner[item.issue_id] = row["session_id"]
        self._argument_revisions = {
            obj_id: [from_dict(Argument, item) for item in rows]
            for obj_id, rows in data.get("argument_revisions", {}).items()
        }
        for row in data.get("plans", []):
            key = (row["session_id"], Party(row["agent"]))
            self._plans[key] = from_dict(ResearchPlan, row["value"])
        self._plan_revisions = {}
        for key, rows in data.get("plan_revisions", {}).items():
            sid, agent = key.rsplit("::", 1)
            self._plan_revisions[(sid, Party(agent))] = [
                from_dict(ResearchPlan, item) for item in rows
            ]

    async def save_session(self, session: ResearchSession) -> None:
        await super().save_session(session); self._flush()

    async def save_plan(self, plan, session_id, agent) -> None:
        await super().save_plan(plan, session_id, agent); self._flush()

    async def append_mutation(self, mutation: Mutation) -> None:
        await super().append_mutation(mutation); self._flush()

    async def save_unit(self, unit, session_id, agent) -> None:
        await super().save_unit(unit, session_id, agent); self._flush()

    async def save_map_entry(self, entry, session_id, agent) -> None:
        await super().save_map_entry(entry, session_id, agent); self._flush()

    async def save_source(self, source, session_id) -> None:
        await super().save_source(source, session_id); self._flush()

    async def save_issue(self, issue, session_id) -> None:
        await super().save_issue(issue, session_id); self._flush()

    async def save_argument(self, argument, session_id, agent) -> None:
        await super().save_argument(argument, session_id, agent); self._flush()

    async def save_rebuttal(self, rebuttal, session_id, agent) -> None:
        await super().save_rebuttal(rebuttal, session_id, agent); self._flush()

    async def save_evidence(self, evidence, session_id, agent) -> None:
        await super().save_evidence(evidence, session_id, agent); self._flush()
