import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cre.models import (
    Argument,
    EngineAction,
    Issue,
    IssueResolution,
    IssueState,
    MapStatus,
    Mutation,
    Party,
    ResearchBudget,
    ResearchMapEntry,
    ResearchSession,
    ResearchUnit,
    SessionStatus,
    Source,
    TargetRef,
    TargetType,
    UnitStatus,
)
from cre.serialization import from_dict, from_json, to_dict, to_json


class TestSerialization(unittest.TestCase):
    def test_reasoning_argument_does_not_need_decorative_evidence(self):
        base = dict(
            argument_id="arg_a_0001",
            title="Non-arbitrary belief",
            claim="A belief needs reasons to be non-arbitrary.",
            burden="Show why reasons distinguish belief from guessing.",
            warrant=["Unreasoned choices are symmetric.", "Reasons break that symmetry."],
            impact="The other side cannot justify preferring one belief.",
            scope="Beliefs offered as guides to judgment or action.",
        )
        reasoning = Argument(
            **base, support_type="reasoning", material_source_ids=["src_debate_1"],
            original_contribution="Connects arbitrariness to the comparative burden.",
        )
        empirical = Argument(**base, support_type="empirical")
        self.assertNotIn("evidence_ids", reasoning.missing_proof_fields())
        self.assertIn("evidence_ids", empirical.missing_proof_fields())
        self.assertEqual(
            from_dict(Argument, to_dict(reasoning)).material_source_ids,
            ["src_debate_1"],
        )
        self.assertIn(
            "comparative burden",
            from_dict(Argument, to_dict(reasoning)).original_contribution,
        )

    def test_unit_roundtrip(self):
        unit = ResearchUnit(
            unit_id="ru_a_0017",
            status=UnitStatus.TENTATIVE,
            source_ids=["s_1", "s_2"],
            content="# Finding\n\nsome markdown",
        )
        restored = from_dict(ResearchUnit, to_dict(unit))
        self.assertEqual(restored, unit)

    def test_map_roundtrip_with_none_metadata(self):
        entry = ResearchMapEntry(
            map_id="map_009",
            title="短期情绪噪声",
            status=MapStatus.ACTIVE,
            importance="high",
            coverage=None,
            uncertainty="high",
        )
        restored = from_dict(ResearchMapEntry, to_dict(entry))
        self.assertEqual(restored, entry)

    def test_issue_closed_with_disagreement(self):
        issue = Issue(
            issue_id="issue_014",
            from_agent=Party.A,
            to_agent=Party.B,
            target=TargetRef(type=TargetType.UNIT, id="ru_a_0017", section="implication"),
            priority="high",
            title="causal claim unsupported",
            body="only correlational evidence",
            state=IssueState.CLOSED,
            resolution=IssueResolution.DISAGREEMENT,
        )
        restored = from_dict(Issue, to_dict(issue))
        self.assertEqual(restored, issue)
        self.assertEqual(restored.state, IssueState.CLOSED)
        self.assertEqual(restored.resolution, IssueResolution.DISAGREEMENT)

    def test_mutation_roundtrip(self):
        m = Mutation(
            mutation_id="mut_003",
            seq=3,
            session_id="sess_1",
            pass_no=1,
            agent=Party.A,
            action=EngineAction.UPDATE_UNIT,
            what_changed="claim narrowed",
            why="new longitudinal evidence",
            target=TargetRef(type=TargetType.UNIT, id="ru_a_0017"),
            payload={"content": "new body"},
            created_at="2026-09-04T10:00:00Z",
        )
        restored = from_dict(Mutation, to_dict(m))
        self.assertEqual(restored, m)
        self.assertEqual(restored.action, EngineAction.UPDATE_UNIT)

    def test_source_roundtrip(self):
        s = Source(
            source_id="src_1",
            url="https://example.com/paper",
            title="A Paper",
            content="abstract...",
            metadata={"publisher": "x", "year": 2026},
            discovered_by=Party.B,
        )
        restored = from_dict(Source, to_dict(s))
        self.assertEqual(restored, s)

    def test_session_roundtrip(self):
        session = ResearchSession(
            session_id="sess_1",
            question="Does X cause Y?",
            position_a="X causes Y",
            position_b="X does not cause Y",
            status=SessionStatus.CONTINUOUS,
            agents=[Party.A, Party.B],
            current_cycle=2,
            next_agent=Party.B,
            budget=ResearchBudget(max_tool_calls_per_pass=50),
        )
        restored = from_dict(ResearchSession, to_dict(session))
        self.assertEqual(restored, session)
        self.assertEqual(restored.position_for(Party.A), "X causes Y")
        self.assertEqual(restored.position_for(Party.B), "X does not cause Y")

    def test_enum_serializes_to_str(self):
        d = to_dict(ResearchUnit(unit_id="ru_1", status=UnitStatus.STABLE))
        self.assertEqual(d["status"], "stable")

    def test_json_roundtrip(self):
        unit = ResearchUnit(
            unit_id="ru_a_0017",
            status=UnitStatus.STABLE,
            source_ids=["s_1"],
            content="body",
        )
        restored = from_json(ResearchUnit, to_json(unit))
        self.assertEqual(restored, unit)


if __name__ == "__main__":
    unittest.main()
