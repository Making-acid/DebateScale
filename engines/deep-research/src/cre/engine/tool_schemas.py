"""Tool schemas for engine actions (OpenAI function format).

Engine actions are exposed to the model as tools; Pass-internal tools (search,
read, etc.) come from the ports and are merged by the runtime.
"""

from __future__ import annotations

from ..prompt_loader import load_prompt

ENGINE_ACTION_NAMES = [
    "update_plan",
    "update_unit",
    "update_map",
    "create_issue",
    "respond_issue",
    "close_issue",
    "conclude_pass",
    "update_argument",
    "update_rebuttal",
    "record_evidence",
]


def _fn(name: str, description: str, properties: dict, required: list) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


ENGINE_ACTION_TOOLS: list[dict] = [
    _fn(
        "update_plan",
        load_prompt("tools/update_plan.md"),
        {
            "phase": {"type": "string", "enum": ["expansion", "collision", "continuous"]},
            "question_interpretation": {"type": "string"},
            "winning_condition": {"type": "string"},
            "strategy": {"type": "string"},
            "route_hypotheses": {"type": "array", "items": {"type": "string"}},
            "next_actions": {
                "type": "array", "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"}, "purpose": {"type": "string"},
                        "expected_gain": {"type": "string"},
                        "stop_or_pivot_if": {"type": "string"},
                    },
                    "required": ["action", "purpose", "expected_gain", "stop_or_pivot_if"],
                },
            },
            "stopping_conditions": {"type": "array", "items": {"type": "string"}},
            "completed": {"type": "array", "items": {"type": "string"}},
            "abandoned": {"type": "array", "items": {"type": "string"}},
            "remaining_work": {"type": "string"},
            "progress_assessment": {"type": "string"},
            "estimated_remaining_actions": {"type": "integer", "minimum": -1, "maximum": 30},
            "status": {"type": "string", "enum": ["active", "ready_to_conclude"]},
            "change_reason": {"type": "string"},
            "what_changed": {"type": "string"}, "why": {"type": "string"},
        },
        [
            "phase", "question_interpretation", "winning_condition", "strategy",
            "next_actions", "stopping_conditions", "remaining_work",
            "progress_assessment", "estimated_remaining_actions", "status",
            "change_reason",
        ],
    ),
    _fn(
        "update_unit",
        load_prompt("tools/update_unit.md"),
        {
            "unit_id": {"type": "string"},
            "content": {"type": "string"},
            "status": {"type": "string", "enum": ["tentative", "stable"]},
            "source_ids": {"type": "array", "items": {"type": "string"}},
            "what_changed": {"type": "string"},
            "why": {"type": "string"},
        },
        [],
    ),
    _fn(
        "update_map",
        load_prompt("tools/update_map.md"),
        {
            "map_id": {"type": "string"},
            "title": {"type": "string"},
            "status": {"type": "string", "enum": ["active", "dormant", "resolved"]},
            "importance": {"type": "string"},
            "coverage": {"type": "string"},
            "uncertainty": {"type": "string"},
            "note": {"type": "string"},
            "proof_obligation": {"type": "string"},
            "externally_blocked": {"type": "boolean"},
            "blocker_reason": {"type": "string"},
            "what_changed": {"type": "string"},
            "why": {"type": "string"},
        },
        [],
    ),
    _fn(
        "record_evidence",
        load_prompt("tools/record_evidence.md"),
        {
            "evidence_id": {"type": "string"},
            "source_id": {"type": "string"},
            "argument_id": {"type": "string"},
            "proposition": {"type": "string"},
            "finding": {"type": "string"},
            "method": {"type": "string"},
            "limitations": {"type": "string"},
            "relation": {"type": "string", "enum": ["supports", "challenges", "limits"]},
            "provenance": {"type": "string"},
            "status": {"type": "string", "enum": ["examined", "admitted", "rejected"]},
            "what_changed": {"type": "string"},
            "why": {"type": "string"},
        },
        ["source_id", "proposition", "finding", "method", "limitations", "provenance"],
    ),
    _fn(
        "update_argument",
        load_prompt("tools/update_argument.md"),
        {
            "argument_id": {"type": "string"},
            "title": {"type": "string"},
            "claim": {"type": "string"},
            "burden": {"type": "string"},
            "criterion": {"type": "string"},
            "warrant": {"type": "array", "items": {"type": "string"}},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "material_source_ids": {
                "type": "array", "items": {"type": "string"},
                "description": "Prior debates, public reasoning, examples, analogies, or objections that helped build or test the argument; these are inspiration, not factual proof.",
            },
            "support_type": {
                "type": "string",
                "enum": ["reasoning", "mixed", "empirical"],
                "description": "Whether the argument is carried by reasoning/value judgment, a mixture, or an empirical claim.",
            },
            "evidence_need": {
                "type": "array", "items": {"type": "string"},
                "description": "Only the load-bearing factual premises that genuinely require external verification.",
            },
            "impact": {"type": "string"},
            "scope": {"type": "string"},
            "original_contribution": {
                "type": "string",
                "description": "What this argument newly contributes beyond a stock case: a distinctive inferential link, framing, comparison, boundary, counterexample, or defensive repair, and why it improves the chance of winning. Be honest if it is a necessary conventional foundation.",
            },
            "vulnerabilities": {"type": "array", "items": {"type": "string"}},
            "defense": {"type": "array", "items": {"type": "string"}},
            "status": {"type": "string", "enum": ["draft", "defensible", "withdrawn"]},
            "what_changed": {"type": "string"},
            "why": {"type": "string"},
        },
        [],
    ),
    _fn(
        "update_rebuttal",
        load_prompt("tools/update_rebuttal.md"),
        {
            "rebuttal_id": {"type": "string"},
            "target_agent": {"type": "string", "enum": ["A", "B"]},
            "target_argument_id": {"type": "string"},
            "target_version": {"type": "integer"},
            "title": {"type": "string"},
            "reconstruction": {"type": "string"},
            "attack_type": {"type": "string"},
            "attack": {"type": "string"},
            "why_it_matters": {"type": "string"},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "likely_response": {"type": "string"},
            "current_effect": {"type": "string"},
            "status": {"type": "string", "enum": ["active", "answered", "survives", "withdrawn"]},
            "what_changed": {"type": "string"},
            "why": {"type": "string"},
        },
        ["target_agent", "target_argument_id", "title", "reconstruction", "attack_type", "attack", "why_it_matters"],
    ),
    _fn(
        "create_issue",
        load_prompt("tools/create_issue.md"),
        {
            "to": {"type": "string", "enum": ["A", "B", "H"]},
            "target": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "id": {"type": "string"},
                    "section": {"type": "string"},
                },
                "required": ["type", "id"],
            },
            "priority": {"type": "string", "enum": ["low", "medium", "high"]},
            "title": {"type": "string"},
            "body": {"type": "string"},
        },
        ["target"],
    ),
    _fn(
        "respond_issue",
        load_prompt("tools/respond_issue.md"),
        {
            "issue_id": {"type": "string"},
            "response": {"type": "string"},
            "what_changed": {"type": "string"},
            "why": {"type": "string"},
        },
        ["issue_id"],
    ),
    _fn(
        "close_issue",
        load_prompt("tools/close_issue.md"),
        {
            "issue_id": {"type": "string"},
            "resolution": {
                "type": "string",
                "enum": [
                    "resolved",
                    "withdrawn",
                    "clarified",
                    "unresolved",
                    "disagreement",
                    "superseded",
                ],
            },
            "what_changed": {"type": "string"},
            "why": {"type": "string"},
        },
        ["issue_id"],
    ),
    _fn(
        "conclude_pass",
        load_prompt("tools/conclude_pass.md"),
        {
            "summary": {"type": "string"},
            "attempted": {"type": "string"},
            "changed": {"type": "string"},
            "remaining_unknowns": {"type": "string"},
            "why_stop": {"type": "string"},
            "next_pass": {"type": "string"},
            "no_high_value_direction": {"type": "boolean"},
        },
        [
            "summary",
            "attempted",
            "changed",
            "remaining_unknowns",
            "why_stop",
            "next_pass",
            "no_high_value_direction",
        ],
    ),
]


