"""Explicit research policies for the public execution profiles.

Profiles share adapters, storage and the phase runner.  They do not silently
inherit their research behaviour from a handful of budget numbers: the policy
also names the intended depth and gives the advocate a compact operating
contract.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import ResearchBudget


@dataclass(frozen=True)
class ResearchProfilePolicy:
    name: str
    label: str
    guidance: str
    budget: ResearchBudget


_PROFILES = {
    "standard": ResearchProfilePolicy(
        name="standard",
        label="标准研究",
        guidance=(
            "PROFILE: STANDARD. Build a compact, complete debate case. Prefer two or three "
            "distinct load-bearing arguments, one precise rebuttal for every live "
            "opponent argument, and only the external checks needed by factual premises. "
            "Completeness and a clean handoff matter more than exploring every plausible route."
        ),
        budget=ResearchBudget(
            max_tool_calls_per_pass=36, max_tokens_per_pass=400_000,
            max_failed_tool_calls_per_pass=10,
            max_parallel_research_actions_per_turn=2,
            max_model_turns_per_pass=48,
            max_unproductive_turns_per_pass=5,
            max_tokens_without_state_progress=45_000,
            min_token_reserve_per_model_turn=16_000,
            max_cycles=1, min_sources_per_agent=0,
            min_examined_sources_per_agent=0, min_core_arguments_per_agent=2,
            min_rebuttals_per_agent=2,
        ),
    ),
    "deep": ResearchProfilePolicy(
        name="deep",
        label="深度研究",
        guidance=(
            "PROFILE: DEEP. Depth means stronger argumentative coverage, not longer "
            "wandering. Build four genuinely different load-bearing argument routes, "
            "inspect prior debate/public reasoning once, and selectively verify only "
            "named factual premises. Stress-test boundaries and ordinary objections, "
            "incorporate what changes the case, and stop when further work repeats an "
            "existing route. Never spend the larger allowance merely because it exists."
        ),
        budget=ResearchBudget(
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
        ),
    ),
}


def research_policy(name: str) -> ResearchProfilePolicy:
    try:
        return _PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"unknown research profile: {name}") from exc
