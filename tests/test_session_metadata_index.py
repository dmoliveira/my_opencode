from __future__ import annotations

import importlib
import json
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


class SessionMetadataIndexTest(unittest.TestCase):
    def test_update_writes_parseable_atomic_index(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sessions" / "index.json"
            result = module.update_session_index(
                {"timestamp": "2026-07-11T00:00:00+00:00", "cwd": "/repo", "reason": "test"},
                path,
            )
            self.assertEqual("PASS", result["result"])
            self.assertEqual("test", json.loads(path.read_text())["sessions"][0]["last_reason"])
            self.assertFalse(list(path.parent.glob(".index.json.*.tmp")))


    def test_concurrent_updates_preserve_all_events(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json"
            def update(reason: str) -> None:
                module.update_session_index(
                    {"timestamp": "2026-07-11T00:00:00+00:00", "cwd": "/repo", "reason": reason},
                    path,
                )
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(update, ["first", "second"]))
            saved = json.loads(path.read_text())
            self.assertEqual(2, saved["sessions"][0]["event_count"])
            self.assertEqual({"first", "second"}, set(saved["sessions"][0]["reasons"]))

    def test_malformed_index_is_preserved_and_reported(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json"
            path.write_text("{not json", encoding="utf-8")
            result = module.update_session_index({"cwd": "/repo"}, path)
            self.assertEqual("FAIL", result["result"])
            self.assertIn("malformed", result["error"])
            self.assertEqual("{not json", path.read_text(encoding="utf-8"))

if __name__ == "__main__":
    unittest.main()
