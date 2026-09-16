import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cre.adapters import JsonFileStore
from cre.engine import ResearchEngine, ResearchRequest, project_research
from cre.models import Party, ResearchPlan, ResearchUnit
from cre.ports.llm import LLMTurn, ToolCall


class PhaseLLM:
    def __init__(self, fail_expansion_once=False):
        self.fail_expansion_once = fail_expansion_once
        self.modes = []

    @staticmethod
    def mode(system):
        if "EXPANSION" in system:
            return "expansion"
        if "COLLISION" in system:
            return "collision"
        if "STABILITY CHECK" in system:
            return "stability"
        return "continuous"

    @staticmethod
    def conclusion(stable=False):
        return {
            "summary": "done", "attempted": "contract", "changed": "state",
            "remaining_unknowns": "none", "why_stop": "done",
            "next_pass": "none", "no_high_value_direction": stable,
        }

    async def run(self, messages, tools=None):
        mode = self.mode(messages[0]["content"])
        self.modes.append(mode)
        names = {item.get("function", {}).get("name") for item in (tools or [])}
        plan_args = {
            "phase": mode, "question_interpretation": "fixture interpretation",
            "winning_condition": "finish phase", "strategy": "fixture strategy",
            "route_hypotheses": ["route"],
            "next_actions": [{"action": "work", "purpose": "finish", "expected_gain": "state", "stop_or_pivot_if": "done"}],
            "stopping_conditions": ["phase done"], "completed": [], "abandoned": [],
            "remaining_work": "phase work", "progress_assessment": "planned",
            "estimated_remaining_actions": 1, "status": "active", "change_reason": "new phase",
        }
        if names == {"update_plan"}:
            return LLMTurn(tool_calls=[ToolCall("p", "update_plan", plan_args)])
        if mode == "expansion" and self.fail_expansion_once:
            self.fail_expansion_once = False
            raise ConnectionError("simulated interruption")
        if mode == "expansion":
            plan_args.update(status="ready_to_conclude", next_actions=[], remaining_work="none", completed=["phase"])
            return LLMTurn(tool_calls=[
                ToolCall("p2", "update_plan", plan_args),
                ToolCall("u", "update_unit", {"content": "research", "status": "tentative"}),
                ToolCall("m", "update_map", {"title": "map", "status": "resolved"}),
                ToolCall("c", "conclude_pass", self.conclusion()),
            ])
        if mode == "stability":
            return LLMTurn(tool_calls=[ToolCall("s", "answer_stability", {"has_direction": False})])
        plan_args.update(status="ready_to_conclude", next_actions=[], remaining_work="none", completed=["phase"])
        return LLMTurn(tool_calls=[
            ToolCall("p2", "update_plan", plan_args),
            ToolCall("c", "conclude_pass", self.conclusion(mode == "continuous")),
        ])


class TextOnlyLLM:
    async def run(self, messages, tools=None):
        return LLMTurn(text="unstructured")


class TestResearchEngineService(unittest.IsolatedAsyncioTestCase):
    async def test_budget_exhaustion_never_commits_phase_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            store = JsonFileStore(path)
            engine = ResearchEngine(store=store, llm_a=TextOnlyLLM(), llm_b=TextOnlyLLM())
            session = await engine.create(ResearchRequest(
                session_id="research-incomplete", question="Should X be adopted?",
            ))
            session.budget.max_model_turns_per_pass = 1
            await store.save_session(session)
            with self.assertRaisesRegex(RuntimeError, "before quality gates"):
                await engine.run(session.session_id)
            restored = JsonFileStore(path)
            saved = await restored.load_session(session.session_id)
            self.assertNotIn("expansion", saved.phase_progress)

    async def test_json_store_roundtrip_preserves_engine_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            store = JsonFileStore(path)
            engine = ResearchEngine(store=store, llm_a=PhaseLLM(), llm_b=PhaseLLM())
            session = await engine.create(ResearchRequest(
                session_id="research-roundtrip", question="Should X be adopted?",
                profile="standard",
            ))
            session.phase_progress["expansion"] = ["A"]
            await store.save_session(session)
            await store.save_unit(ResearchUnit("ru_a_0001", content="durable"), session.session_id, Party.A)
            await store.save_plan(
                ResearchPlan(
                    plan_id="plan_a", phase="expansion",
                    question_interpretation="fixture", winning_condition="win",
                    strategy="adaptive", next_actions=[{"action": "x"}],
                    stopping_conditions=["done"], remaining_work="x",
                    progress_assessment="starting", estimated_remaining_actions=1,
                ),
                session.session_id, Party.A,
            )

            restored = JsonFileStore(path)
            restored_session = await restored.load_session(session.session_id)
            self.assertEqual(restored_session.phase_progress, {"expansion": ["A"]})
            self.assertEqual((await restored.load_unit("ru_a_0001")).content, "durable")
            self.assertEqual((await restored.load_plan(session.session_id, Party.A)).strategy, "adaptive")
            self.assertEqual(engine.capabilities().deep_research_gaps(), ["web_search", "source_reading"])

            projection = await project_research(restored, session.session_id)
            self.assertEqual(projection["contract_version"], "2")
            self.assertEqual(projection["units"]["A"][0]["content"], "durable")
            self.assertEqual(projection["plans"]["A"]["strategy"], "adaptive")

    async def test_resume_skips_party_with_committed_expansion_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            first_a, first_b = PhaseLLM(), PhaseLLM(fail_expansion_once=True)
            store = JsonFileStore(path)
            engine = ResearchEngine(store=store, llm_a=first_a, llm_b=first_b)
            session = await engine.create(ResearchRequest(
                session_id="research-resume", question="Should X be adopted?",
            ))
            session.budget.min_sources_per_agent = 0
            session.budget.min_examined_sources_per_agent = 0
            session.budget.min_core_arguments_per_agent = 0
            session.budget.min_rebuttals_per_agent = 0
            session.budget.argument_first_gate = False
            session.budget.max_cycles = 1
            await store.save_session(session)
            with self.assertRaises(ConnectionError):
                await engine.run(session.session_id)

            checkpointed = JsonFileStore(path)
            partial = await checkpointed.load_session(session.session_id)
            self.assertEqual(partial.phase_progress.get("expansion"), ["A"])

            resumed_a, resumed_b = PhaseLLM(), PhaseLLM()
            resumed = ResearchEngine(
                store=checkpointed, llm_a=resumed_a, llm_b=resumed_b
            )
            await resumed.run(session.session_id)
            self.assertNotIn("expansion", resumed_a.modes)
            self.assertIn("expansion", resumed_b.modes)


if __name__ == "__main__":
    unittest.main()
