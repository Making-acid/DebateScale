"""Engine layer: mechanical action application, mutation log, projections, runtime."""

from .actions import apply_action
from .blackboard import (
    map_from_markdown,
    map_to_markdown,
    unit_from_markdown,
    unit_to_markdown,
)
from .budget import PassBudget, PassUsage
from .capabilities import EngineCapabilities, inspect_capabilities
from .mutation_log import MutationLog, now_iso
from .runtime import Runtime
from .projection import project_research
from .reporting import build_editorial_packet, compile_reader_report
from .service import ResearchEngine, ResearchRequest, research_budget
from .profiles import ResearchProfilePolicy, research_policy
from .semantic_diff import build_semantic_diff
from .state_machine import evaluate_candidate_stable

__all__ = [
    "MutationLog",
    "EngineCapabilities",
    "PassBudget",
    "PassUsage",
    "Runtime",
    "ResearchEngine",
    "ResearchRequest",
    "apply_action",
    "build_semantic_diff",
    "evaluate_candidate_stable",
    "inspect_capabilities",
    "map_from_markdown",
    "map_to_markdown",
    "now_iso",
    "research_budget",
    "research_policy",
    "ResearchProfilePolicy",
    "project_research",
    "build_editorial_packet",
    "compile_reader_report",
    "unit_from_markdown",
    "unit_to_markdown",
]
