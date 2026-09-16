import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cre.adapters import InMemoryStore
from cre.engine import (
    MutationLog,
    apply_action,
    build_semantic_diff,
    map_from_markdown,
    map_to_markdown,
    unit_from_markdown,
    unit_to_markdown,
)
from cre.models import (
    EngineAction,
    IssueResolution,
    IssueState,
    MapStatus,
    Party,
    Source,
    ResearchUnit,
    ResearchPlan,
    UnitStatus,
)


class TestBlackboard(unittest.TestCase):
    def test_unit_markdown_roundtrip(self):
        unit = ResearchUnit(
            unit_id="ru_a_0017",
            status=UnitStatus.TENTATIVE,
            source_ids=["s_1", "s_2"],
            content="# Finding\n\nbody",
        )
        restored = unit_from_markdown(unit_to_markdown(unit))
        self.assertEqual(restored, unit)

    def test_map_markdown_roundtrip(self):
        from cre.models import ResearchMapEntry

        entry = ResearchMapEntry(
            map_id="map_a_0001",
            title="短期情绪噪声",
            status=MapStatus.ACTIVE,
            importance="high",
            uncertainty="high",
            note="needs more evidence",
        )
        restored = map_from_markdown(map_to_markdown(entry))
        self.assertEqual(restored, entry)


