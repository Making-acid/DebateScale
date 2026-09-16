"""End-to-end demo: drive the engine through a full run with a scripted mock LLM.

Run with:  python examples/run_demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cre.adapters import InMemoryStore
from cre.engine import MutationLog, Runtime, build_semantic_diff
from cre.models import Party, ResearchBudget, ResearchSession, SessionStatus
from cre.ports.llm import LLMTurn, ToolCall
from cre.ports.search import SearchResult

QUESTION = "表情包是否丰富了我们的表达？"


class DemoSearch:
    async def search(self, query: str, n: int = 3) -> list[SearchResult]:
        return [
            SearchResult(
                title="表情包使用频率与语言表达研究报告",
                url="https://example.com/paper1",
                snippet="对 2000 名受访者的调查显示，表情包使用与情绪表达效率相关。",
            ),
            SearchResult(
                title="数字沟通中的语义稀释",
                url="https://example.com/paper2",
                snippet="有学者指出，过度依赖表情包可能降低词汇选择的精确性。",
            ),
        ]


class DemoLLM:
    def __init__(self):
        self._count: dict[tuple[str, str], int] = {}

    def _detect(self, messages):
        system = messages[0]["content"]
        agent = "A" if "Position Advocate A" in system else "B"
        if "EXPANSION" in system:
            mode = "expansion"
        elif "COLLISION" in system:
            mode = "collision"
        elif "STABILITY CHECK" in system:
            mode = "stability_check"
        else:
            mode = "continuous"
        return mode, agent

    @staticmethod
    def _conclusion(summary: str, stable: bool) -> dict:
        return {
            "summary": summary,
            "attempted": "completed the phase contract",
            "changed": "updated the integrated research skeleton",
            "remaining_unknowns": "preserved in the research map",
            "why_stop": "the current pass objective is complete",
            "next_pass": "investigate the highest-value evidence gap",
            "no_high_value_direction": stable,
        }

    async def run(self, messages, tools=None):
        mode, agent = self._detect(messages)
        key = (mode, agent)
        n = self._count.get(key, 0)
        self._count[key] = n + 1
        return self._turn(mode, agent, n)

    def _turn(self, mode, agent, n):
        if mode == "expansion" and n == 0:
            return LLMTurn(
                tool_calls=[
                    ToolCall(id=f"{agent}-s", name="search", arguments={"query": "表情包 表达 研究", "n": 3})
                ]
            )
        if mode == "expansion":
            return LLMTurn(
                tool_calls=[
                    ToolCall(
                        id=f"{agent}-u",
                        name="update_unit",
                        arguments={
                            "content": f"# 表情包与表达\n\n初步发现（{agent}）：表情包降低了部分日常表达的门槛。",
                            "status": "tentative",
                            "what_changed": "initial unit",
                        },
                    ),
                    ToolCall(
                        id=f"{agent}-m",
                        name="update_map",
                        arguments={"title": "词汇精确性是否下降", "status": "active", "importance": "medium"},
                    ),
                    ToolCall(
                        id=f"{agent}-c",
                        name="conclude_pass",
                        arguments=self._conclusion("expansion complete", False),
                    ),
                ]
            )
        if mode == "collision":
            return LLMTurn(
                tool_calls=[
                    ToolCall(
                        id=f"{agent}-c",
                        name="conclude_pass",
                        arguments=self._conclusion("collision complete", False),
                    )
                ]
            )
        if mode == "stability_check":
            return LLMTurn(
                tool_calls=[
                    ToolCall(
                        id=f"{agent}-a",
                        name="answer_stability",
                        arguments={"has_direction": False, "direction": ""},
                    )
                ]
            )
        # continuous
        return LLMTurn(
            tool_calls=[
                ToolCall(
                    id=f"{agent}-u",
                    name="update_unit",
                    arguments={
                        "content": f"# 表情包与表达\n\n深化（{agent}）：低可解释性条件下，可见的短期好感下降可能增加沟通压力。",
                        "status": "stable",
                        "what_changed": "claim narrowed",
                        "why": "new longitudinal evidence",
                    },
                ),
                ToolCall(
                    id=f"{agent}-c",
                    name="conclude_pass",
                    arguments=self._conclusion("no high-value direction remains", True),
                ),
            ]
        )


async def main():
    store = InMemoryStore()
    session = ResearchSession(
        session_id="demo",
        question=QUESTION,
        position_a="表情包丰富了我们的表达",
        position_b="表情包虚泛了我们的表达",
        status=SessionStatus.CREATED,
        budget=ResearchBudget(
            min_sources_per_agent=0,
            min_examined_sources_per_agent=0,
            min_core_arguments_per_agent=0,
            min_rebuttals_per_agent=0,
        ),
    )
    await store.save_session(session)

    runtime = Runtime(store=store, llm=DemoLLM(), search=DemoSearch())
    result = await runtime.run("demo")

    print("=" * 60)
    print(f"final status: {result.status.value}  (cycles={result.current_cycle})")
    print("=" * 60)

    log = MutationLog(store, "demo")
    mutations = await log.list()
    print("\n--- mutation log ---")
    for m in mutations:
        print(
            f"  #{m.seq} pass{m.pass_no} {m.agent.value} {m.action.value}"
            f"{' -> ' + m.target.id if m.target else ''}"
        )

    print("\n--- semantic diff (pass 5) ---")
    print(build_semantic_diff(await log.list(5), Party.A, 5))

    print("--- A's units ---")
    for u in await store.list_units("demo", Party.A):
        print(f"  {u.unit_id} [{u.status.value}] {u.content.splitlines()[0]}")

    print("--- B's units ---")
    for u in await store.list_units("demo", Party.B):
        print(f"  {u.unit_id} [{u.status.value}] {u.content.splitlines()[0]}")

    print("--- map entries ---")
    for a in (Party.A, Party.B):
        for e in await store.list_map_entries("demo", a):
            print(f"  {a.value} {e.map_id} [{e.status.value}] {e.title}")

    print("--- shared sources ---")
    for s in await store.list_sources("demo"):
        print(f"  {s.source_id} {s.title}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
