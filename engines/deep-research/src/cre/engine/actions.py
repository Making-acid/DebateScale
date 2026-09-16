"""Engine action application: turn a model-produced action into a state change
plus an append-only mutation.

This is the mechanical core: it reads/writes state via the store and appends
exactly one mutation per action. It performs NO semantic judgment.
"""

from __future__ import annotations

import copy
from typing import Optional

from ..models import (
    Argument,
    ArgumentStatus,
    EngineAction,
    EvidenceRecord,
    EvidenceStatus,
    Issue,
    IssueResolution,
    IssueState,
    MapStatus,
    Mutation,
    Party,
    ResearchMapEntry,
    ResearchPlan,
    ResearchUnit,
    Rebuttal,
    RebuttalStatus,
    TargetRef,
    TargetType,
    UnitStatus,
)
from ..ports.store import StorePort
from .mutation_log import MutationLog


def _tail_num(id_: str) -> int:
    tail = id_.rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _parse_party(value) -> Party:
    return value if isinstance(value, Party) else Party(str(value))


def _parse_target(value) -> TargetRef:
    if isinstance(value, TargetRef):
        return value
    return TargetRef(
        type=TargetType(value["type"]),
        id=value["id"],
        section=value.get("section"),
    )


async def _next_unit_id(store: StorePort, session_id: str, agent: Party) -> str:
    units = await store.list_units(session_id, agent)
    n = max((_tail_num(u.unit_id) for u in units), default=0) + 1
    return f"ru_{agent.value.lower()}_{n:04d}"


async def _next_map_id(store: StorePort, session_id: str, agent: Party) -> str:
    entries = await store.list_map_entries(session_id, agent)
    n = max((_tail_num(e.map_id) for e in entries), default=0) + 1
    return f"map_{agent.value.lower()}_{n:04d}"


async def _next_issue_id(store: StorePort, session_id: str) -> str:
    issues = await store.list_issues(session_id)
    n = max((_tail_num(i.issue_id) for i in issues), default=0) + 1
    return f"issue_{n:04d}"


async def _next_argument_id(store: StorePort, session_id: str, agent: Party) -> str:
    arguments = await store.list_arguments(session_id, agent)
    n = max((_tail_num(item.argument_id) for item in arguments), default=0) + 1
    return f"arg_{agent.value.lower()}_{n:04d}"


async def _next_rebuttal_id(store: StorePort, session_id: str, agent: Party) -> str:
    rebuttals = await store.list_rebuttals(session_id, agent)
    n = max((_tail_num(item.rebuttal_id) for item in rebuttals), default=0) + 1
    return f"reb_{agent.value.lower()}_{n:04d}"


async def _next_evidence_id(store: StorePort, session_id: str, agent: Party) -> str:
    evidence = await store.list_evidence(session_id, agent)
    n = max((_tail_num(item.evidence_id) for item in evidence), default=0) + 1
    return f"ev_{agent.value.lower()}_{n:04d}"


async def _update_plan(
    store: StorePort, log: MutationLog, agent: Party, pass_no: int, payload: dict
) -> Mutation:
    plan = await store.load_plan(log.session_id, agent)
    previous = copy.deepcopy(plan)
    if plan is None:
        plan = ResearchPlan(plan_id=f"plan_{agent.value.lower()}")
    else:
        plan.version += 1

    for field in (
        "phase", "question_interpretation", "winning_condition", "strategy",
        "remaining_work", "progress_assessment", "status", "change_reason",
    ):
        if field in payload:
            setattr(plan, field, str(payload[field]))
    for field in (
        "route_hypotheses", "next_actions", "stopping_conditions", "completed",
        "abandoned",
    ):
        if field in payload:
            setattr(plan, field, list(payload[field]))
    if "estimated_remaining_actions" in payload:
        plan.estimated_remaining_actions = int(payload["estimated_remaining_actions"])

    if plan.status not in {"active", "ready_to_conclude"}:
        raise ValueError("plan status must be active or ready_to_conclude")
    if len(plan.next_actions) > 5:
        raise ValueError("keep only the next five highest-value actions in the rolling plan")
    if plan.estimated_remaining_actions < -1 or plan.estimated_remaining_actions > 30:
        raise ValueError("estimated_remaining_actions must be -1 (unknown) or between 0 and 30")
    missing = plan.missing_fields()
    if missing:
        raise ValueError("dynamic plan is incomplete; missing: " + ", ".join(missing))
    if previous is not None:
        comparable = copy.deepcopy(plan)
        comparable.version = previous.version
        if comparable == previous:
            raise ValueError(
                "plan update made no material change; execute the existing next action "
                "or conclude instead of creating a duplicate plan revision"
            )

    await store.save_plan(plan, log.session_id, agent)
    return await log.append(
        agent=agent,
        action=EngineAction.UPDATE_PLAN,
        pass_no=pass_no,
        what_changed=payload.get("what_changed", plan.change_reason),
        why=payload.get("why", ""),
        target=TargetRef(type=TargetType.PLAN, id=plan.plan_id),
        payload={
            "phase": plan.phase, "status": plan.status, "version": plan.version,
            "estimated_remaining_actions": plan.estimated_remaining_actions,
        },
    )


