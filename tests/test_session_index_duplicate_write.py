from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import session_metadata_index as owner


class SessionIndexDuplicateWriteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="index-duplicate-write-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.root.chmod(0o700)
        self.index = self.root / "index.json"
        self.quarantine = self.root / "quarantine"
        self.now = datetime.now(UTC).isoformat()

    def _write_index(self, ids: list[str]) -> None:
        rows = [
            {
                "session_id": identifier,
                "cwd": f"/synthetic/{number}",
                "started_at": self.now,
                "last_event_at": self.now,
                "event_count": 0,
                "events": [],
            }
            for number, identifier in enumerate(ids)
        ]
        self.index.write_text(
            json.dumps({"version": 1, "sessions": rows}), encoding="utf-8"
        )
        self.index.chmod(0o600)

    def _index_snapshot(self) -> tuple:
        info = self.index.stat()
        return (
            self.index.read_bytes(),
            info.st_dev,
            info.st_ino,
            info.st_mode,
            info.st_nlink,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )

    def test_any_duplicate_blocks_publication_before_retention(self) -> None:
        duplicate = "PRIVATE-DUPLICATE-ID"
        # A unique target is also unsafe: normal retention prunes the entire index.
        cases = (
            ([duplicate, duplicate], duplicate),
            ([duplicate, "ses_unique", duplicate], "ses_unique"),
            ([duplicate, duplicate, "ses_unique"], "ses_new"),
        )
        policy = {
            "max_sessions": 1,
            "max_age_days": 1,
            "max_events_per_session": 24,
            "max_reasons_per_session": 12,
            "max_plan_ids_per_session": 12,
        }
        for ids, target in cases:
            with self.subTest(target=target):
                self._write_index(ids)
                before = self._index_snapshot()
                with (
                    patch.dict(
                        os.environ,
                        {
                            "OPENCODE_SESSION_ID": target,
                            "MY_OPENCODE_SESSION_INDEX_QUARANTINE_DIR": str(
                                self.quarantine
                            ),
                        },
                    ),
                    patch.object(
                        owner, "_load_policy", return_value=policy
                    ) as load_policy,
                    patch.object(
                        owner, "_session_id", wraps=owner._session_id
                    ) as select_id,
                    patch.object(
                        owner, "_prune_sessions", wraps=owner._prune_sessions
                    ) as prune,
                    patch.object(owner, "_atomic_write_json") as publish,
                    patch.object(owner, "_quarantine_corrupt_index") as quarantine,
                ):
                    result = owner.update_session_index(
                        {
                            "timestamp": self.now,
                            "cwd": "/synthetic/new",
                            "reason": "test",
                        },
                        self.index,
                    )
                self.assertEqual("FAIL", result["result"])
                self.assertEqual("session_index_duplicate_id", result["reason_code"])
                self.assertIsNone(result["quarantine"])
                self.assertIsNone(result["corruption_kind"])
                self.assertNotIn(duplicate, json.dumps(result))
                self.assertTrue(result["recovery_steps"])
                self.assertFalse(self.quarantine.exists())
                load_policy.assert_not_called()
                select_id.assert_not_called()
                prune.assert_not_called()
                publish.assert_not_called()
                quarantine.assert_not_called()
                self.assertEqual(before, self._index_snapshot())
                # The owner lock can be created even though index publication is refused.
                self.assertTrue((self.root / "index.json.lock").is_file())

    def test_unique_and_case_distinct_ids_still_update_synthetic_index(self) -> None:
        self._write_index(["ses_example", "SES_example"])
        policy = {
            "max_sessions": 120,
            "max_age_days": 30,
            "max_events_per_session": 24,
            "max_reasons_per_session": 12,
            "max_plan_ids_per_session": 12,
        }
        with (
            patch.dict(os.environ, {"OPENCODE_SESSION_ID": "ses_example"}),
            patch.object(owner, "_load_policy", return_value=policy),
        ):
            result = owner.update_session_index(
                {"timestamp": self.now, "cwd": "/synthetic/new", "reason": "test"},
                self.index,
            )
        self.assertEqual("PASS", result["result"])
        rows = json.loads(self.index.read_text(encoding="utf-8"))["sessions"]
        counts = {row["session_id"]: row["event_count"] for row in rows}
        self.assertEqual({"ses_example": 1, "SES_example": 0}, counts)

    def test_digest_cli_reports_partial_effect_but_preserves_duplicate_index(
        self,
    ) -> None:
        identifier = "PRIVATE-DUPLICATE-ID"
        self._write_index([identifier, identifier])
        before = self._index_snapshot()
        digest = self.root / "digest.json"
        config = self.root / "synthetic-config.json"
        config.write_text("{}", encoding="utf-8")
        config.chmod(0o600)
        env = {
            "HOME": str(self.root),
            "PATH": os.defpath,
            "TMPDIR": str(self.root),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_CACHE_HOME": str(self.root / "cache"),
            "XDG_STATE_HOME": str(self.root / "state"),
            "MY_OPENCODE_SESSION_INDEX_PATH": str(self.index),
            "MY_OPENCODE_SESSION_INDEX_QUARANTINE_DIR": str(self.quarantine),
            "MY_OPENCODE_DIGEST_PATH": str(digest),
            "MY_OPENCODE_PLAN_RUNTIME_PATH": str(self.root / "plan.json"),
            "OPENCODE_CONFIG_PATH": str(config),
            "OPENCODE_SESSION_ID": identifier,
            "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
        }
        run = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPTS / "session_digest.py"),
                "run",
                "--reason",
                "manual",
            ],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(1, run.returncode, run.stderr)
        self.assertEqual("", run.stderr)
        self.assertIn("session_index_result: FAIL", run.stdout)
        self.assertIn("session_index_reason: session_index_duplicate_id", run.stdout)
        self.assertNotIn(identifier, run.stdout + run.stderr)
        self.assertEqual(before, self._index_snapshot())
        self.assertFalse(self.quarantine.exists())
        self.assertTrue(
            digest.is_file(), "digest may be published before index failure"
        )
        saved = json.loads(digest.read_text(encoding="utf-8"))
        self.assertEqual("FAIL", saved["session_index"]["result"])
        self.assertEqual(
            "session_index_duplicate_id", saved["session_index"]["reason_code"]
        )

        doctor = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPTS / "session_digest.py"),
                "doctor",
                "--json",
            ],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(1, doctor.returncode, doctor.stderr)
        report = json.loads(doctor.stdout)
        self.assertEqual("FAIL", report["result"])
        self.assertEqual(
            "session_index_duplicate_id", report["session_index"]["reason_code"]
        )
        self.assertEqual(
            saved["session_index"]["recovery_steps"], report["quick_fixes"]
        )
        self.assertNotIn("run /digest run --reason manual", report["quick_fixes"])
        self.assertEqual(before, self._index_snapshot())

    def test_unindexed_handoff_does_not_recommend_blind_digest_retry(self) -> None:
        self._write_index(["ses_duplicate", "ses_duplicate"])
        before = self._index_snapshot()
        env = {
            "HOME": str(self.root),
            "PATH": os.defpath,
            "TMPDIR": str(self.root),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_CACHE_HOME": str(self.root / "cache"),
            "XDG_STATE_HOME": str(self.root / "state"),
            "MY_OPENCODE_SESSION_INDEX_PATH": str(self.index),
            "MY_OPENCODE_DIGEST_PATH": str(self.root / "digest.json"),
            "MY_OPENCODE_SESSION_REDACT_DEFAULT": "false",
            "OPENCODE_SESSION_ID": "ses_unindexed",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        for redact in (False, True):
            with self.subTest(redact=redact):
                args = [
                    sys.executable,
                    "-B",
                    str(SCRIPTS / "session_command.py"),
                    "handoff",
                    "--json",
                ]
                if redact:
                    args.append("--redact")
                result = subprocess.run(
                    args,
                    cwd=self.root,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
                self.assertEqual(1, result.returncode, result.stderr)
                payload = json.loads(result.stdout)
                if redact:
                    self.assertEqual(
                        {
                            "result": "FAIL",
                            "command": "handoff",
                            "redacted": True,
                            "error_code": "session_not_indexed",
                        },
                        payload,
                    )
                else:
                    self.assertIn("inspect", payload["error"].lower())
                    self.assertNotIn("run /digest run first", payload["error"])
                self.assertEqual(before, self._index_snapshot())
                self.assertFalse((self.root / "digest.json").exists())


if __name__ == "__main__":
    unittest.main()
