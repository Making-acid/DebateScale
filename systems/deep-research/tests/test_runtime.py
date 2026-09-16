import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cre.adapters import InMemoryStore
from cre.engine import MutationLog, Runtime, apply_action
from cre.engine.budget import PassBudget
from cre.engine.runtime import PassBudgetExhausted, _canonical_tool_name
from cre.engine.state_machine import evaluate_candidate_stable
from cre.engine.tool_schemas import read_source_tool_schema, search_tool_schema
from cre.models import (
    Argument,
    EngineAction,
    MapStatus,
    Mutation,
    Party,
    Rebuttal,
    ResearchBudget,
    ResearchMapEntry,
    ResearchPlan,
    ResearchSession,
    ResearchUnit,
    SessionStatus,
    Source,
)
from cre.prompt_loader import load_prompt, render_prompt
from cre.ports.llm import LLMTurn, ToolCall
from cre.ports.search import SearchResult
from cre.skills import build_system_prompt


class MockLLM:
    """Stateless scripted model keyed by the mode embedded in the system prompt."""

    def _mode(self, system: str) -> str:
        if "EXPANSION" in system:
            return "expansion"
        if "COLLISION" in system:
            return "collision"
        if "STABILITY CHECK" in system:
            return "stability_check"
        return "continuous"

    @staticmethod
    def _conclusion(summary: str, stable: bool) -> dict:
        return {
            "summary": summary,
            "attempted": "completed the phase contract",
            "changed": "updated durable research state",
            "remaining_unknowns": "documented in the research map",
            "why_stop": "current pass objective is complete",
            "next_pass": "follow the highest-value map branch",
            "no_high_value_direction": stable,
        }

    async def run(self, messages, tools=None):
        mode = self._mode(messages[0]["content"])
        names = {item.get("function", {}).get("name") for item in (tools or [])}
        if names == {"update_plan"}:
            return LLMTurn(tool_calls=[ToolCall(
                id="plan", name="update_plan", arguments={
                    "phase": mode,
                    "question_interpretation": "interpret the motion from this fixed position",
                    "winning_condition": "build a defensible comparative case",
                    "strategy": "choose the highest-value unresolved case route",
                    "route_hypotheses": ["core route"],
                    "next_actions": [{
                        "action": "build case", "purpose": "satisfy this phase",
                        "expected_gain": "durable case progress",
                        "stop_or_pivot_if": "the phase contract is satisfied",
                    }],
                    "stopping_conditions": ["phase contract satisfied"],
                    "completed": [], "abandoned": [],
                    "remaining_work": "complete the phase",
                    "progress_assessment": "initial plan",
                    "estimated_remaining_actions": 2, "status": "active",
                    "change_reason": "new phase",
                },
            )])
        ready_plan = ToolCall(
            id="plan-ready", name="update_plan", arguments={
                "phase": mode,
                "question_interpretation": "interpret the motion from this fixed position",
                "winning_condition": "build a defensible comparative case",
                "strategy": "phase work is complete",
                "route_hypotheses": ["core route"], "next_actions": [],
                "stopping_conditions": ["phase contract satisfied"],
                "completed": ["phase contract"], "abandoned": [],
                "remaining_work": "none",
                "progress_assessment": "ready to conclude",
                "estimated_remaining_actions": 0, "status": "ready_to_conclude",
                "change_reason": "exit audit passed",
            },
        )
        if mode == "expansion":
            return LLMTurn(
                tool_calls=[
                    ToolCall(
                        id="t1",
                        name="update_unit",
                        arguments={
                            "content": "# Finding\n\nsomething",
                            "status": "tentative",
                            "what_changed": "new unit",
                        },
                    ),
                    ready_plan,
                    ToolCall(
                        id="t2",
                        name="update_map",
                        arguments={
                            "title": "verify the main mechanism",
                            "status": "resolved",
                            "importance": "medium",
                            "what_changed": "opened evidence task",
                        },
                    ),
                    ToolCall(
                        id="t3",
                        name="conclude_pass",
                        arguments=self._conclusion("expansion done", False),
                    ),
                ]
            )
        if mode == "collision":
            return LLMTurn(
                tool_calls=[
                    ready_plan,
                    ToolCall(
                        id="t1",
                        name="conclude_pass",
                        arguments=self._conclusion("collision done", False),
                    )
                ]
            )
        if mode == "stability_check":
            return LLMTurn(
                tool_calls=[
                    ToolCall(
                        id="t1",
                        name="answer_stability",
                        arguments={"has_direction": False, "direction": ""},
                    )
                ]
            )
        return LLMTurn(
            tool_calls=[
                ready_plan,
                ToolCall(
                    id="t1",
                    name="conclude_pass",
                    arguments=self._conclusion("no high value", True),
                )
            ]
        )


