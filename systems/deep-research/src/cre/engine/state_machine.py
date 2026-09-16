"""State transitions and the mechanical CANDIDATE_STABLE signal.

The runtime checks signals and switches states; it does not judge research value.
``evaluate_candidate_stable`` encodes only the mechanical condition from the
design doc: both agents concluded with no high-value direction, and there is no
high-priority open issue or high-importance active map branch.
"""

from __future__ import annotations

from ..models import EngineAction, Mutation, Party, ResearchSession, SessionStatus
from ..ports.store import StorePort


def last_conclude_pass(mutations: list[Mutation], agent: Party) -> Mutation | None:
    for m in reversed(mutations):
        if m.agent is agent and m.action == EngineAction.CONCLUDE_PASS:
            return m
    return None


async def evaluate_candidate_stable(
    store: StorePort,
    session: ResearchSession,
    mutations: list[Mutation],
) -> bool:
    agents = session.agents
    for agent in agents:
        last = last_conclude_pass(mutations, agent)
        if last is None:
            return False
        if not last.payload.get("no_high_value_direction"):
            return False

    open_issues = [
        i for i in await store.list_issues(session.session_id) if i.state.value == "open"
    ]
    if any(i.priority == "high" for i in open_issues):
        return False

    for agent in agents:
        entries = await store.list_map_entries(session.session_id, agent)
        # Needing more searchable evidence is not a stopping reason. A high-value
        # proof obligation remains blocking even when an agent labels it dormant;
        # only a concrete external blocker can move it out of the engine.
        if any(
            e.status.value != "resolved"
            and e.importance == "high"
            and not e.externally_blocked
            for e in entries
        ):
            return False

        if session.budget.min_core_arguments_per_agent:
            arguments = await store.list_arguments(session.session_id, agent)
            viable = [item for item in arguments if item.status.value != "withdrawn"]
            if len(viable) < session.budget.min_core_arguments_per_agent:
                return False
            if any(
                item.status.value != "defensible" or item.missing_proof_fields()
                for item in viable
            ):
                return False

        if session.budget.min_rebuttals_per_agent:
            rebuttals = await store.list_rebuttals(session.session_id, agent)
            complete = [item for item in rebuttals if not item.missing_fields()]
            if len(complete) < session.budget.min_rebuttals_per_agent:
                return False

    # An unanswered attack against the opponent's *current* argument revision is
    # a live hole in the case. Attacks against older revisions remain in history,
    # but do not block convergence because the target text has already changed.
    for agent in agents:
        for rebuttal in await store.list_rebuttals(session.session_id, agent):
            if rebuttal.status.value != "active":
                continue
            target = await store.load_argument(rebuttal.target_argument_id)
            if target is not None and target.version == rebuttal.target_version:
                return False

    return True