async def _update_unit(
    store: StorePort, log: MutationLog, agent: Party, pass_no: int, payload: dict
) -> Mutation:
    unit_id = payload.get("unit_id") or await _next_unit_id(store, log.session_id, agent)
    unit = await store.load_unit(unit_id) or ResearchUnit(unit_id=unit_id)

    if "content" in payload:
        unit.content = payload["content"]
    if "status" in payload:
        unit.status = UnitStatus(payload["status"])
    if "source_ids" in payload:
        unit.source_ids = list(payload["source_ids"])

    await store.save_unit(unit, log.session_id, agent)
    return await log.append(
        agent=agent,
        action=EngineAction.UPDATE_UNIT,
        pass_no=pass_no,
        what_changed=payload.get("what_changed", ""),
        why=payload.get("why", ""),
        target=TargetRef(type=TargetType.UNIT, id=unit_id),
        payload={"status": unit.status.value, "source_ids": unit.source_ids},
    )


async def _update_map(
    store: StorePort, log: MutationLog, agent: Party, pass_no: int, payload: dict
) -> Mutation:
    map_id = payload.get("map_id") or await _next_map_id(store, log.session_id, agent)
    entry = await store.load_map_entry(map_id) or ResearchMapEntry(map_id=map_id, title="")

    if "title" in payload:
        entry.title = payload["title"]
    if "status" in payload:
        entry.status = MapStatus(payload["status"])
    for field in ("importance", "coverage", "uncertainty"):
        if field in payload:
            setattr(entry, field, payload[field])
    if "note" in payload:
        entry.note = payload["note"]
    if "proof_obligation" in payload:
        entry.proof_obligation = payload["proof_obligation"]
    if "externally_blocked" in payload:
        entry.externally_blocked = bool(payload["externally_blocked"])
    if "blocker_reason" in payload:
        entry.blocker_reason = payload["blocker_reason"]

    await store.save_map_entry(entry, log.session_id, agent)
    return await log.append(
        agent=agent,
        action=EngineAction.UPDATE_MAP,
        pass_no=pass_no,
        what_changed=payload.get("what_changed", ""),
        why=payload.get("why", ""),
        target=TargetRef(type=TargetType.MAP, id=map_id),
        payload={"status": entry.status.value},
    )


async def _update_argument(
    store: StorePort, log: MutationLog, agent: Party, pass_no: int, payload: dict
) -> Mutation:
    own_arguments = await store.list_arguments(log.session_id, agent)
    own_argument_ids = {item.argument_id for item in own_arguments}
    argument_id = payload.get("argument_id") or await _next_argument_id(
        store, log.session_id, agent
    )
    argument = await store.load_argument(argument_id)
    if argument is not None and argument_id not in own_argument_ids:
        valid = ", ".join(sorted(own_argument_ids)) or "none"
        raise ValueError(
            f"cannot revise argument {argument_id}: it is not owned by position "
            f"{agent.value}. Use update_rebuttal to attack an opponent argument. "
            f"Valid own argument ids: {valid}"
        )
    if argument is None:
        required_text = ("title", "claim", "burden", "impact", "scope")
        missing = [
            field for field in required_text
            if not str(payload.get(field, "")).strip()
        ]
        if len(payload.get("warrant") or []) < 2:
            missing.append("warrant(>=2 steps)")
        if missing:
            raise ValueError(
                "a new argument cannot be an empty placeholder; provide its basic "
                "proof structure in the same update: " + ", ".join(missing)
            )
        argument = Argument(argument_id=argument_id)
    else:
        argument.version += 1

    for field in (
        "title", "claim", "burden", "criterion", "impact", "scope",
        "original_contribution", "support_type"
    ):
        if field in payload:
            setattr(argument, field, str(payload[field]))
    for field in (
        "warrant", "evidence_ids", "material_source_ids", "evidence_need",
        "vulnerabilities", "defense"
    ):
        if field in payload:
            setattr(argument, field, list(payload[field]))
    if argument.support_type not in {"reasoning", "mixed", "empirical"}:
        raise ValueError("support_type must be reasoning, mixed, or empirical")
    if "status" in payload:
        argument.status = ArgumentStatus(payload["status"])

    for evidence_id in argument.evidence_ids:
        if await store.load_evidence(evidence_id) is None:
            raise KeyError(f"argument references unknown evidence {evidence_id}")
    for source_id in argument.material_source_ids:
        if await store.load_source(source_id) is None:
            raise KeyError(f"argument references unknown material source {source_id}")

    await store.save_argument(argument, log.session_id, agent)
    return await log.append(
        agent=agent,
        action=EngineAction.UPDATE_ARGUMENT,
        pass_no=pass_no,
        what_changed=payload.get("what_changed", ""),
        why=payload.get("why", ""),
        target=TargetRef(type=TargetType.ARGUMENT, id=argument_id),
        payload={"status": argument.status.value, "version": argument.version},
    )