def search_tool_schema() -> dict:
    return _fn(
        "search",
        load_prompt("tools/search.md"),
        {
            "query": {
                "type": "string",
                "description": "The actual web query, using the likely source's terminology and language.",
            },
            "purpose": {
                "type": "string",
                "description": "The exact proof obligation, evidence gap, or uncertainty this search should reduce.",
            },
            "strategy": {
                "type": "string",
                "description": "A short name and rationale for the chosen search approach; free-form strategies are allowed.",
            },
            "search_mode": {
                "type": "string",
                "enum": ["argument_discovery", "fact_verification"],
                "description": "Discover debate ideas/precedents/public reasoning, or verify one load-bearing factual premise.",
            },
            "discovery_kind": {
                "type": "string",
                "enum": [
                    "exact_motion", "adjacent_motion", "public_reasoning",
                    "concept_example", "not_applicable",
                ],
                "description": "For argument discovery, identify the discovery route. Use not_applicable only for fact verification.",
            },
            "n": {"type": "integer"},
        },
        ["query", "purpose", "strategy", "search_mode", "discovery_kind"],
    )


def read_source_tool_schema() -> dict:
    return _fn(
        "read_source",
        load_prompt("tools/read_source.md"),
        {
            "source_id": {"type": "string"},
            "purpose": {
                "type": "string",
                "description": "The exact proposition, mechanism, method, or limitation this reading must verify.",
            },
            "focus_terms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional source terminology, variables, populations, methods, or section names for passage selection.",
            },
        },
        ["source_id", "purpose"],
    )


def transcribe_source_tool_schema() -> dict:
    return _fn(
        "transcribe_source",
        load_prompt("tools/transcribe_source.md"),
        {
            "source_id": {"type": "string"},
            "purpose": {
                "type": "string",
                "description": "The existing argument, clash, or objection this transcript could improve.",
            },
            "language": {"type": "string"},
            "max_duration_seconds": {
                "type": "integer", "minimum": 60, "maximum": 5400,
                "description": "Reject longer media instead of silently starting an unbounded ASR job.",
            },
            "focus_terms": {
                "type": "array", "items": {"type": "string"},
            },
        },
        ["source_id", "purpose"],
    )


def stability_tool_schema() -> dict:
    return _fn(
        "answer_stability",
        load_prompt("tools/stability_check.md"),
        {
            "has_direction": {"type": "boolean"},
            "direction": {"type": "string"},
        },
        ["has_direction"],
    )
