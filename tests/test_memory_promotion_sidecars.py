from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


class MemoryPromotionSidecarsTest(unittest.TestCase):
    def _module(
        self,
        root: Path,
        *,
        digest_path: Path | None = None,
        index_path: Path | None = None,
        db_path: Path | None = None,
    ):
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        digest = digest_path or root / "digest.json"
        index = index_path or root / "index.json"
        database = db_path or root / "shared-memory.db"
        env = {
            "HOME": str(root),
            "MY_OPENCODE_DIGEST_PATH": str(digest),
            "MY_OPENCODE_SESSION_INDEX_PATH": str(index),
            "MY_OPENCODE_SHARED_MEMORY_PATH": str(database),
            "MY_OPENCODE_WORKFLOW_STATE_PATH": str(root / "workflow.json"),
            "MY_OPENCODE_CLAIMS_PATH": str(root / "claims.json"),
            "MY_OPENCODE_DOCTOR_REPORT_PATH": str(root / "doctor.json"),
            "CI": "true",
        }
        with patch.dict(os.environ, env):
            importlib.reload(importlib.import_module("session_metadata_index"))
            importlib.reload(importlib.import_module("shared_memory_runtime"))
            module = importlib.reload(importlib.import_module("memory_command"))
        return module, env, digest, index, database

    def _run(self, module, env: dict[str, str], args: list[str]) -> tuple[int, dict]:
        with patch.dict(os.environ, env), contextlib.redirect_stdout(
            io.StringIO()
        ) as output:
            code = module.cmd_promote([*args, "--json"])
        return code, json.loads(output.getvalue())

    def _write_json(self, path: Path, payload: dict, mode: int = 0o600) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")
        path.chmod(mode)

    def test_unsafe_or_malformed_digest_never_connects(self) -> None:
        for content, mode, reason_code in (
            ('{"timestamp": "private"}', 0o644, "session_sidecar_insecure_permissions"),
            ("{malformed", 0o600, "session_sidecar_malformed_json"),
        ):
            with self.subTest(reason_code=reason_code), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                module, env, digest, _index, database = self._module(root)
                digest.write_text(content, encoding="utf-8")
                digest.chmod(mode)
                with patch.object(module, "connect") as connect_mock:
                    code, payload = self._run(
                        module,
                        env,
                        ["--source", "digest"],
                    )
                self.assertEqual(1, code)
                self.assertEqual(reason_code, payload["reason_code"])
                self.assertEqual([], payload["memories"])
                connect_mock.assert_not_called()
                for candidate in (
                    database,
                    Path(f"{database}-wal"),
                    Path(f"{database}-shm"),
                    Path(f"{database}-journal"),
                ):
                    self.assertFalse(candidate.exists())

    def test_source_all_index_failure_precedes_any_database_or_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module, env, digest, index, database = self._module(root)
            self._write_json(digest, {"timestamp": "digest"})
            index.write_text("{corrupt-index", encoding="utf-8")
            index.chmod(0o600)
            self._write_json(
                Path(env["MY_OPENCODE_WORKFLOW_STATE_PATH"]),
                {"active": {"run_id": "must-not-promote", "status": "passed"}},
            )
            with patch.object(module, "connect") as connect_mock:
                code, payload = self._run(module, env, ["--source", "all"])
            self.assertEqual(1, code)
            self.assertEqual("session_index_corrupt", payload["reason_code"])
            self.assertEqual(0, payload["count"])
            connect_mock.assert_not_called()
            self.assertFalse(database.exists())

    def test_database_namespace_alias_is_rejected_before_connect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shared = root / "digest-and-memory.db"
            module, env, digest, _index, _database = self._module(
                root,
                digest_path=shared,
                db_path=shared,
            )
            self._write_json(digest, {"timestamp": "digest"})
            with patch.object(module, "connect") as connect_mock:
                code, payload = self._run(module, env, ["--source", "digest"])
            self.assertEqual(1, code)
            self.assertEqual("session_sidecar_alias", payload["reason_code"])
            connect_mock.assert_not_called()
            self.assertEqual({"timestamp": "digest"}, json.loads(shared.read_text()))

    def test_safe_digest_and_index_are_materialized_then_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module, env, digest, index, database = self._module(root)
            self._write_json(
                digest,
                {
                    "timestamp": "2026-07-30T00:00:00Z",
                    "reason": "manual",
                    "cwd": str(REPO_ROOT),
                    "git": {"branch": "main", "status_count": 0},
                    "plan_execution": {"status": "idle"},
                    "session_index": {"session_id": "safe-session"},
                },
            )
            self._write_json(
                index,
                {
                    "version": 1,
                    "generated_at": "2026-07-30T00:00:00Z",
                    "sessions": [
                        {
                            "session_id": "safe-session",
                            "cwd": str(REPO_ROOT),
                            "started_at": "2026-07-30T00:00:00Z",
                            "last_event_at": "2026-07-30T00:01:00Z",
                            "event_count": 1,
                            "last_reason": "manual",
                            "reasons": ["manual"],
                            "plan_ids": [],
                            "events": [],
                        }
                    ],
                },
            )

            code, payload = self._run(module, env, ["--source", "all"])
            self.assertEqual(0, code)
            self.assertEqual("PASS", payload["result"])
            self.assertEqual(2, payload["count"])
            self.assertTrue(database.exists())

    def test_unselected_malformed_digest_is_not_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module, env, digest, _index, database = self._module(root)
            digest.write_text("{malformed-but-unselected", encoding="utf-8")
            digest.chmod(0o600)
            code, payload = self._run(module, env, ["--source", "workflow"])
            self.assertEqual(0, code)
            self.assertEqual("PASS", payload["result"])
            self.assertEqual(0, payload["count"])
            self.assertTrue(database.exists())


if __name__ == "__main__":
    unittest.main()
