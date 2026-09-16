import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web.pdf_report import build_pdf_report
from web.server import build_demo


class TestPdfReport(unittest.TestCase):
    def test_builds_readable_pdf_from_public_result(self):
        result = asyncio.run(build_demo())
        self.assertEqual(result["contract_version"], "2")
        self.assertEqual(result["session"]["status"], "human_review")
        self.assertEqual(result["metrics"]["passes"], 8)
        self.assertGreaterEqual(result["metrics"]["arguments"], 6)
        self.assertGreaterEqual(result["metrics"]["rebuttals"], 4)
        for party in ("A", "B"):
            self.assertEqual(result["plans"][party]["status"], "ready_to_conclude")
            self.assertGreaterEqual(len(result["plan_revisions"][party]), 4)
        pdf = build_pdf_report(result)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf), 10_000)
        self.assertNotIn(b"argument_id", pdf)


if __name__ == "__main__":
    unittest.main()
