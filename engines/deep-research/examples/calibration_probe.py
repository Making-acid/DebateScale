"""Low-budget one-side calibration run for prompt and behavior tuning.

Uses the saved provider configuration without printing credentials. The probe is
deliberately not a product workflow: it stops after a small number of turns and
writes an auditable JSON trace under web/.local/experiments.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cre.adapters import DuckDuckGoSearch, JsonFileStore, create_debate_llms
from cre.engine import MutationLog, Runtime
from cre.engine.runtime import PassBudgetExhausted
from cre.models import Party, ResearchBudget, ResearchSession, SessionStatus


async def run_probe(
    question: str, position: str, max_tokens: int, resume: str = ""
) -> int:
    config_path = ROOT / "web" / ".local" / "model_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    session_id = resume.strip() or f"probe-{uuid.uuid4().hex[:10]}"
    output_dir = ROOT / "web" / ".local" / "experiments" / session_id
    output_dir.mkdir(parents=True, exist_ok=True)
    store = JsonFileStore(output_dir / "state.json")
    session = await store.load_session(session_id) if resume.strip() else None
    if session is None:
        session = ResearchSession(
            session_id=session_id,
            question=question,
            position_a=position,
            position_b=f"反对命题：{question}",
            agents=[Party.A],
            status=SessionStatus.CREATED,
            budget=ResearchBudget(
                max_tool_calls_per_pass=6,
                max_failed_tool_calls_per_pass=3,
                max_parallel_research_actions_per_turn=2,
                max_tokens_per_pass=max_tokens,
                max_model_turns_per_pass=8,
                max_unproductive_turns_per_pass=3,
                max_tokens_without_state_progress=24_000,
                min_token_reserve_per_model_turn=10_000,
                max_cycles=0,
                min_sources_per_agent=0,
                min_examined_sources_per_agent=0,
                min_core_arguments_per_agent=3,
                min_rebuttals_per_agent=0,
            ),
        )
    else:
        # A resumed calibration is a fresh bounded observation window over the
        # same durable research state, not a reset of the research itself.
        session.budget.max_tokens_per_pass = max_tokens
        session.budget.max_model_turns_per_pass = 8
    await store.save_session(session)
    llm_a, _ = create_debate_llms(config)
    trace_path = output_dir / "trace.jsonl"
    last_budget: dict = {}

    def progress(update: dict) -> None:
        nonlocal last_budget
        if isinstance(update.get("budget"), dict):
            last_budget = dict(update["budget"])
        with trace_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(update, ensure_ascii=False, default=str) + "\n")
        event = update.get("event") or {}
        if event.get("kind") in {
            "model", "decision", "argument", "unit", "map", "search", "read",
            "gate", "early_stop", "pass",
        } and event.get("status") != "working":
            print(json.dumps({
                "kind": event.get("kind"),
                "title": event.get("title"),
                "summary": event.get("summary"),
                "tokens": last_budget.get("tokens", 0),
            }, ensure_ascii=False), flush=True)

    runtime = Runtime(
        store=store,
        llm=llm_a,
        search=DuckDuckGoSearch(timeout=min(float(config.get("timeout_seconds", 120)), 30)),
        progress_callback=progress,
    )
    runtime.log = MutationLog(store, session_id)
    outcome = "completed"
    try:
        await runtime._run_pass(session, Party.A, 1, "expansion")
    except PassBudgetExhausted as exc:
        outcome = str(exc)
    arguments = await store.list_arguments(session_id, Party.A)
    sources = await store.list_sources(session_id)
    result = {
        "session_id": session_id,
        "outcome": outcome,
        "budget": last_budget,
        "arguments": [
            {
                "id": item.argument_id,
                "title": item.title,
                "support_type": item.support_type,
                "evidence_need": item.evidence_need,
                "warrant_steps": len(item.warrant),
                "original_contribution": item.original_contribution,
                "material_source_ids": item.material_source_ids,
            }
            for item in arguments
        ],
        "sources": [
            {
                "id": item.source_id,
                "title": item.title,
                "url": item.url,
                "type": item.source_type,
                "access_tier": item.metadata.get("access_tier", "unknown"),
                "readability": item.metadata.get("expected_readability", "unknown"),
                "structured_reader": item.metadata.get("structured_reader", ""),
                "characters": len(item.content),
                "investigated": Party.A in item.investigated_by,
                "read_error": item.metadata.get("last_read_error", ""),
            }
            for item in sources
        ],
        "trace": str(trace_path),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Windows consoles commonly use a legacy code page; escaped output keeps a
    # source-title emoji from hiding an otherwise successful diagnostic.
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", default="爱情是人类的必需品吗？")
    parser.add_argument("--position", default="爱情是人类的必需品")
    parser.add_argument("--max-tokens", type=int, default=48_000)
    parser.add_argument("--resume", default="", help="Resume an experiment session id")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(
        run_probe(args.question, args.position, args.max_tokens, args.resume)
    ))


if __name__ == "__main__":
    main()