class TestActions(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = InMemoryStore()
        self.log = MutationLog(self.store, "sess_1")

    async def test_update_unit_creates_then_mutates(self):
        m = await apply_action(
            self.store,
            self.log,
            EngineAction.UPDATE_UNIT,
            Party.A,
            1,
            {"content": "# X\n\nclaim", "status": "tentative", "what_changed": "new unit"},
        )
        self.assertEqual(m.target.id, "ru_a_0001")
        unit = await self.store.load_unit("ru_a_0001")
        self.assertEqual(unit.content, "# X\n\nclaim")

        await apply_action(
            self.store,
            self.log,
            EngineAction.UPDATE_UNIT,
            Party.A,
            1,
            {"unit_id": "ru_a_0001", "status": "stable", "why": "verified"},
        )
        unit = await self.store.load_unit("ru_a_0001")
        self.assertEqual(unit.status, UnitStatus.STABLE)

    async def test_model_owned_plan_is_created_and_revised(self):
        created = await apply_action(
            self.store, self.log, EngineAction.UPDATE_PLAN, Party.A, 1,
            {
                "phase": "expansion", "question_interpretation": "Q means X",
                "winning_condition": "establish X", "strategy": "test two routes",
                "route_hypotheses": ["route one", "route two"],
                "next_actions": [{
                    "action": "form argument", "purpose": "test route one",
                    "expected_gain": "a viable warrant", "stop_or_pivot_if": "warrant fails",
                }],
                "stopping_conditions": ["case is defensible"], "completed": [],
                "abandoned": [], "remaining_work": "test route one",
                "progress_assessment": "starting", "estimated_remaining_actions": 4,
                "status": "active", "change_reason": "initial plan",
            },
        )
        self.assertEqual(created.target.id, "plan_a")
        await apply_action(
            self.store, self.log, EngineAction.UPDATE_PLAN, Party.A, 1,
            {
                "next_actions": [], "completed": ["route one"],
                "remaining_work": "none", "progress_assessment": "exit audit passed",
                "estimated_remaining_actions": 0, "status": "ready_to_conclude",
                "change_reason": "stopping conditions met",
            },
        )
        plan = await self.store.load_plan("sess_1", Party.A)
        self.assertEqual(plan.version, 2)
        self.assertEqual(plan.status, "ready_to_conclude")
        self.assertEqual(len(await self.store.list_plan_revisions("sess_1", Party.A)), 2)
        with self.assertRaisesRegex(ValueError, "no material change"):
            await apply_action(
                self.store, self.log, EngineAction.UPDATE_PLAN, Party.A, 1, {}
            )
        self.assertEqual(len(await self.store.list_plan_revisions("sess_1", Party.A)), 2)

    async def test_create_respond_close_issue(self):
        await apply_action(
            self.store,
            self.log,
            EngineAction.UPDATE_UNIT,
            Party.A,
            1,
            {"content": "P causes Q"},
        )
        created = await apply_action(
            self.store,
            self.log,
            EngineAction.CREATE_ISSUE,
            Party.B,
            1,
            {
                "to": "A",
                "target": {"type": "unit", "id": "ru_a_0001", "section": "implication"},
                "priority": "high",
                "title": "causal claim unsupported",
                "body": "only correlational evidence",
            },
        )
        self.assertEqual(created.target.id, "issue_0001")

        await apply_action(
            self.store,
            self.log,
            EngineAction.RESPOND_ISSUE,
            Party.A,
            2,
            {"issue_id": "issue_0001", "response": "we narrowed the claim"},
        )
        await apply_action(
            self.store,
            self.log,
            EngineAction.CLOSE_ISSUE,
            Party.A,
            2,
            {"issue_id": "issue_0001", "resolution": "resolved"},
        )
        issue = await self.store.load_issue("issue_0001")
        self.assertEqual(issue.state, IssueState.CLOSED)
        self.assertEqual(issue.resolution, IssueResolution.RESOLVED)
        self.assertIn("we narrowed the claim", issue.body)

    async def test_conclude_pass(self):
        m = await apply_action(
            self.store,
            self.log,
            EngineAction.CONCLUDE_PASS,
            Party.A,
            1,
            {"summary": "no high-gain direction remains", "why_stop": "coverage audit"},
        )
        self.assertEqual(m.action, EngineAction.CONCLUDE_PASS)
        self.assertEqual(m.payload["summary"], "no high-gain direction remains")

    async def test_semantic_diff(self):
        await apply_action(
            self.store,
            self.log,
            EngineAction.UPDATE_UNIT,
            Party.A,
            1,
            {"content": "x", "what_changed": "claim narrowed", "why": "new evidence"},
        )
        await apply_action(
            self.store,
            self.log,
            EngineAction.UPDATE_MAP,
            Party.A,
            1,
            {"title": "verify X→Y", "status": "active", "what_changed": "reopened"},
        )
        diff = build_semantic_diff(await self.log.list(1), Party.A, 1)
        self.assertIn("ru_a_0001", diff)
        self.assertIn("claim narrowed", diff)
        self.assertIn("map_a_0001", diff)

    async def test_argument_evidence_rebuttal_are_first_class_and_versioned(self):
        await self.store.save_source(Source(source_id="src_0001", title="study"), "sess_1")
        created = await apply_action(
            self.store, self.log, EngineAction.UPDATE_ARGUMENT, Party.A, 1,
            {
                "title": "Mechanism", "claim": "P", "burden": "show P",
                "criterion": "comparative effect", "warrant": ["P1", "P2"],
                "impact": "I", "scope": "S", "status": "draft",
            },
        )
        self.assertEqual(created.target.id, "arg_a_0001")
        await apply_action(
            self.store, self.log, EngineAction.RECORD_EVIDENCE, Party.A, 1,
            {
                "source_id": "src_0001", "argument_id": "arg_a_0001",
                "proposition": "P1", "finding": "F", "method": "M",
                "limitations": "L", "provenance": "original",
            },
        )
        await apply_action(
            self.store, self.log, EngineAction.UPDATE_ARGUMENT, Party.A, 2,
            {
                "argument_id": "arg_a_0001",
                "evidence_ids": ["ev_a_0001"],
                "material_source_ids": ["src_0001"],
            },
        )
        argument = await self.store.load_argument("arg_a_0001")
        self.assertEqual(argument.version, 2)
        self.assertEqual(argument.material_source_ids, ["src_0001"])
        self.assertEqual(argument.missing_proof_fields(), [])
        revisions = await self.store.list_argument_revisions("arg_a_0001")
        self.assertEqual([item.version for item in revisions], [1, 2])

        rebuttal = await apply_action(
            self.store, self.log, EngineAction.UPDATE_REBUTTAL, Party.B, 2,
            {
                "target_agent": "A", "target_argument_id": "arg_a_0001",
                "target_version": 1, "title": "Break P1",
                "reconstruction": "A claims P through P1", "attack_type": "warrant",
                "attack": "P1 does not imply P2", "why_it_matters": "the chain breaks",
            },
        )
        self.assertEqual(rebuttal.target.id, "reb_b_0001")
        saved = await self.store.load_rebuttal("reb_b_0001")
        self.assertEqual(saved.target_version, 1)

    async def test_new_argument_rejects_empty_placeholder(self):
        with self.assertRaisesRegex(ValueError, "empty placeholder"):
            await apply_action(
                self.store, self.log, EngineAction.UPDATE_ARGUMENT, Party.A, 1,
                {"what_changed": "reserve a slot"},
            )
        self.assertEqual(await self.store.list_arguments("sess_1", Party.A), [])

    async def test_position_cannot_revise_opponent_argument(self):
        await apply_action(
            self.store, self.log, EngineAction.UPDATE_ARGUMENT, Party.A, 1,
            {
                "title": "A case", "claim": "P", "burden": "show P",
                "warrant": ["P1", "P2"], "impact": "I", "scope": "S",
            },
        )
        with self.assertRaisesRegex(ValueError, "not owned by position B"):
            await apply_action(
                self.store, self.log, EngineAction.UPDATE_ARGUMENT, Party.B, 1,
                {"argument_id": "arg_a_0001", "claim": "not P"},
            )
        saved = await self.store.load_argument("arg_a_0001")
        self.assertEqual(saved.claim, "P")
        self.assertEqual(saved.version, 1)

    async def test_position_cannot_hijack_rebuttal_or_attack_own_argument(self):
        await apply_action(
            self.store, self.log, EngineAction.UPDATE_ARGUMENT, Party.A, 1,
            {
                "title": "A case", "claim": "P", "burden": "show P",
                "warrant": ["P1", "P2"], "impact": "I", "scope": "S",
            },
        )
        await apply_action(
            self.store, self.log, EngineAction.UPDATE_ARGUMENT, Party.B, 1,
            {
                "title": "B case", "claim": "not P", "burden": "show not P",
                "warrant": ["B1", "B2"], "impact": "I", "scope": "S",
            },
        )
        await apply_action(
            self.store, self.log, EngineAction.UPDATE_REBUTTAL, Party.A, 2,
            {
                "target_agent": "B", "target_argument_id": "arg_b_0001",
                "title": "attack", "reconstruction": "not P",
                "attack_type": "warrant", "attack": "B1 fails",
                "why_it_matters": "not P fails",
            },
        )
        with self.assertRaisesRegex(ValueError, "not owned by position B"):
            await apply_action(
                self.store, self.log, EngineAction.UPDATE_REBUTTAL, Party.B, 3,
                {
                    "rebuttal_id": "reb_a_0001", "target_agent": "A",
                    "target_argument_id": "arg_a_0001", "attack": "replace",
                },
            )
        with self.assertRaisesRegex(ValueError, "against own argument"):
            await apply_action(
                self.store, self.log, EngineAction.UPDATE_REBUTTAL, Party.B, 3,
                {
                    "target_agent": "A", "target_argument_id": "arg_b_0001",
                    "title": "self attack", "reconstruction": "not P",
                    "attack_type": "warrant", "attack": "B1 fails",
                    "why_it_matters": "not P fails",
                },
            )


if __name__ == "__main__":
    unittest.main()
