"""Dump the full persistent state of the pioneer session as a readable report."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cre.adapters import InMemoryStore
from cre.engine import Runtime
from cre.models import Party, ResearchSession, SessionStatus
from pioneer_test import MockSearch, PioneerLLM, QUESTION, TrackingStore


async def main():
    store = TrackingStore()
    await store.save_session(ResearchSession(
        session_id="pioneer", question=QUESTION, status=SessionStatus.CREATED))
    runtime = Runtime(store=store, llm=PioneerLLM(), search=MockSearch())
    result = await runtime.run("pioneer")

    print(f"# 研究报告：{result.question}")
    print(f"（session=pioneer  状态={result.status.value}  cycles={result.current_cycle}）\n")

    for a in ("A", "B"):
        party = Party[a]
        print(f"\n{'='*60}\n== Researcher {a} 的 Blackboard ==\n{'='*60}")
        for u in await store.list_units("pioneer", party):
            print(f"\n### {u.unit_id}  status={u.status.value}  sources={u.source_ids}")
            print(u.content)
        print(f"\n### {a} 的 Research Map")
        for e in await store.list_map_entries("pioneer", party):
            print(f"- {e.map_id} [{e.status.value}] imp={e.importance} "
                  f"cov={e.coverage} unc={e.uncertainty}  {e.title}")
            if e.note:
                print(f"    note: {e.note}")

    print(f"\n{'='*60}\n== Issue 档案 ==\n{'='*60}")
    for i in await store.list_issues("pioneer"):
        print(f"\n### {i.issue_id}  {i.from_agent.value}->{i.to_agent.value}  "
              f"state={i.state.value}  resolution={i.resolution.value}  priority={i.priority}")
        print(f"target: {i.target.type.value}:{i.target.id}#{i.target.section}")
        print(f"title: {i.title}\nbody:\n{i.body}")

    print(f"\n{'='*60}\n== 各 Pass 结论（Pass Conclusion）==\n{'='*60}")
    from cre.engine import MutationLog
    from cre.models import EngineAction
    for m in await MutationLog(store, "pioneer").list():
        if m.action == EngineAction.CONCLUDE_PASS:
            p = m.payload
            print(f"\n### Pass {m.pass_no}（{m.agent.value}）")
            print(f"  总结: {p.get('summary','')}")
            print(f"  剩余未知: {p.get('remaining_unknowns','')}")
            print(f"  下一 Pass 建议: {p.get('next_pass','')}")
            print(f"  无高价值方向: {p.get('no_high_value_direction')}")


if __name__ == "__main__":
    asyncio.run(main())
