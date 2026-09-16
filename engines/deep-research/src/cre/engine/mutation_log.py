"""Mutation log: the append-only source of truth for the engine.

The Blackboard files, Semantic Diff and Issue Archive are projections of this
log. ``MutationLog`` owns id / seq / timestamp generation and delegates
persistence to the store. Seq assignment is guarded by a lock so parallel
passes (e.g. the expansion of A and B) never collide.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from ..models import EngineAction, Mutation, Party, TargetRef
from ..ports.store import StorePort


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MutationLog:
    def __init__(self, store: StorePort, session_id: str):
        self._store = store
        self.session_id = session_id
        self._lock = asyncio.Lock()
        self._seq = 0
        self._loaded = False

    async def _ensure_loaded(self) -> None:
        mutations = await self._store.list_mutations(self.session_id)
        self._seq = max((m.seq for m in mutations), default=0)
        self._loaded = True

    async def append(
        self,
        *,
        agent: Party,
        action: EngineAction,
        pass_no: int,
        what_changed: str = "",
        why: str = "",
        target: Optional[TargetRef] = None,
        payload: Optional[dict] = None,
    ) -> Mutation:
        async with self._lock:
            if not self._loaded:
                await self._ensure_loaded()
            self._seq += 1
            seq = self._seq
            mutation = Mutation(
                mutation_id=f"mut_{seq}",
                seq=seq,
                session_id=self.session_id,
                pass_no=pass_no,
                agent=agent,
                action=action,
                what_changed=what_changed,
                why=why,
                target=target,
                payload=payload or {},
                created_at=now_iso(),
            )
            await self._store.append_mutation(mutation)
            return mutation

    async def list(self, pass_no: Optional[int] = None) -> list[Mutation]:
        mutations = await self._store.list_mutations(self.session_id)
        if pass_no is not None:
            mutations = [m for m in mutations if m.pass_no == pass_no]
        return sorted(mutations, key=lambda m: m.seq)
