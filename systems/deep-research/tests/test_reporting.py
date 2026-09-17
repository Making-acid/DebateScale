import asyncio
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from cre.engine import build_editorial_packet, compile_reader_report
from cre.ports.llm import LLMTurn, LLMUsage, ToolCall
from web.pdf_report import build_pdf_report
from web.server import build_demo


class EditorLLM:
    async def run(self, messages, tools=None):
        headings = (
            "# 测试辩题\n\n## 先读结论\n\n## 这道题究竟在争什么\n\n"
            "## 正方\n\n## 反方\n\n## 真正决定比赛的交锋\n\n"
            "## 怎样把研究转成赛场表达\n\n## 使用前仍需注意\n\n"
        )
        markdown = headings + "核心内容见 arg_a_0001。" + ("这是经过编辑、可供读者直接阅读的完整论证。" * 220)
        return LLMTurn(text=markdown, usage=LLMUsage(100, 50))


class BrokenEditorLLM:
    async def run(self, messages, tools=None):
        raise ConnectionError("temporary disconnect")


class TestReporting(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.data = await build_demo()

    async def test_editorial_packet_excludes_engine_labels_and_history(self):
        packet, sources = build_editorial_packet(self.data)
        serialized = json.dumps(packet, ensure_ascii=False)
        for forbidden in ("argument_id", "evidence_id", "target_argument_id", "version", "mutations", "passes", "plan_id"):
            self.assertNotIn(forbidden, serialized)
        self.assertTrue(packet["affirmative_material"]["arguments"])
        self.assertIsInstance(sources, list)

    async def test_model_editor_creates_reader_contract_and_sources(self):
        report, meta = await compile_reader_report(self.data, EditorLLM())
        self.assertEqual(meta["mode"], "model_edited")
        self.assertNotRegex(report["markdown"], r"(?i)\b(?:arg|map|reb|ru|mut)_[a-z0-9_-]+\b")
        self.assertEqual(report["title"], self.data["session"]["question"])
        self.assertTrue(report["markdown"].startswith("# 测试辩题"))
        self.assertIn("sources", report)

    async def test_editor_failure_falls_back_without_failing_research(self):
        report, meta = await compile_reader_report(self.data, BrokenEditorLLM())
        self.assertEqual(meta["mode"], "deterministic_fallback")
        self.assertTrue(report["sides"]["affirmative"]["arguments"])
        self.assertTrue(report["sides"]["negative"]["arguments"])
        pdf = build_pdf_report({**self.data, "reader_report": report})
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf), 5000)


if __name__ == "__main__":
    unittest.main()