class TestRuntime(unittest.IsolatedAsyncioTestCase):
    def test_provider_tool_name_style_is_canonicalized_only_when_offered(self):
        offered = {"update_argument", "update_rebuttal", "conclude_pass"}
        self.assertEqual(
            _canonical_tool_name("updateArgument", offered), "update_argument"
        )
        self.assertEqual(
            _canonical_tool_name("Update-Rebuttal", offered), "update_rebuttal"
        )
        self.assertEqual(
            _canonical_tool_name("deleteEverything", offered), "deleteEverything"
        )

    async def _plan(self, store, session, agent, phase, status="active"):
        await store.save_plan(
            ResearchPlan(
                plan_id=f"plan_{agent.value.lower()}", phase=phase,
                question_interpretation="specific interpretation",
                winning_condition="defensible position",
                strategy="adaptive route",
                next_actions=[] if status == "ready_to_conclude" else [{
                    "action": "next", "purpose": "progress", "expected_gain": "gain",
                    "stop_or_pivot_if": "no gain",
                }],
                stopping_conditions=["phase objective satisfied"],
                remaining_work="none" if status == "ready_to_conclude" else "next action",
                progress_assessment="fixture", estimated_remaining_actions=0,
                status=status,
            ),
            session.session_id, agent,
        )

    async def test_repeated_invalid_argument_updates_remove_only_that_tool(self):
        class InvalidUpdateModel:
            def __init__(self):
                self.turn = 0

            async def run(self, messages, tools=None):
                self.turn += 1
                names = {
                    item.get("function", {}).get("name") for item in (tools or [])
                }
                if self.turn <= 3:
                    self_outer.assertIn("update_argument", names)
                    return LLMTurn(tool_calls=[
                        ToolCall(f"u{self.turn}", "update_argument", {"argument_id": "arg_a_0001"}),
                    ])
                self_outer.assertNotIn("update_argument", names)
                self_outer.assertIn("update_rebuttal", names)
                self_outer.assertTrue(any(
                    "ARGUMENT UPDATE CLOSED" in str(item.get("content", ""))
                    for item in messages
                ))
                raise RuntimeError("argument-breaker-observed")

        self_outer = self
        store = InMemoryStore()
        session = ResearchSession(
            session_id="argument-breaker", question="P?",
            position_a="P", position_b="not P", agents=[Party.B],
        )
        await store.save_session(session)
        runtime = Runtime(store=store, llm=InvalidUpdateModel())
        runtime.log = MutationLog(store, session.session_id)
        await self._plan(store, session, Party.B, "continuous")
        with self.assertRaisesRegex(RuntimeError, "argument-breaker-observed"):
            await runtime._run_pass(session, Party.B, 1, "continuous")

    async def test_valid_argument_resets_invalid_update_streak(self):
        class RecoveringModel:
            def __init__(self):
                self.turn = 0

            async def run(self, messages, tools=None):
                self.turn += 1
                names = {
                    item.get("function", {}).get("name") for item in (tools or [])
                }
                self_outer.assertIn("update_argument", names)
                if self.turn == 1:
                    return LLMTurn(tool_calls=[
                        ToolCall("bad", "update_argument", {"title": "incomplete"}),
                    ])
                if self.turn == 2:
                    return LLMTurn(tool_calls=[ToolCall(
                        "good", "update_argument", {
                            "title": "Complete case",
                            "claim": "The position holds under the stated comparison.",
                            "burden": "Show a relevant difference.",
                            "impact": "The difference decides the motion.",
                            "scope": "The stated motion only.",
                            "warrant": ["First infer the relevant difference.", "Then connect it to the decision rule."],
                        },
                    )])
                raise RuntimeError("argument-recovery-observed")

        self_outer = self
        store = InMemoryStore()
        session = ResearchSession(
            session_id="argument-recovery", question="P?",
            position_a="P", position_b="not P", agents=[Party.A],
        )
        await store.save_session(session)
        runtime = Runtime(store=store, llm=RecoveringModel())
        runtime.log = MutationLog(store, session.session_id)
        await self._plan(store, session, Party.A, "expansion")
        with self.assertRaisesRegex(RuntimeError, "argument-recovery-observed"):
            await runtime._run_pass(session, Party.A, 1, "expansion")

    async def test_argument_tool_stays_open_until_expansion_floor_is_met(self):
        class StillRequiredModel:
            def __init__(self):
                self.turn = 0

            async def run(self, messages, tools=None):
                self.turn += 1
                names = {
                    item.get("function", {}).get("name") for item in (tools or [])
                }
                self_outer.assertIn("update_argument", names)
                if self.turn <= 4:
                    return LLMTurn(tool_calls=[ToolCall(
                        f"bad-{self.turn}", "update_argument", {"title": "incomplete"},
                    )])
                raise RuntimeError("required-argument-tool-observed")

        self_outer = self
        store = InMemoryStore()
        session = ResearchSession(
            session_id="argument-required", question="P?",
            position_a="P", position_b="not P", agents=[Party.A],
        )
        await store.save_session(session)
        runtime = Runtime(store=store, llm=StillRequiredModel())
        runtime.log = MutationLog(store, session.session_id)
        await self._plan(store, session, Party.A, "expansion")
        with self.assertRaisesRegex(RuntimeError, "required-argument-tool-observed"):
            await runtime._run_pass(session, Party.A, 1, "expansion")

    async def test_invalid_argument_in_collision_returns_tool_error_not_crash(self):
        class CollisionInvalidModel:
            def __init__(self):
                self.turn = 0

            async def run(self, messages, tools=None):
                self.turn += 1
                if self.turn == 1:
                    return LLMTurn(tool_calls=[ToolCall(
                        "bad", "update_argument", {"title": "incomplete"},
                    )])
                self_outer.assertTrue(any(
                    "a new argument cannot be an empty placeholder"
                    in str(item.get("content", ""))
                    for item in messages
                ))
                raise RuntimeError("collision-error-returned")

        self_outer = self
        store = InMemoryStore()
        session = ResearchSession(
            session_id="collision-invalid", question="P?", position_a="P",
            position_b="not P", agents=[Party.B],
        )
        await store.save_session(session)
        runtime = Runtime(store=store, llm=CollisionInvalidModel())
        runtime.log = MutationLog(store, session.session_id)
        await self._plan(store, session, Party.B, "continuous")
        with self.assertRaisesRegex(RuntimeError, "collision-error-returned"):
            await runtime._run_pass(session, Party.B, 1, "continuous")

    async def test_ready_plan_with_satisfied_contract_exposes_only_conclusion(self):
        class ExitModel:
            async def run(self, messages, tools=None):
                names = {
                    item.get("function", {}).get("name") for item in (tools or [])
                }
                self_outer.assertEqual(names, {"conclude_pass"})
                return LLMTurn(tool_calls=[ToolCall(
                    "done", "conclude_pass", {
                        "summary": "done", "attempted": "done", "changed": "done",
                        "remaining_unknowns": "none", "why_stop": "contract met",
                        "next_pass": "collision", "no_high_value_direction": True,
                    },
                )])

        self_outer = self
        store = InMemoryStore()
        session = ResearchSession(
            session_id="ready-exit", question="P?", position_a="P",
            position_b="not P", agents=[Party.A],
        )
        session.budget.argument_first_gate = False
        session.budget.min_sources_per_agent = 0
        session.budget.min_examined_sources_per_agent = 0
        session.budget.min_core_arguments_per_agent = 0
        await store.save_session(session)
        runtime = Runtime(store=store, llm=ExitModel())
        runtime.log = MutationLog(store, session.session_id)
        await apply_action(
            store, runtime.log, EngineAction.UPDATE_UNIT, Party.A, 1,
            {"content": "integrated case"},
        )
        await apply_action(
            store, runtime.log, EngineAction.UPDATE_MAP, Party.A, 1,
            {"title": "checked", "status": "resolved"},
        )
        await self._plan(store, session, Party.A, "expansion", "ready_to_conclude")
        result = await runtime._run_pass(session, Party.A, 1, "expansion")
        self.assertEqual(result.action, EngineAction.CONCLUDE_PASS)

    async def test_two_plan_only_revisions_force_a_concrete_collision_action(self):
        class PlanLoopModel:
            async def run(self, messages, tools=None):
                names = {
                    item.get("function", {}).get("name") for item in (tools or [])
                }
                self_outer.assertNotIn("update_plan", names)
                self_outer.assertIn("update_rebuttal", names)
                raise RuntimeError("plan-action-gate-observed")

        self_outer = self
        store = InMemoryStore()
        session = ResearchSession(
            session_id="plan-action-gate", question="P?", position_a="P",
            position_b="not P", agents=[Party.A],
        )
        await store.save_session(session)
        runtime = Runtime(store=store, llm=PlanLoopModel())
        runtime.log = MutationLog(store, session.session_id)
        await self._plan(store, session, Party.A, "collision")
        for _ in range(2):
            await runtime.log.append(
                agent=Party.A, action=EngineAction.UPDATE_PLAN, pass_no=1,
                payload={"phase": "collision", "status": "active"},
            )
        with self.assertRaisesRegex(RuntimeError, "plan-action-gate-observed"):
            await runtime._run_pass(session, Party.A, 1, "collision")

    async def test_hidden_tool_call_is_rejected_at_execution_boundary(self):
        class StaleToolModel:
            def __init__(self):
                self.turn = 0

            async def run(self, messages, tools=None):
                self.turn += 1
                names = {
                    item.get("function", {}).get("name") for item in (tools or [])
                }
                self_outer.assertNotIn("update_plan", names)
                if self.turn == 1:
                    return LLMTurn(tool_calls=[ToolCall(
                        "stale", "update_plan", {"strategy": "wrongly forced revision"},
                    )])
                self_outer.assertTrue(any(
                    "TOOL_GATE: update_plan was not offered" in str(item.get("content", ""))
                    for item in messages
                ))
                raise RuntimeError("hidden-tool-rejected")

        self_outer = self
        store = InMemoryStore()
        session = ResearchSession(
            session_id="hidden-plan", question="P?", position_a="P",
            position_b="not P", agents=[Party.A],
        )
        await store.save_session(session)
        runtime = Runtime(store=store, llm=StaleToolModel())
        runtime.log = MutationLog(store, session.session_id)
        await self._plan(store, session, Party.A, "collision")
        for _ in range(2):
            await runtime.log.append(
                agent=Party.A, action=EngineAction.UPDATE_PLAN, pass_no=1,
                payload={"phase": "collision", "status": "active"},
            )
        with self.assertRaisesRegex(RuntimeError, "hidden-tool-rejected"):
            await runtime._run_pass(session, Party.A, 1, "collision")
        self.assertEqual(len(await runtime.log.list(1)), 2)
        self.assertEqual(
            (await store.load_plan(session.session_id, Party.A)).strategy,
            "adaptive route",
        )

    async def test_two_similar_empty_searches_close_retrieval_branch(self):
        class EmptySearch:
            async def search(self, query, n=10):
                return []

        class LoopingModel:
            def __init__(self):
                self.turn = 0

            async def run(self, messages, tools=None):
                self.turn += 1
                names = {
                    item.get("function", {}).get("name") for item in (tools or [])
                }
                if self.turn <= 2:
                    self_outer.assertIn("search", names)
                    return LLMTurn(tool_calls=[ToolCall(
                        id=f"s{self.turn}", name="search", arguments={
                            "query": (
                                "Jankowiak Fischer romantic love 166 cultures"
                                if self.turn == 1 else
                                "Fischer Jankowiak 166 cultures romantic love universal"
                            ),
                            "purpose": "verify the same cross-cultural universality premise",
                            "strategy": "named-study lookup",
                            "search_mode": "fact_verification",
                            "discovery_kind": "not_applicable",
                        },
                    )])
                self_outer.assertNotIn("search", names)
                self_outer.assertTrue(any(
                    "RETRIEVAL BRANCH CLOSED" in str(item.get("content", ""))
                    for item in messages
                ))
                raise RuntimeError("breaker-observed")

        self_outer = self
        store = InMemoryStore()
        session = ResearchSession(
            session_id="search-breaker", question="爱情是不是人类的必需品",
            position_a="爱情是必需品", position_b="爱情不是必需品",
            agents=[Party.A],
        )
        await store.save_session(session)
        runtime = Runtime(store=store, llm=LoopingModel(), search=EmptySearch())
        runtime.log = MutationLog(store, session.session_id)
        await self._plan(store, session, Party.A, "expansion")

        async def ready(*args):
            return True

        async def incomplete(*args):
            return False

        runtime._case_frame_ready = ready
        runtime._expansion_state_complete = incomplete
        with self.assertRaisesRegex(RuntimeError, "breaker-observed"):
            await runtime._run_pass(session, Party.A, 1, "expansion")

    async def test_duplicate_failed_source_action_forces_synthesis(self):
        class SearchWithReader:
            async def search(self, query, n=10):
                return []

            async def read(self, url):
                raise AssertionError("video landing pages must not be read")

        class RepeatingModel:
            def __init__(self):
                self.turn = 0

            async def run(self, messages, tools=None):
                self.turn += 1
                names = {
                    item.get("function", {}).get("name") for item in (tools or [])
                }
                if self.turn <= 2:
                    self_outer.assertIn("read_source", names)
                    return LLMTurn(tool_calls=[ToolCall(
                        id=f"r{self.turn}", name="read_source",
                        arguments={"source_id": "src_video", "purpose": "mine its case"},
                    )])
                self_outer.assertNotIn("read_source", names)
                self_outer.assertTrue(any(
                    "EXTERNAL RETRIEVAL CLOSED" in str(item.get("content", ""))
                    for item in messages
                ))
                raise RuntimeError("source-breaker-observed")

        self_outer = self
        store = InMemoryStore()
        session = ResearchSession(
            session_id="source-breaker", question="爱情是不是人类的必需品",
            position_a="爱情是必需品", position_b="爱情不是必需品",
            agents=[Party.A],
        )
        await store.save_session(session)
        await store.save_source(Source(
            source_id="src_video", url="https://video.example/round",
            title="prior round", content="lead",
            metadata={"content_access": "lead_only"}, discovered_by=Party.A,
        ), session.session_id)
        runtime = Runtime(store=store, llm=RepeatingModel(), search=SearchWithReader())
        runtime.log = MutationLog(store, session.session_id)
        await self._plan(store, session, Party.A, "expansion")

        async def ready(*args):
            return True

        async def incomplete(*args):
            return False

        runtime._case_frame_ready = ready
        runtime._expansion_state_complete = incomplete
        with self.assertRaisesRegex(RuntimeError, "source-breaker-observed"):
            await runtime._run_pass(session, Party.A, 1, "expansion")

    async def test_one_position_failure_does_not_cancel_the_other(self):
        runtime = Runtime(store=InMemoryStore(), llm=MockLLM())
        session = ResearchSession(
            session_id="independent",
            question="P?",
            position_a="P",
            position_b="not P",
        )
        finished = []

        async def scripted_run(session, agent, pass_no, mode, checkpoint_key):
            if agent is Party.A:
                raise PassBudgetExhausted("A exhausted")
            import asyncio
            await asyncio.sleep(0.01)
            finished.append(agent)

        runtime._run_and_checkpoint = scripted_run
        with self.assertRaises(PassBudgetExhausted):
            await runtime._run_parallel_phase(
                session, [(Party.A, 1), (Party.B, 2)], "expansion", "expansion"
            )
        self.assertEqual(finished, [Party.B])

    async def test_search_candidates_are_screened_before_persistence(self):
        runtime = Runtime(store=InMemoryStore(), llm=MockLLM())
        good = SearchResult(
            title="Social relationships and mortality risk meta-analysis",
            url="https://journals.plos.org/article?id=1&utm_source=test",
            snippet="Holt-Lunstad meta-analysis of social relationships and mortality",
        )
        noise = SearchResult(
            title="دليل شامل عن عجلة قيادة السيارة",
            url="https://cars.example/steering",
            snippet="car steering shopping guide",
        )
        search_vertical = SearchResult(
            title="Debate result images",
            url="https://image.so.com/i?q=debate",
            snippet="debate speech images",
        )
        kept, rejected = runtime._screen_search_results(
            [good, noise, search_vertical],
            query="Holt-Lunstad social relationships mortality meta-analysis",
            purpose="verify the mortality effect",
            question="Are close relationships necessary?",
            position="They are necessary",
            limit=5,
            existing_urls=set(),
        )
        self.assertEqual([item.title for item in kept], [good.title])
        self.assertEqual(rejected, 2)
        self.assertNotIn("utm_source", kept[0].url)

    async def test_exact_motion_rejects_unrelated_debate_video(self):
        runtime = Runtime(store=InMemoryStore(), llm=MockLLM())
        matching = SearchResult(
            title="安乐死应不应该合法化辩论赛",
            url="https://www.bilibili.com/video/BVmatch",
            snippet="正方安乐死应当合法化",
        )
        unrelated = SearchResult(
            title="知足常乐辩论赛完整版",
            url="https://www.bilibili.com/video/BVnoise",
            snippet="另一场精彩辩论",
        )
        kept, _ = runtime._screen_search_results(
            [matching, unrelated],
            query="安乐死应不应该合法化 辩论",
            purpose="寻找同题比赛",
            question="安乐死应不应该合法化？",
            position="安乐死应当合法化",
            limit=5,
            existing_urls=set(),
            search_mode="argument_discovery",
            discovery_kind="exact_motion",
        )
        self.assertEqual([item.url for item in kept], [matching.url])
        self.assertEqual(kept[0].metadata["content_access"], "lead_only")

    async def test_source_reading_selects_focus_passages(self):
        runtime = Runtime(store=InMemoryStore(), llm=MockLLM(), max_tool_result_chars=2000)
        body = ("Generic introduction without the measured outcome.\n\n" * 100) + (
            "The longitudinal cohort measured mortality hazard ratio and social isolation. " * 20
        )
        excerpt = runtime._focused_excerpt(body, "mortality hazard ratio social isolation")
        self.assertIn("mortality hazard ratio", excerpt)
        self.assertLessEqual(len(excerpt), 2200)

    async def test_video_landing_page_never_counts_as_document_read(self):
        class ShouldNotRead:
            async def read(self, url):
                raise AssertionError("video landing page should not reach network reader")

        store = InMemoryStore()
        await store.save_source(Source(
            source_id="src_video",
            title="A prior debate video",
            url="https://www.bilibili.com/video/BV123",
            metadata={"content_access": "lead_only"},
        ), "sess_video")
        runtime = Runtime(store=store, llm=MockLLM(), search=ShouldNotRead())
        result = await runtime._execute_pass_tool(
            "sess_video", Party.A, "read_source",
            {"source_id": "src_video", "purpose": "inspect the debate"},
        )
        self.assertTrue(result.startswith("source read skipped"))
        self.assertIn("not a transcript", result)

    async def test_full_cycle_to_stable(self):
        store = InMemoryStore()
        session = ResearchSession(
            session_id="sess_1",
            question="Does X cause Y?",
            position_a="X causes Y",
            position_b="X does not cause Y",
            status=SessionStatus.CREATED,
            budget=ResearchBudget(
                min_sources_per_agent=0,
                min_examined_sources_per_agent=0,
                min_core_arguments_per_agent=0,
                min_rebuttals_per_agent=0,
                argument_first_gate=False,
            ),
        )
        await store.save_session(session)

        progress = []
        rt = Runtime(store=store, llm=MockLLM(), progress_callback=progress.append)
        result = await rt.run("sess_1")

        self.assertEqual(result.status, SessionStatus.STABLE_FOR_REVIEW)
        self.assertGreaterEqual(result.current_cycle, 1)

        # A and B each created a unit during expansion
        units_a = await store.list_units("sess_1", Party.A)
        units_b = await store.list_units("sess_1", Party.B)
        self.assertEqual(len(units_a), 1)
        self.assertEqual(len(units_b), 1)

        # Every phase also persists its initial and exit-audit plan revisions.
        mutations = await MutationLog(store, "sess_1").list()
        self.assertEqual(len(mutations), 22)
        self.assertEqual(
            sum(m.action.value == "update_plan" for m in mutations), 12
        )

        # the concluding pass of both agents carries the stable signal
        self.assertTrue(
            any(
                m.action.value == "conclude_pass" and m.payload.get("no_high_value_direction")
                for m in mutations
            )
        )
        self.assertTrue(any(item.get("event", {}).get("kind") == "model" for item in progress))
        self.assertTrue(any(isinstance(item.get("budget"), dict) for item in progress))

    async def test_raises_on_unknown_session(self):
        rt = Runtime(store=InMemoryStore(), llm=MockLLM())
        with self.assertRaises(KeyError):
            await rt.run("missing")

    async def test_collision_context_contains_full_opponent_state_and_sources(self):
        store = InMemoryStore()
        session = ResearchSession(
            session_id="ctx",
            question="P or not P?",
            position_a="P",
            position_b="not P",
        )
        await store.save_session(session)
        await store.save_source(
            Source(source_id="src_0001", title="Primary report", content="full finding"),
            "ctx",
        )
        await store.save_argument(
            Argument(
                argument_id="arg_b_0001", title="B case", claim="not P",
                material_source_ids=["src_0001"],
            ),
            "ctx", Party.B,
        )
        from cre.models import ResearchUnit

        marker = "opponent-detail-that-must-not-be-truncated"
        await store.save_unit(
            ResearchUnit(unit_id="ru_b_0001", content=marker), "ctx", Party.B
        )
        runtime = Runtime(store=store, llm=MockLLM())
        runtime.log = MutationLog(store, "ctx")
        context = await runtime._build_context(session, Party.A, "collision")
        self.assertIn(marker, context)
        self.assertIn("Primary report", context)
        self.assertIn("Assigned standpoint: P", context)

    async def test_collision_exposes_only_collision_actions(self):
        class InspectingModel:
            async def run(self, messages, tools=None):
                names = {
                    item.get("function", {}).get("name") for item in (tools or [])
                }
                self_outer.assertEqual(
                    names,
                    {"update_plan", "update_rebuttal", "conclude_pass"},
                )
                raise RuntimeError("collision-tools-observed")

        self_outer = self
        store = InMemoryStore()
        session = ResearchSession(
            session_id="collision-tools", question="P?", position_a="P",
            position_b="not P", agents=[Party.A],
        )
        await store.save_session(session)
        runtime = Runtime(store=store, llm=InspectingModel())
        runtime.log = MutationLog(store, session.session_id)
        await self._plan(store, session, Party.A, "collision")
        with self.assertRaisesRegex(RuntimeError, "collision-tools-observed"):
            await runtime._run_pass(session, Party.A, 1, "collision")

    async def test_continuous_is_bounded_to_case_repair_actions(self):
        class InspectingModel:
            async def run(self, messages, tools=None):
                names = {
                    item.get("function", {}).get("name") for item in (tools or [])
                }
                self_outer.assertEqual(
                    names,
                    {"update_plan", "update_rebuttal", "update_argument", "conclude_pass"},
                )
                self_outer.assertNotIn("search", names)
                self_outer.assertNotIn("update_map", names)
                raise RuntimeError("continuous-tools-observed")

        self_outer = self
        store = InMemoryStore()
        session = ResearchSession(
            session_id="continuous-tools", question="P?", position_a="P",
            position_b="not P", agents=[Party.A],
        )
        await store.save_session(session)
        runtime = Runtime(store=store, llm=InspectingModel())
        runtime.log = MutationLog(store, session.session_id)
        await self._plan(store, session, Party.A, "continuous")
        with self.assertRaisesRegex(RuntimeError, "continuous-tools-observed"):
            await runtime._run_pass(session, Party.A, 1, "continuous")

    async def test_continuous_retry_after_two_repairs_exposes_only_exit_actions(self):
        class InspectingModel:
            async def run(self, messages, tools=None):
                names = {
                    item.get("function", {}).get("name") for item in (tools or [])
                }
                self_outer.assertEqual(names, {"update_plan", "conclude_pass"})
                self_outer.assertTrue(any(
                    "already committed its two allowed concrete repairs" in
                    str(item.get("content", "")) for item in messages
                ))
                raise RuntimeError("continuous-exit-observed")

        self_outer = self
        store = InMemoryStore()
        session = ResearchSession(
            session_id="continuous-exit", question="P?", position_a="P",
            position_b="not P", agents=[Party.A],
        )
        await store.save_session(session)
        for seq, action in enumerate((
            EngineAction.CONCLUDE_PASS,
            EngineAction.UPDATE_ARGUMENT,
            EngineAction.UPDATE_REBUTTAL,
        ), 1):
            await store.append_mutation(Mutation(
                mutation_id=f"mut_{seq}", seq=seq,
                session_id=session.session_id, pass_no=seq,
                agent=Party.A, action=action,
            ))
        runtime = Runtime(store=store, llm=InspectingModel())
        runtime.log = MutationLog(store, session.session_id)
        await self._plan(store, session, Party.A, "continuous")
        with self.assertRaisesRegex(RuntimeError, "continuous-exit-observed"):
            await runtime._run_pass(session, Party.A, 4, "continuous")

    async def test_complete_current_version_coverage_forces_collision_conclusion(self):
        class InspectingModel:
            async def run(self, messages, tools=None):
                names = {
                    item.get("function", {}).get("name") for item in (tools or [])
                }
                self_outer.assertEqual(names, {"conclude_pass"})
                self_outer.assertTrue(any(
                    "COLLISION CONVERGENCE GATE" in str(item.get("content", ""))
                    for item in messages
                ))
                raise RuntimeError("collision-convergence-observed")

        self_outer = self
        store = InMemoryStore()
        session = ResearchSession(
            session_id="collision-convergence", question="P?", position_a="P",
            position_b="not P", agents=[Party.A],
            budget=ResearchBudget(min_rebuttals_per_agent=1),
        )
        await store.save_session(session)
        await store.save_argument(
            Argument(argument_id="arg_b_0001", claim="not P", version=2),
            session.session_id, Party.B,
        )
        await store.save_rebuttal(
            Rebuttal(
                rebuttal_id="reb_a_0001", target_agent=Party.B,
                target_argument_id="arg_b_0001", target_version=2,
                title="attack", reconstruction="not P", attack_type="warrant",
                attack="premise fails", why_it_matters="claim fails",
            ),
            session.session_id, Party.A,
        )
        runtime = Runtime(store=store, llm=InspectingModel())
        runtime.log = MutationLog(store, session.session_id)
        await self._plan(store, session, Party.A, "collision", "ready_to_conclude")
        with self.assertRaisesRegex(RuntimeError, "collision-convergence-observed"):
            await runtime._run_pass(session, Party.A, 1, "collision")

    async def test_collision_records_stale_version_for_continuous_without_blocking_family_review(self):
        store = InMemoryStore()
        session = ResearchSession(
            session_id="collision-version-gate", question="P?",
            position_a="P", position_b="not P", agents=[Party.A],
            budget=ResearchBudget(min_rebuttals_per_agent=1),
        )
        await store.save_session(session)
        await store.save_argument(
            Argument(argument_id="arg_b_0001", claim="not P", version=3),
            session.session_id, Party.B,
        )
        await store.save_rebuttal(
            Rebuttal(
                rebuttal_id="reb_a_0001", target_agent=Party.B,
                target_argument_id="arg_b_0001", target_version=2,
                title="old attack", reconstruction="not P", attack_type="warrant",
                attack="premise fails", why_it_matters="claim fails",
            ), session.session_id, Party.A,
        )
        runtime = Runtime(store=store, llm=MockLLM())
        runtime.log = MutationLog(store, session.session_id)
        await self._plan(store, session, Party.A, "collision", "ready_to_conclude")
        error = await runtime._conclusion_error(
            "collision", Party.A, 1, MockLLM._conclusion("done", True)
        )
        self.assertIsNone(error)
        context = await runtime._build_context(session, Party.A, "collision")
        self.assertIn("VERSION GAPS FOR CONTINUOUS REPAIR", context)
        self.assertIn("arg_b_0001 current v3", context)

    async def test_recovery_keeps_family_review_checkpoint_when_versions_move(self):
        store = InMemoryStore()
        session = ResearchSession(
            session_id="collision-repair", question="P?",
            position_a="P", position_b="not P",
            budget=ResearchBudget(
                min_sources_per_agent=0, min_examined_sources_per_agent=0,
                min_core_arguments_per_agent=0, min_rebuttals_per_agent=1,
                argument_first_gate=False,
            ),
        )
        session.phase_progress = {
            "expansion": ["A", "B"], "collision": ["A", "B"],
            "continuous:0": ["A"],
        }
        await store.save_session(session)
        for party in (Party.A, Party.B):
            await store.save_unit(
                ResearchUnit(f"ru_{party.value.lower()}_0001", content="case"),
                session.session_id, party,
            )
            await store.save_map_entry(
                ResearchMapEntry(f"map_{party.value.lower()}_0001", title="done", status=MapStatus.RESOLVED),
                session.session_id, party,
            )
        await store.save_map_entry(
            ResearchMapEntry("map_a_late", title="new continuous task"),
            session.session_id, Party.A,
        )
        await store.save_argument(
            Argument(argument_id="arg_a_0001", claim="P", version=3),
            session.session_id, Party.A,
        )
        await store.save_argument(
            Argument(argument_id="arg_b_0001", claim="not P", version=2),
            session.session_id, Party.B,
        )
        for owner, target, version in (
            (Party.A, "arg_b_0001", 2),
            (Party.B, "arg_a_0001", 2),
        ):
            await store.save_rebuttal(
                Rebuttal(
                    rebuttal_id=f"reb_{owner.value.lower()}_0001",
                    target_agent=Party.B if owner is Party.A else Party.A,
                    target_argument_id=target, target_version=version,
                    title="attack", reconstruction="claim", attack_type="warrant",
                    attack="premise fails", why_it_matters="case changes",
                ), session.session_id, owner,
            )
        runtime = Runtime(store=store, llm=MockLLM())
        runtime.log = MutationLog(store, session.session_id)
        await runtime._repair_phase_progress(session)
        self.assertEqual(session.phase_progress["collision"], ["A", "B"])
        self.assertIn("continuous:0", session.phase_progress)

    async def test_recovery_restores_erased_markers_from_concluded_passes(self):
        store = InMemoryStore()
        session = ResearchSession(
            session_id="erased-progress", question="P?",
            position_a="P", position_b="not P",
            budget=ResearchBudget(
                min_sources_per_agent=0, min_examined_sources_per_agent=0,
                min_core_arguments_per_agent=0, min_rebuttals_per_agent=0,
                argument_first_gate=False,
            ),
        )
        await store.save_session(session)
        for party in (Party.A, Party.B):
            await store.save_unit(
                ResearchUnit(f"ru_{party.value.lower()}_0001", content="case"),
                session.session_id, party,
            )
            await store.save_map_entry(
                ResearchMapEntry(f"map_{party.value.lower()}_0001", title="done"),
                session.session_id, party,
            )
        seq = 0
        for phase, parties in (
            ("expansion", (Party.A, Party.B)),
            ("collision", (Party.A, Party.B)),
            ("continuous", (Party.A,)),
        ):
            for party in parties:
                pass_no = seq // 2 + 1
                for action, payload in (
                    (EngineAction.UPDATE_PLAN, {"phase": phase}),
                    (EngineAction.CONCLUDE_PASS, {"summary": "done"}),
                ):
                    seq += 1
                    await store.append_mutation(Mutation(
                        mutation_id=f"mut_{seq}", seq=seq,
                        session_id=session.session_id, pass_no=pass_no,
                        agent=party, action=action, payload=payload,
                    ))
        runtime = Runtime(store=store, llm=MockLLM())
        await runtime._repair_phase_progress(session)
        self.assertEqual(set(session.phase_progress["expansion"]), {"A", "B"})
        self.assertEqual(set(session.phase_progress["collision"]), {"A", "B"})
        self.assertEqual(session.phase_progress["continuous:0"], ["A"])
        self.assertEqual(session.status, SessionStatus.CONTINUOUS)

    async def test_pass_one_conclusion_requires_integrated_unit_and_map(self):
        store = InMemoryStore()
        session = ResearchSession(session_id="gate", question="P?", position_a="P")
        await store.save_session(session)
        await self._plan(store, session, Party.A, "expansion", "ready_to_conclude")
        runtime = Runtime(store=store, llm=MockLLM())
        runtime.log = MutationLog(store, "gate")
        error = await runtime._conclusion_error(
            "expansion", Party.A, 1, MockLLM._conclusion("too early", False)
        )
        self.assertIn("update_unit", error)
        self.assertIn("update_map", error)

    async def test_resumed_pass_accepts_durable_prior_unit_and_map(self):
        store = InMemoryStore()
        session = ResearchSession(
            session_id="resumed-gate", question="P?", position_a="P",
            position_b="not P",
        )
        session.budget.argument_first_gate = False
        session.budget.min_sources_per_agent = 0
        session.budget.min_examined_sources_per_agent = 0
        session.budget.min_core_arguments_per_agent = 0
        await store.save_session(session)
        runtime = Runtime(store=store, llm=MockLLM())
        runtime.log = MutationLog(store, session.session_id)
        await apply_action(
            store, runtime.log, EngineAction.UPDATE_UNIT, Party.A, 1,
            {"content": "durable case"},
        )
        await apply_action(
            store, runtime.log, EngineAction.UPDATE_MAP, Party.A, 1,
            {"title": "durable obligation", "status": "resolved"},
        )
        await self._plan(store, session, Party.A, "expansion", "ready_to_conclude")
        self.assertIsNone(await runtime._conclusion_error(
            "expansion", Party.A, 2, MockLLM._conclusion("resume", True)
        ))

    async def test_conclusion_requires_complete_research_account(self):
        store = InMemoryStore()
        runtime = Runtime(store=store, llm=MockLLM())
        runtime.log = MutationLog(store, "gate")
        error = await runtime._conclusion_error(
            "continuous",
            Party.A,
            1,
            {"summary": "incomplete", "no_high_value_direction": False},
        )
        self.assertIn("attempted", error)
        self.assertIn("remaining_unknowns", error)

    async def test_pass_one_map_resolution_must_revise_deliverable(self):
        store = InMemoryStore()
        session = ResearchSession(
            session_id="map_gate",
            question="P?",
            position_a="P",
            position_b="not P",
            budget=ResearchBudget(
                min_sources_per_agent=0,
                min_examined_sources_per_agent=0,
                min_core_arguments_per_agent=0,
            ),
        )
        await store.save_session(session)
        runtime = Runtime(store=store, llm=MockLLM())
        runtime.log = MutationLog(store, session.session_id)
        await self._plan(store, session, Party.A, "expansion", "ready_to_conclude")
        await apply_action(
            store, runtime.log, EngineAction.UPDATE_UNIT, Party.A, 1,
            {"content": "case", "status": "tentative"},
        )
        await apply_action(
            store, runtime.log, EngineAction.UPDATE_MAP, Party.A, 1,
            {"title": "close warrant", "status": "active"},
        )
        await apply_action(
            store, runtime.log, EngineAction.UPDATE_MAP, Party.A, 1,
            {"map_id": "map_a_0001", "status": "resolved"},
        )
        error = await runtime._conclusion_error(
            "expansion", Party.A, 1, MockLLM._conclusion("done", False)
        )
        self.assertIn("without revising the deliverable", error)

    async def test_current_revision_cannot_stabilize_under_active_rebuttal(self):
        store = InMemoryStore()
        session = ResearchSession(
            session_id="live_attack",
            question="P or not P?",
            position_a="P",
            position_b="not P",
            budget=ResearchBudget(
                min_sources_per_agent=0,
                min_examined_sources_per_agent=0,
                min_core_arguments_per_agent=0,
                min_rebuttals_per_agent=0,
            ),
        )
        await store.save_session(session)
        argument = Argument(argument_id="arg_a_0001", claim="P", version=1)
        await store.save_argument(argument, session.session_id, Party.A)
        await store.save_rebuttal(
            Rebuttal(
                rebuttal_id="reb_b_0001",
                target_agent=Party.A,
                target_argument_id=argument.argument_id,
                target_version=1,
            ),
            session.session_id,
            Party.B,
        )
        log = MutationLog(store, session.session_id)
        for agent in session.agents:
            await log.append(
                agent=agent,
                action=EngineAction.CONCLUDE_PASS,
                pass_no=1,
                payload={"no_high_value_direction": True},
            )
        mutations = await log.list()
        self.assertFalse(await evaluate_candidate_stable(store, session, mutations))

        # Once the owner has revised the attacked text, the old attack becomes
        # historical and no longer blocks the new current version.
        argument.version = 2
        await store.save_argument(argument, session.session_id, Party.A)
        self.assertTrue(await evaluate_candidate_stable(store, session, mutations))


