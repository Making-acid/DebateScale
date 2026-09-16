import json
import sys
import tempfile
import unittest
import threading
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web.server import (  # noqa: E402
    DEFAULT_MODEL_CONFIG,
    ExclusiveWorkbenchServer,
    JOBS,
    WorkbenchHandler,
    delete_failed_researches,
    delete_research_record,
    load_model_config,
    public_model_config,
    save_model_config,
    validate_model_config,
    _load_research,
    _save_research,
    _update_job,
)


class TestModelSettings(unittest.TestCase):
    def test_workbench_refuses_second_server_on_same_port(self):
        first = ExclusiveWorkbenchServer(("127.0.0.1", 0), WorkbenchHandler)
        try:
            port = first.server_address[1]
            with self.assertRaises(OSError):
                second = ExclusiveWorkbenchServer(
                    ("127.0.0.1", port), WorkbenchHandler
                )
                second.server_close()
        finally:
            first.server_close()

    def test_progress_events_and_per_agent_budgets_are_persisted(self):
        session_id = "research-progress-test"
        with tempfile.TemporaryDirectory() as temp_dir:
            JOBS[session_id] = {
                "id": session_id,
                "status": "running",
                "events": [],
                "event_seq": 0,
                "budgets": {},
            }
            try:
                with patch("web.server.JOB_STATE_DIR", Path(temp_dir)):
                    _update_job(
                        session_id,
                        agent="A",
                        message="正在搜索",
                        event={
                            "kind": "search", "title": "发起定向搜索",
                            "status": "working", "summary": "query",
                            "details": [], "agent": "A", "pass_no": 1,
                            "phase": "expansion",
                        },
                        budget={"research_calls": 3, "research_call_limit": 65},
                    )
                saved = JOBS[session_id]
                self.assertEqual(saved["events"][0]["seq"], 1)
                self.assertEqual(saved["events"][0]["kind"], "search")
                self.assertEqual(saved["budgets"]["A"]["research_calls"], 3)
            finally:
                JOBS.pop(session_id, None)

    def test_concurrent_progress_writes_share_one_atomic_snapshot_safely(self):
        session_id = "research-concurrent-progress"
        errors = []
        with tempfile.TemporaryDirectory() as temp_dir:
            JOBS[session_id] = {"id": session_id, "status": "running", "events": [], "event_seq": 0, "budgets": {}}
            try:
                def write(agent):
                    try:
                        for index in range(12):
                            _update_job(session_id, agent=agent, message=f"{agent}-{index}")
                    except Exception as exc:  # pragma: no cover - assertion reports it
                        errors.append(exc)

                with patch("web.server.JOB_STATE_DIR", Path(temp_dir)):
                    threads = [threading.Thread(target=write, args=(agent,)) for agent in ("A", "B")]
                    for thread in threads:
                        thread.start()
                    for thread in threads:
                        thread.join()
                self.assertEqual(errors, [])
                saved = json.loads((Path(temp_dir) / f"{session_id}.json").read_text(encoding="utf-8"))
                self.assertIn(saved["message"].split("-")[0], {"A", "B"})
            finally:
                JOBS.pop(session_id, None)

    def test_failed_history_moves_to_recoverable_trash(self):
        session_id = "research-delete-test"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            jobs = root / "jobs"
            researches = root / "researches"
            trash = root / "trash"
            jobs.mkdir()
            (jobs / f"{session_id}.json").write_text("{}", encoding="utf-8")
            JOBS[session_id] = {"id": session_id, "status": "failed"}
            try:
                with patch("web.server.JOB_STATE_DIR", jobs), patch(
                    "web.server.RESEARCH_DIR", researches
                ), patch("web.server.TRASH_DIR", trash):
                    result = delete_failed_researches()
                    self.assertEqual(result["deleted"], 1)
                    self.assertFalse((jobs / f"{session_id}.json").exists())
                    self.assertEqual(len(list(trash.rglob("*.job.json"))), 1)
                    with self.assertRaises(KeyError):
                        delete_research_record(session_id)
            finally:
                JOBS.pop(session_id, None)

    def test_research_result_roundtrip(self):
        result = {"session": {"session_id": "research-test", "question": "测试辩题"}}
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("web.server.RESEARCH_DIR", Path(temp_dir)):
                _save_research(result)
                self.assertEqual(_load_research("research-test"), result)

    def test_public_projection_never_exposes_api_key(self):
        config = dict(DEFAULT_MODEL_CONFIG)
        config.update({"api_key": "sk-secret-value", "model_a": "a", "model_b": "b"})
        public = public_model_config(config)
        self.assertNotIn("api_key", public)
        self.assertTrue(public["has_api_key"])
        self.assertEqual(public["api_key_hint"], "••••alue")
        self.assertTrue(public["ready"])

    def test_blank_key_keeps_existing_secret(self):
        existing = dict(DEFAULT_MODEL_CONFIG)
        existing["provider"] = "generic-chat"
        existing["api_key"] = "sk-existing"
        result = validate_model_config(
            {
                "provider": "generic-chat",
                "base_url": "https://example.test/v1/",
                "api_key": "",
                "model_a": "model-a",
                "model_b": "model-b",
                "timeout_seconds": 180,
            },
            existing,
        )
        self.assertEqual(result["api_key"], "sk-existing")
        self.assertEqual(result["base_url"], "https://example.test/v1")
        self.assertEqual(result["provider"], "generic-chat")

    def test_local_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "model_config.json"
            config = dict(DEFAULT_MODEL_CONFIG)
            config.update({"api_key": "secret", "model_a": "a", "model_b": "b"})
            save_model_config(config, path)
            self.assertEqual(load_model_config(path), config)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["api_key"], "secret")

    def test_rejects_invalid_url_and_timeout(self):
        with self.assertRaisesRegex(ValueError, "API 地址"):
            validate_model_config({"base_url": "not-a-url"})
        with self.assertRaisesRegex(ValueError, "10–600"):
            validate_model_config(
                {"base_url": "https://example.test/v1", "timeout_seconds": 5}
            )

    def test_local_provider_is_ready_without_key(self):
        config = validate_model_config({
            "provider": "ollama", "base_url": "http://localhost:11434/v1",
            "model_a": "qwen3-coder:32b", "model_b": "qwen3-coder:32b",
        })
        self.assertEqual(config["auth_mode"], "none")
        self.assertTrue(public_model_config(config)["ready"])


if __name__ == "__main__":
    unittest.main()
