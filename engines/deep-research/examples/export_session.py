"""Export current debate-ready results first, with the process as an appendix.

Everything comes from the store, but the reading order is deliberate: current
arguments and rebuttals are the product; internal work records are history.

Run with:  python examples/export_session.py [session_id] [output.md]
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cre.adapters import InMemoryStore
from cre.engine import MutationLog, build_semantic_diff, now_iso
from cre.models import EngineAction, Party, SessionStatus


def _pass_map(mutations):
    passes = {}
    for m in mutations:
        passes.setdefault(m.pass_no, []).append(m)
    return passes


def _agent_of(pass_mutations):
    agents = {m.agent for m in pass_mutations}
    return next(iter(agents)).value if len(agents) == 1 else "?"


async def export(store: InMemoryStore, session_id: str) -> str:
    from cre.models import Party  # noqa: F401

    session = await store.load_session(session_id)
    if session is None:
        raise KeyError(f"unknown session {session_id}")

    log = MutationLog(store, session_id)
    mutations = await log.list()
    passes = _pass_map(mutations)
    lines: list[str] = []

    w = lines.append
    w(f"# Continuous Research Engine — 会话导出")
    w("")
    w(f"- **Session**: `{session_id}`")
    w(f"- **辩题**: {session.question}")
    w(f"- **A 方立场**: {session.position_for(Party.A)}")
    w(f"- **B 方立场**: {session.position_for(Party.B)}")
    w(f"- **状态**: `{session.status.value}`  |  **Cycles**: {session.current_cycle}"
      f"  |  **下一个先手**: {session.next_agent.value}")
    w(f"- **导出时间**: {now_iso()}")
    w(f"- **Mutations**: {len(mutations)} 条  |  "
      f"**Passes**: {len(passes)} 个  |  "
      f"**来源**: {len(await store.list_sources(session_id))} 条（共享）")
    w("")
    w("> 阅读顺序：先看双方当前立论与攻防；证据账本随后；"
      "旧版本和内部过程只放在附录。")
    w("")

    # ---- current product: what a debater should read first ----
    source_by_id = {s.source_id: s for s in await store.list_sources(session_id)}
    w("## 一、双方当前立论\n")
    for agent in session.agents:
        arguments = await store.list_arguments(session_id, agent)
        w(f"### {agent.value} 方：{session.position_for(agent)}\n")
        if not arguments:
            w("（尚未形成结构化论点）\n")
        for argument in arguments:
            if argument.status.value == "withdrawn":
                continue
            w(f"#### {argument.title}  `v{argument.version}`  `{argument.status.value}`\n")
            w(f"- **主张**：{argument.claim}")
            w(f"- **需承担的证明责任**：{argument.burden}")
            if argument.criterion:
                w(f"- **判准**：{argument.criterion}")
            w("- **论证链**：")
            for index, step in enumerate(argument.warrant, 1):
                w(f"  {index}. {step}")
            w(f"- **影响**：{argument.impact}")
            w(f"- **成立边界**：{argument.scope}")
            if argument.vulnerabilities:
                w("- **已知薄弱处**：" + "；".join(argument.vulnerabilities))
            if argument.defense:
                w("- **当前防守**：" + "；".join(argument.defense))
            if argument.evidence_ids:
                w("- **直接证据**：")
                for evidence_id in argument.evidence_ids:
                    evidence = await store.load_evidence(evidence_id)
                    if evidence is None:
                        continue
                    source = source_by_id.get(evidence.source_id)
                    source_label = source.title if source else evidence.source_id
                    w(f"  - {evidence.finding} — {source_label}"
                      f"（限制：{evidence.limitations or '未登记'}）")
            w("")

    w("\n---\n\n## 二、双方当前攻防\n")
    for agent in session.agents:
        rebuttals = await store.list_rebuttals(session_id, agent)
        w(f"### {agent.value} 方对对方的驳论\n")
        if not rebuttals:
            w("（尚未形成结构化驳论）\n")
        for rebuttal in rebuttals:
            w(f"#### {rebuttal.title}  `{rebuttal.status.value}`\n")
            w(f"- **它针对的论证**：{rebuttal.reconstruction}")
            w(f"- **攻击类型**：{rebuttal.attack_type}")
            w(f"- **具体攻击**：{rebuttal.attack}")
            w(f"- **为什么会动摇对方**：{rebuttal.why_it_matters}")
            if rebuttal.likely_response:
                w(f"- **对方可能如何回应**：{rebuttal.likely_response}")
            if rebuttal.current_effect:
                w(f"- **当前结果**：{rebuttal.current_effect}")
            w("")

    w("\n---\n\n## 三、证据账本\n")
    for agent in session.agents:
        evidence_records = await store.list_evidence(session_id, agent)
        w(f"### {agent.value} 方已深读证据（{len(evidence_records)}）\n")
        for evidence in evidence_records:
            source = source_by_id.get(evidence.source_id)
            w(f"- **{evidence.proposition}**：{evidence.finding}")
            w(f"  - 方法：{evidence.method or '未登记'}")
            w(f"  - 限制：{evidence.limitations or '未登记'}")
            if source:
                w(f"  - 来源：[{source.title}]({source.url})")
        w("")

    w("\n---\n\n# 附录：推演历史与内部记录\n")

    w("## 论点修订历史\n")
    for agent in session.agents:
        for argument in await store.list_arguments(session_id, agent):
            revisions = await store.list_argument_revisions(argument.argument_id)
            w(f"### {agent.value} 方 / {argument.title}\n")
            for revision in revisions:
                w(f"- `v{revision.version}` `{revision.status.value}`：{revision.claim}")
    w("")

    # ---- blackboards ----
    for agent in session.agents:
        units = await store.list_units(session_id, agent)
        maps = await store.list_map_entries(session_id, agent)
        w(f"\n---\n\n## 内部 Blackboard / {agent.value} 方\n")
        w(f"### Units（{len(units)}）\n")
        if not units:
            w("（空）\n")
        for u in units:
            w(f"#### `{u.unit_id}`  status=`{u.status.value}`  "
              f"sources={u.source_ids or '[]'}\n")
            w(u.content)
            w("")
        w(f"### Research Map（{len(maps)}）\n")
        if not maps:
            w("（空）\n")
        for e in maps:
            w(f"- **`{e.map_id}`** `{e.status.value}` "
              f"imp=`{e.importance}` cov=`{e.coverage}` unc=`{e.uncertainty}` — "
              f"**{e.title}**")
            if e.note:
                w(f"  - note: {e.note}")
        w("")

    # ---- issues ----
    issues = await store.list_issues(session_id)
    w(f"\n---\n\n## Issue 档案（{len(issues)}）\n")
    if not issues:
        w("（无）\n")
    for i in sorted(issues, key=lambda x: x.issue_id):
        res = i.resolution.value if i.resolution else "-"
        w(f"### `{i.issue_id}`  {i.from_agent.value} → {i.to_agent.value}  "
          f"state=`{i.state.value}`  resolution=`{res}`  priority=`{i.priority}`\n")
        w(f"- target: `{i.target.type.value}:{i.target.id}`"
          f"{'#' + i.target.section if i.target.section else ''}")
        w(f"- **{i.title}**")
        w("")
        w(i.body)
        w("")

    # ---- sources ----
    sources = await store.list_sources(session_id)
    w(f"\n---\n\n## 共享 Source Pool（{len(sources)}）\n")
    for s in sorted(sources, key=lambda x: x.source_id):
        disc = f" 发现者={s.discovered_by.value}" if s.discovered_by else ""
        w(f"- **`{s.source_id}`** {s.title} — {s.url}{disc}")
        if s.content:
            w(f"  - {s.content}")
    w("")

    # ---- pass conclusions ----
    w(f"\n---\n\n## 各 Pass 结论（Pass Conclusion）\n")
    for pno in sorted(passes):
        agent = _agent_of(passes[pno])
        w(f"### Pass {pno}（{agent}）\n")
        for m in passes[pno]:
            if m.action == EngineAction.CONCLUDE_PASS:
                p = m.payload
                w(f"- 总结: {p.get('summary', '') or m.what_changed}")
                w(f"- 实际改变: {p.get('changed', '')}")
                w(f"- 剩余未知: {p.get('remaining_unknowns', '')}")
                w(f"- 为什么停: {p.get('why_stop', '')}")
                w(f"- 下一 Pass 建议: {p.get('next_pass', '')}")
                w(f"- 无高价值方向: **{p.get('no_high_value_direction')}**")
        w("")

    # ---- semantic diffs (communication record) ----
    w(f"\n---\n\n## Semantic Diff（双方互相看到的认知变化，逐 Pass）\n")
    for pno in sorted(passes):
        pm = passes[pno]
        agent = _agent_of(passes[pno])
        w(f"### {agent} Pass #{pno}\n")
        w("```text")
        w(build_semantic_diff(pm, Party[agent] if agent in Party.__members__ else Party.A, pno).rstrip())
        w("```")
        w("")

    # ---- mutation log appendix ----
    w(f"\n---\n\n## 附录：Mutation Log（append-only 真相源，{len(mutations)} 条）\n")
    w("| seq | pass | agent | action | target | what_changed |")
    w("|---|---|---|---|---|---|")
    for m in mutations:
        tgt = m.target.id if m.target else ""
        wc = (m.what_changed or "").replace("|", "\\|").replace("\n", " ")
        w(f"| {m.seq} | {m.pass_no} | {m.agent.value} | `{m.action.value}` "
          f"| {tgt} | {wc} |")
    w("")
    return "\n".join(lines)


async def main():
    session_id = sys.argv[1] if len(sys.argv) > 1 else "pioneer"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent / f"export_{session_id}.md"

    # rebuild the pioneer session so the export is self-contained
    if session_id == "pioneer":
        from pioneer_test import MockSearch, PioneerLLM, QUESTION, TrackingStore
        store = TrackingStore()
        from cre.models import ResearchBudget, ResearchSession, SessionStatus
        await store.save_session(ResearchSession(
            session_id=session_id,
            question=QUESTION,
            position_a="表情包丰富了我们的表达",
            position_b="表情包虚泛了我们的表达",
            status=SessionStatus.CREATED,
            budget=ResearchBudget(
                min_sources_per_agent=2,
                min_examined_sources_per_agent=3,
                min_core_arguments_per_agent=3,
                min_rebuttals_per_agent=2,
            )))
        await Runtime(store=store, llm=PioneerLLM(), search=MockSearch()).run(session_id)
    else:
        store = InMemoryStore()

    report = await export(store, session_id)
    out.write_text(report, encoding="utf-8")
    print(f"exported: {out.resolve()}  ({len(report)} chars)")


if __name__ == "__main__":
    from cre.engine import Runtime

    asyncio.run(main())