class TestResearchMethodPrompt(unittest.TestCase):
    def test_prompts_are_loaded_from_editable_resources(self):
        self.assertIn("Let the research state", load_prompt("common/principles.md"))
        rendered = render_prompt(
            "identity.md", agent="B", question="Q?", position="not Q"
        )
        self.assertIn("Position Advocate B", rendered)
        self.assertIn("Debate proposition: Q?", rendered)

    def test_prompt_loader_rejects_parent_traversal(self):
        with self.assertRaises(ValueError):
            load_prompt("../secrets.txt")

    def test_pass_one_is_position_conditioned_argument_first_research(self):
        prompt = build_system_prompt(
            "expansion", Party.A, "P or not P?", "P"
        )
        self.assertIn("Your assigned standpoint: P", prompt)
        self.assertIn("ARGUMENT-FIRST RECONNAISSANCE", prompt)
        self.assertIn("Position Advocate A", prompt)
        self.assertIn("Construct the position yourself", prompt)
        self.assertIn("exact-motion archaeology", prompt)
        self.assertIn("Search-result", prompt)
        self.assertIn("snippets are leads", prompt)
        self.assertIn("Let the research state choose the search strategy", prompt)
        self.assertIn("public-reasoning", prompt)
        self.assertIn("FACT VERIFICATION", prompt)
        self.assertIn("Search is downstream", prompt)

    def test_search_tool_requests_purpose_and_adaptive_strategy(self):
        schema = search_tool_schema()["function"]
        self.assertEqual(
            schema["parameters"]["required"],
            ["query", "purpose", "strategy", "search_mode", "discovery_kind"],
        )
        self.assertIn("exact_motion", schema["description"])
        self.assertIn("cosmetic rewording", schema["description"])
        self.assertIn("free-form strategies", schema["parameters"]["properties"]["strategy"]["description"])
        read_schema = read_source_tool_schema()["function"]
        self.assertEqual(read_schema["parameters"]["required"], ["source_id", "purpose"])

    def test_collision_is_error_correction_not_forced_persuasion(self):
        prompt = build_system_prompt(
            "collision", Party.B, "P or not P?", "not P"
        )
        self.assertIn("COLLISION / ORDINARY REBUTTAL", prompt)
        self.assertIn("Reconstruct it fairly", prompt)
        self.assertIn("target an exact argument id and version", prompt.lower())
        self.assertIn("why the opponent's position", prompt)


