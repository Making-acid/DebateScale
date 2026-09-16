"""Compose the system prompt from independently editable prompt resources."""

from __future__ import annotations

from ..models import Party
from ..prompt_loader import load_prompt, render_prompt

_MODE_PROMPTS = {
    "expansion": "phases/expansion.md",
    "collision": "phases/collision.md",
    "continuous": "phases/continuous.md",
    "stability_check": "phases/stability_check.md",
}

_COMMON_PROMPTS = (
    "common/duties.md",
    "common/principles.md",
    "common/search_strategy.md",
    "common/exit_audit.md",
    "common/workflow.md",
)


def build_system_prompt(mode: str, agent: Party, question: str, position: str = "") -> str:
    phase_name = _MODE_PROMPTS.get(mode, _MODE_PROMPTS["continuous"])
    return "\n\n".join(
        (
            render_prompt(
                "identity.md",
                agent=agent.value,
                question=question,
                position=position,
            ),
            load_prompt(phase_name),
            *(load_prompt(name) for name in _COMMON_PROMPTS),
        )
    )
