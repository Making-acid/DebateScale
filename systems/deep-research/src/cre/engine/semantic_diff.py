"""Semantic Diff: aggregate one pass's mutations into an opponent-facing summary.

The opponent reads *what changed and why* — the cognitive version history — not
the raw text diff. Raw Git diff remains available as a fallback for wording.
"""

from __future__ import annotations

from ..models import EngineAction, Mutation, Party


def build_semantic_diff(mutations: list[Mutation], agent: Party, pass_no: int) -> str:
    lines: list[str] = [f"{agent.value} Pass #{pass_no}", ""]
    if not mutations:
        lines.append("(no persistent changes)")
        return "\n".join(lines)

    for m in sorted(mutations, key=lambda x: x.seq):
        if m.action == EngineAction.UPDATE_UNIT:
            ref = m.target.id if m.target else "?"
            lines.append(f"{ref}:")
            lines.append(f"  {m.what_changed or '(updated)'}")
            if m.why:
                lines.append(f"  why: {m.why}")
        elif m.action == EngineAction.UPDATE_MAP:
            ref = m.target.id if m.target else "?"
            lines.append(f"{ref}:")
            lines.append(f"  {m.what_changed or '(updated)'}")
            if m.why:
                lines.append(f"  why: {m.why}")
        elif m.action == EngineAction.CREATE_ISSUE:
            ref = m.target.id if m.target else "?"
            lines.append(f"{ref}:")
            lines.append(f"  created: {m.what_changed or m.payload.get('title', '')}")
        elif m.action == EngineAction.RESPOND_ISSUE:
            ref = m.target.id if m.target else "?"
            lines.append(f"{ref}:")
            lines.append("  responded")
        elif m.action == EngineAction.CLOSE_ISSUE:
            ref = m.target.id if m.target else "?"
            res = m.payload.get("resolution", "")
            lines.append(f"{ref}:")
            lines.append(f"  closed ({res})" if res else "  closed")
        elif m.action == EngineAction.CONCLUDE_PASS:
            lines.append("pass concluded:")
            summary = m.payload.get("summary") or m.what_changed
            lines.append(f"  {summary}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