async def _record_evidence(
    store: StorePort, log: MutationLog, agent: Party, pass_no: int, payload: dict
) -> Mutation:
    source_id = payload["source_id"]
    if await store.load_source(source_id) is None:
        raise KeyError(f"evidence references unknown source {source_id}")
    argument_id = payload.get("argument_id", "")
    if argument_id and await store.load_argument(argument_id) is None:
        raise KeyError(f"evidence references unknown argument {argument_id}")

    evidence_id = payload.get("evidence_id") or await _next_evidence_id(
        store, log.session_id, agent
    )
    record = await store.load_evidence(evidence_id) or EvidenceRecord(
        evidence_id=evidence_id, source_id=source_id
    )
    record.source_id = source_id
    for field in (
        "argument_id", "proposition", "finding", "method", "limitations",
        "relation", "provenance",
    ):
        if field in payload:
            setattr(record, field, str(payload[field]))
    if "status" in payload:
        record.status = EvidenceStatus(payload["status"])
    await store.save_evidence(record, log.session_id, agent)
    return await log.append(
        agent=agent,
        action=EngineAction.RECORD_EVIDENCE,
        pass_no=pass_no,
        what_changed=payload.get("what_changed", ""),
        why=payload.get("why", ""),
        target=TargetRef(type=TargetType.EVIDENCE, id=evidence_id),
        payload={"source_id": source_id, "status": record.status.value},
    )


async def _update_rebuttal(
    store: StorePort, log: MutationLog, agent: Party, pass_no: int, payload: dict
) -> Mutation:
    target_argument_id = payload["target_argument_id"]
    target = await store.load_argument(target_argument_id)
    if target is None:
        raise KeyError(f"rebuttal targets unknown argument {target_argument_id}")
    own_argument_ids = {
        item.argument_id
        for item in await store.list_arguments(log.session_id, agent)
    }
    if target_argument_id in own_argument_ids:
        raise ValueError(
            f"cannot create a rebuttal against own argument {target_argument_id}; "
            "repair it with update_argument instead"
        )
    rebuttal_id = payload.get("rebuttal_id") or await _next_rebuttal_id(
        store, log.session_id, agent
    )
    own_rebuttal_ids = {
        item.rebuttal_id
        for item in await store.list_rebuttals(log.session_id, agent)
    }
    rebuttal = await store.load_rebuttal(rebuttal_id)
    if rebuttal is not None and rebuttal_id not in own_rebuttal_ids:
        valid = ", ".join(sorted(own_rebuttal_ids)) or "none"
        raise ValueError(
            f"cannot revise rebuttal {rebuttal_id}: it is not owned by position "
            f"{agent.value}. Valid own rebuttal ids: {valid}"
        )
    opponent = Party.B if agent is Party.A else Party.A
    requested_target_agent = _parse_party(payload.get("target_agent", opponent))
    if requested_target_agent is not opponent:
        raise ValueError(
            f"rebuttal target_agent must be opponent {opponent.value}, not "
            f"{requested_target_agent.value}"
        )
    rebuttal = rebuttal or Rebuttal(
        rebuttal_id=rebuttal_id,
        target_agent=opponent,
        target_argument_id=target_argument_id,
        target_version=int(payload.get("target_version", target.version)),
    )
    rebuttal.target_agent = opponent
    rebuttal.target_argument_id = target_argument_id
    rebuttal.target_version = int(payload.get("target_version", target.version))
    for field in (
        "title", "reconstruction", "attack_type", "attack", "why_it_matters",
        "likely_response", "current_effect",
    ):
        if field in payload:
            setattr(rebuttal, field, str(payload[field]))
    if "evidence_ids" in payload:
        rebuttal.evidence_ids = list(payload["evidence_ids"])
    if "status" in payload:
        rebuttal.status = RebuttalStatus(payload["status"])
    await store.save_rebuttal(rebuttal, log.session_id, agent)
    return await log.append(
        agent=agent,
        action=EngineAction.UPDATE_REBUTTAL,
        pass_no=pass_no,
        what_changed=payload.get("what_changed", ""),
        why=payload.get("why", ""),
        target=TargetRef(type=TargetType.REBUTTAL, id=rebuttal_id),
        payload={
            "target_argument_id": target_argument_id,
            "target_version": rebuttal.target_version,
            "status": rebuttal.status.value,
        },
    )


