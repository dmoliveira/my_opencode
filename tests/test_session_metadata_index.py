from __future__ import annotations

import importlib
import json
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import unittest
from pathlib import Path
from unittest.mock import patch

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
            self.assertEqual({"events": 0, "reasons": 0, "plan_ids": 0}, result["pruned"])
            self.assertEqual("test", json.loads(path.read_text())["sessions"][0]["last_reason"])
            self.assertFalse(list(path.parent.glob(".index.json.*.tmp")))
            self.assertEqual(0o600, path.stat().st_mode & 0o777)


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
            self.assertEqual(2, sum(item["event_count"] for item in saved["sessions"]))
            self.assertIn(saved["sessions"][0]["last_reason"], {"first", "second"})

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

    def test_pruning_interprets_legacy_naive_timestamps_as_utc(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        sessions = [
            {"session_id": "naive", "last_event_at": "2026-07-26T12:00:00"},
            {"session_id": "earlier-offset", "last_event_at": "2026-07-27T01:00:00+02:00"},
            {"session_id": "later-utc", "last_event_at": "2026-07-26T23:30:00+00:00"},
            {"session_id": "invalid", "last_event_at": "not-a-timestamp"},
            {"session_id": "expired", "last_event_at": "2026-07-01T00:00:00"},
        ]
        with patch.object(
            module,
            "_utc_now",
            return_value=datetime(2026, 7, 27, 0, 0, tzinfo=UTC),
        ):
            result = module._prune_sessions(
                sessions,
                {"max_age_days": 7, "max_sessions": 10},
            )
        self.assertEqual(
            ["later-utc", "earlier-offset", "naive", "invalid"],
            [item["session_id"] for item in result],
        )
        self.assertEqual(UTC, module._parse_iso("2026-07-26T12:00:00").tzinfo)
        self.assertEqual(
            datetime.fromisoformat("2026-07-26T12:00:00+10:00").utcoffset(),
            module._parse_iso("2026-07-26T12:00:00+10:00").utcoffset(),
        )

    def test_session_command_orders_mixed_offsets_chronologically(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_command"))
        rows = module._session_rows(
            {
                "sessions": [
                    {"session_id": "earlier-offset", "last_event_at": "2026-07-27T01:00:00+02:00"},
                    {"session_id": "later-utc", "last_event_at": "2026-07-26T23:30:00+00:00"},
                    {"session_id": "legacy-naive", "last_event_at": "2026-07-26T23:15:00"},
                    {"session_id": "invalid", "last_event_at": "not-a-timestamp"},
                ]
            }
        )
        self.assertEqual(
            ["later-utc", "legacy-naive", "earlier-offset", "invalid"],
            [row["session_id"] for row in rows],
        )

    def test_fallback_identity_is_process_unique(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        previous = __import__("os").environ.pop("OPENCODE_SESSION_ID", None)
        try:
            first = module._session_id("2026-07-11T00:00:00+00:00", "/repo")
            second = module._session_id("2026-07-11T00:00:00+00:00", "/repo")
            self.assertNotEqual(first, second)
            self.assertTrue(first.startswith("/repo::2026-07-11T00:00:00+00:00::"))
        finally:
            if previous is not None:
                __import__("os").environ["OPENCODE_SESSION_ID"] = previous

if __name__ == "__main__":
    unittest.main()
