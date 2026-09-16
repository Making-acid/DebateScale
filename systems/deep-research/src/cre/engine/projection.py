"""Stable projection of engine state for any host or report renderer."""

from __future__ import annotations

from ..models import EngineAction, Party
from ..ports.store import StorePort
from ..serialization import to_dict
from .mutation_log import MutationLog


def _pass_label(number: int) -> str:
    if number <= 2:
        return "Pass One · 独立展开"
    if number <= 4:
        return "Pass Two · 交叉校验"
    return f"持续研究 · 第 {(number - 3) // 2} 轮"


async def project_research(
    store: StorePort, session_id: str, *, mode: str = "live"
) -> dict:
    """Return the versioned, renderer-neutral result contract."""

    result = await store.load_session(session_id)
    if result is None:
        raise KeyError(session_id)
    mutations = await MutationLog(store, session_id).list()
    units = {
        party.value: [to_dict(item) for item in await store.list_units(session_id, party)]
        for party in (Party.A, Party.B)
    }
    maps = {
        party.value: [to_dict(item) for item in await store.list_map_entries(session_id, party)]
        for party in (Party.A, Party.B)
    }
    plans = {}
    for party in (Party.A, Party.B):
        plan = await store.load_plan(session_id, party)
        plans[party.value] = to_dict(plan) if plan is not None else None
    plan_revisions = {
        party.value: [
            to_dict(item)
            for item in await store.list_plan_revisions(session_id, party)
        ]
        for party in (Party.A, Party.B)
    }
    arguments = {
        party.value: [to_dict(item) for item in await store.list_arguments(session_id, party)]
        for party in (Party.A, Party.B)
    }
    rebuttals = {
        party.value: [to_dict(item) for item in await store.list_rebuttals(session_id, party)]
        for party in (Party.A, Party.B)
    }
    revision_gaps = {}
    for party in (Party.A, Party.B):
        opponent = Party.B if party is Party.A else Party.A
        covered = {
            (item["target_argument_id"], item["target_version"])
            for item in rebuttals[party.value]
            if item.get("status") not in {"withdrawn", "answered"}
            and all(item.get(field) for field in (
                "title", "reconstruction", "attack_type", "attack", "why_it_matters"
            ))
        }
        revision_gaps[party.value] = [
            {
                "argument_id": item["argument_id"],
                "current_version": item["version"],
                "previously_reviewed_versions": sorted({
                    rebuttal["target_version"]
                    for rebuttal in rebuttals[party.value]
                    if rebuttal["target_argument_id"] == item["argument_id"]
                }),
            }
            for item in arguments[opponent.value]
            if item.get("status") != "withdrawn"
            and (item["argument_id"], item["version"]) not in covered
        ]
    evidence = {
        party.value: [to_dict(item) for item in await store.list_evidence(session_id, party)]
        for party in (Party.A, Party.B)
    }
    issues = [to_dict(item) for item in await store.list_issues(session_id)]
    sources = [to_dict(item) for item in await store.list_sources(session_id)]
    revisions = {
        item["argument_id"]: [
            to_dict(revision)
            for revision in await store.list_argument_revisions(item["argument_id"])
        ]
        for items in arguments.values()
        for item in items
    }

    grouped: dict[int, list] = {}
    for mutation in mutations:
        grouped.setdefault(mutation.pass_no, []).append(mutation)
    passes = []
    for number, entries in sorted(grouped.items()):
        conclusion = next(
            (item for item in entries if item.action is EngineAction.CONCLUDE_PASS), None
        )
        passes.append({
            "number": number,
            "agent": entries[0].agent.value,
            "phase": _pass_label(number),
            "summary": conclusion.payload.get("summary", "") if conclusion else "",
            "remaining_unknowns": conclusion.payload.get("remaining_unknowns", "") if conclusion else "",
            "why_stop": conclusion.payload.get("why_stop", "") if conclusion else "",
            "changes": [
                {
                    "action": item.action.value,
                    "target": item.target.id if item.target else None,
                    "what_changed": item.what_changed,
                    "why": item.why,
                }
                for item in entries
                if item.action is not EngineAction.CONCLUDE_PASS
            ],
        })

    timeline = [
        {"time": timestamp, "status": status, "cycle": cycle, "next": next_agent}
        for timestamp, status, cycle, next_agent in getattr(store, "timeline", [])
    ]
    return {
        "contract_version": "2",
        "mode": mode,
        "mode_note": (
            "真实研究：双方模型使用隔离上下文，联网搜索并深读来源。"
            if mode == "live"
            else "内置结构样例。"
        ),
        "session": to_dict(result),
        "units": units,
        "maps": maps,
        "plans": plans,
        "plan_revisions": plan_revisions,
        "issues": issues,
        "sources": sources,
        "arguments": arguments,
        "rebuttals": rebuttals,
        "revision_gaps": revision_gaps,
        "evidence": evidence,
        "argument_revisions": revisions,
        "passes": passes,
        "mutations": [to_dict(item) for item in mutations],
        "timeline": timeline,
        "metrics": {
            "sources": len(sources),
            "arguments": sum(map(len, arguments.values())),
            "evidence": sum(map(len, evidence.values())),
            "rebuttals": sum(map(len, rebuttals.values())),
            "passes": len(passes),
        },
    }