async def _create_issue(
    store: StorePort, log: MutationLog, agent: Party, pass_no: int, payload: dict
) -> Mutation:
    issue_id = payload.get("issue_id") or await _next_issue_id(store, log.session_id)
    to_agent = _parse_party(payload.get("to", Party.B if agent is Party.A else Party.A))
    issue = Issue(
        issue_id=issue_id,
        from_agent=agent,
        to_agent=to_agent,
        target=_parse_target(payload["target"]),
        priority=str(payload.get("priority", "medium")),
        title=payload.get("title", ""),
        body=payload.get("body", ""),
        state=IssueState.OPEN,
    )
    await store.save_issue(issue, log.session_id)
    return await log.append(
        agent=agent,
        action=EngineAction.CREATE_ISSUE,
        pass_no=pass_no,
        what_changed=issue.title,
        target=TargetRef(type=TargetType.ISSUE, id=issue_id),
        payload={"to": to_agent.value, "priority": issue.priority, "title": issue.title},
    )


async def _respond_issue(
    store: StorePort, log: MutationLog, agent: Party, pass_no: int, payload: dict
) -> Mutation:
    issue_id = payload["issue_id"]
    issue = await store.load_issue(issue_id)
    if issue is None:
        raise KeyError(f"unknown issue {issue_id}")
    response = payload.get("response", "")
    issue.body = f"{issue.body}\n\n---\n\n{response}".strip() if issue.body else response
    await store.save_issue(issue, log.session_id)
    return await log.append(
        agent=agent,
        action=EngineAction.RESPOND_ISSUE,
        pass_no=pass_no,
        what_changed=payload.get("what_changed", ""),
        why=payload.get("why", ""),
        target=TargetRef(type=TargetType.ISSUE, id=issue_id),
        payload={"response": response},
    )


async def _close_issue(
    store: StorePort, log: MutationLog, agent: Party, pass_no: int, payload: dict
) -> Mutation:
    issue_id = payload["issue_id"]
    issue = await store.load_issue(issue_id)
    if issue is None:
        raise KeyError(f"unknown issue {issue_id}")
    issue.state = IssueState.CLOSED
    if payload.get("resolution"):
        issue.resolution = IssueResolution(payload["resolution"])
    await store.save_issue(issue, log.session_id)
    return await log.append(
        agent=agent,
        action=EngineAction.CLOSE_ISSUE,
        pass_no=pass_no,
        what_changed=payload.get("what_changed", ""),
        why=payload.get("why", ""),
        target=TargetRef(type=TargetType.ISSUE, id=issue_id),
        payload={"resolution": issue.resolution.value if issue.resolution else None},
    )


async def _conclude_pass(log: MutationLog, agent: Party, pass_no: int, payload: dict) -> Mutation:
    return await log.append(
        agent=agent,
        action=EngineAction.CONCLUDE_PASS,
        pass_no=pass_no,
        what_changed=payload.get("summary", ""),
        why=payload.get("why_stop", ""),
        target=None,
        payload=dict(payload),
    )


async def apply_action(
    store: StorePort,
    log: MutationLog,
    action: EngineAction,
    agent: Party,
    pass_no: int,
    payload: dict,
) -> Mutation:
    if action == EngineAction.UPDATE_PLAN:
        return await _update_plan(store, log, agent, pass_no, payload)
    if action == EngineAction.UPDATE_UNIT:
        return await _update_unit(store, log, agent, pass_no, payload)
    if action == EngineAction.UPDATE_MAP:
        return await _update_map(store, log, agent, pass_no, payload)
    if action == EngineAction.CREATE_ISSUE:
        return await _create_issue(store, log, agent, pass_no, payload)
    if action == EngineAction.RESPOND_ISSUE:
        return await _respond_issue(store, log, agent, pass_no, payload)
    if action == EngineAction.CLOSE_ISSUE:
        return await _close_issue(store, log, agent, pass_no, payload)
    if action == EngineAction.CONCLUDE_PASS:
        return await _conclude_pass(log, agent, pass_no, payload)
    if action == EngineAction.UPDATE_ARGUMENT:
        return await _update_argument(store, log, agent, pass_no, payload)
    if action == EngineAction.UPDATE_REBUTTAL:
        return await _update_rebuttal(store, log, agent, pass_no, payload)
    if action == EngineAction.RECORD_EVIDENCE:
        return await _record_evidence(store, log, agent, pass_no, payload)
    raise ValueError(f"unknown engine action: {action}")