class TestPassBudget(unittest.TestCase):
    def test_local_state_actions_do_not_spend_external_research_allowance(self):
        budget = PassBudget(ResearchBudget(
            max_tool_calls_per_pass=1,
            max_failed_tool_calls_per_pass=1,
            max_model_turns_per_pass=3,
            max_tokens_per_pass=100,
        ))
        for _ in range(20):
            budget.record_state_action()
        self.assertFalse(budget.research_exhausted)
        self.assertFalse(budget.exhausted)
        budget.record_tool_call(success=True)
        self.assertTrue(budget.research_exhausted)
        self.assertFalse(budget.exhausted)
        self.assertEqual(budget.snapshot()["state_actions"], 20)

    def test_failed_calls_use_their_own_bounded_cushion(self):
        budget = PassBudget(ResearchBudget(
            max_tool_calls_per_pass=5,
            max_failed_tool_calls_per_pass=1,
        ))
        budget.record_tool_call(success=False)
        snapshot = budget.snapshot()
        self.assertEqual(snapshot["research_calls"], 0)
        self.assertEqual(snapshot["failed_calls"], 1)
        self.assertTrue(snapshot["research_exhausted"])

    def test_research_modes_are_counted_even_when_search_fails(self):
        budget = PassBudget(ResearchBudget())
        budget.record_tool_call(
            success=False, kind="search", mode="argument_discovery",
            discovery_kind="exact_motion",
        )
        budget.record_tool_call(
            success=True, kind="search", mode="fact_verification"
        )
        budget.record_tool_call(success=True, kind="read_source")
        snapshot = budget.snapshot()
        self.assertEqual(snapshot["argument_discovery_searches"], 1)
        self.assertEqual(snapshot["exact_motion_searches"], 1)
        self.assertEqual(snapshot["fact_verification_searches"], 1)
        self.assertEqual(snapshot["source_reads"], 1)

    def test_current_context_is_reported_separately_from_cumulative_tokens(self):
        budget = PassBudget(ResearchBudget())
        budget.record_context(10_001, compacted=True)
        snapshot = budget.snapshot()
        self.assertEqual(snapshot["estimated_context_tokens"], 5_001)
        self.assertEqual(snapshot["context_compactions"], 1)
        self.assertEqual(snapshot["tokens"], 0)


if __name__ == "__main__":
    unittest.main()
