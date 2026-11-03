from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import session_metadata_index as owner


class SessionIndexDuplicateJsonKeysTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="index-duplicate-json-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.root.chmod(0o700)
        self.index = self.root / "index.json"
        self.digest = self.root / "digest.json"
        self.quarantine = self.root / "quarantine"
        self.config = self.root / "synthetic-config.json"
        self.config.write_text("{}", encoding="utf-8")
        self.config.chmod(0o600)

    def _write_index(self, raw: bytes) -> None:
        self.index.write_bytes(raw)
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

    def _environment(self) -> dict[str, str]:
        return {
            "HOME": str(self.root),
            "PATH": os.defpath,
            "TMPDIR": str(self.root),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_CACHE_HOME": str(self.root / "cache"),
            "XDG_STATE_HOME": str(self.root / "state"),
            "MY_OPENCODE_SESSION_INDEX_PATH": str(self.index),
            "MY_OPENCODE_SESSION_INDEX_QUARANTINE_DIR": str(self.quarantine),
            "MY_OPENCODE_DIGEST_PATH": str(self.digest),
            "MY_OPENCODE_PLAN_RUNTIME_PATH": str(self.root / "plan.json"),
            "MY_OPENCODE_SESSION_REDACT_DEFAULT": "false",
            "OPENCODE_CONFIG_PATH": str(self.config),
            "OPENCODE_SESSION_ID": "ses_synthetic",
            "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
        }

    def _run(self, script: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / script), *args],
            cwd=self.root,
            env=self._environment(),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def test_duplicate_decoded_object_keys_are_rejected_at_every_depth(self) -> None:
        fixtures = (
            b'{"version":1,"sessions":[],"sessions":[]}',
            b'{"version":1,"sessions":[],"sess\\u0069ons":[]}',
            b'{"version":1,"sessions":[{"session_id":"a","session_id":"b"}]}',
            b'{"version":1,"sessions":[{"session_id":"a","events":[{"x":1,"x":2}]}]}',
            b'{"version":1,"sessions":[],"extra":{"PRIVATE-KEY":"PRIVATE-ONE","PRIVATE-KEY":"PRIVATE-TWO"}}',
            b'[{"PRIVATE-KEY":"PRIVATE-ONE","PRIVATE-KEY":"PRIVATE-TWO"}]',
        )
        for raw in fixtures:
            with self.subTest(raw=raw[:80]):
                with self.assertRaises(owner.SessionIndexError) as raised:
                    owner._parse_index_bytes(raw)
                self.assertNotIsInstance(raised.exception, owner.SessionIndexCorruption)
                self.assertEqual(
                    "session_index_duplicate_key", raised.exception.reason_code
                )
                self.assertNotIn("PRIVATE-KEY", str(raised.exception))
                self.assertNotIn("PRIVATE-ONE", str(raised.exception))
                self.assertNotIn("PRIVATE-TWO", str(raised.exception))

    def test_valid_objects_with_repeated_keys_in_separate_objects_are_preserved(
        self,
    ) -> None:
        value = {
            "version": 1,
            "sessions": [
                {"session_id": "ses_one", "events": [{"same": "one"}]},
                {"session_id": "ses_two", "events": [{"same": "two"}]},
            ],
            "extra": {"\u00e9": 1, "e\u0301": 2},
        }
        parsed = owner._parse_index_bytes(json.dumps(value).encode())
        self.assertEqual(value["sessions"], parsed["sessions"])

    def test_syntax_error_after_nested_duplicate_remains_corruption(self) -> None:
        raw = (
            b'{"version":1,"sessions":[{"session_id":"a","session_id":"b"}],"trailing":'
        )
        with self.assertRaises(owner.SessionIndexCorruption) as raised:
            owner._parse_index_bytes(raw)
        self.assertEqual("malformed_json", raised.exception.corruption_kind)
        self.assertEqual(raw, raised.exception.raw_bytes)

    def test_readers_fail_closed_without_quarantine_or_content_disclosure(self) -> None:
        self._write_index(
            b'{"version":1,"sessions":[{"session_id":"PRIVATE-ONE"}],'
            b'"sessions":[{"session_id":"PRIVATE-TWO"}],'
            b'"PRIVATE-KEY":"PRIVATE-ONE","PRIVATE-KEY":"PRIVATE-TWO"}'
        )
        before = self._index_snapshot()
        commands = (
            (["show", "ses_synthetic", "--json"], "show", False),
            (["show", "ses_synthetic"], "show", False),
            (["current", "--json"], "current", False),
            (["list", "--json"], "list", False),
            (["handoff", "--json"], "handoff", False),
            (["handoff", "--redact", "--json"], "handoff", True),
            (["handoff", "--redact"], "handoff", True),
            (["search", "synthetic", "--redact", "--json"], "search", True),
            (["search", "synthetic", "--redact"], "search", True),
        )
        for args, command, redacted in commands:
            with self.subTest(args=args):
                result = self._run("session_command.py", *args)
                self.assertEqual(1, result.returncode, result.stderr)
                self.assertEqual("", result.stderr)
                if "--json" not in args:
                    expected = (
                        "error_code: session_index_unavailable"
                        if redacted
                        else "reason_code: session_index_duplicate_key"
                    )
                    self.assertIn(expected, result.stdout)
                elif redacted:
                    payload = json.loads(result.stdout)
                    self.assertEqual(
                        {
                            "result": "FAIL",
                            "command": command,
                            "redacted": True,
                            "error_code": "session_index_unavailable",
                        },
                        payload,
                    )
                else:
                    payload = json.loads(result.stdout)
                    self.assertEqual("FAIL", payload["result"])
                    self.assertEqual(
                        "session_index_duplicate_key", payload["reason_code"]
                    )
                self.assertNotIn("PRIVATE-ONE", result.stdout + result.stderr)
                self.assertNotIn("PRIVATE-TWO", result.stdout + result.stderr)
                self.assertNotIn("PRIVATE-KEY", result.stdout + result.stderr)
                self.assertEqual(before, self._index_snapshot())
                self.assertFalse(self.quarantine.exists())
                self.assertEqual(
                    {"index.json", "synthetic-config.json"},
                    {path.name for path in self.root.iterdir()},
                )

    def test_writer_refuses_ambiguous_json_before_publish_or_quarantine(self) -> None:
        raw = (
            b'{"version":1,"sessions":[{"session_id":"PRIVATE-FIRST"}],'
            b'"sessions":[{"session_id":"PRIVATE-SECOND"}]}'
        )
        self._write_index(raw)
        before = self._index_snapshot()
        with (
            patch.dict(os.environ, self._environment(), clear=True),
            patch.object(owner, "_atomic_write_json") as publish,
            patch.object(owner, "_quarantine_corrupt_index") as quarantine,
        ):
            result = owner.update_session_index({"cwd": "/synthetic"}, self.index)
        self.assertEqual("FAIL", result["result"])
        self.assertEqual("session_index_duplicate_key", result["reason_code"])
        self.assertIsNone(result["corruption_kind"])
        self.assertIsNone(result["quarantine"])
        self.assertNotIn("PRIVATE-FIRST", json.dumps(result))
        self.assertNotIn("PRIVATE-SECOND", json.dumps(result))
        self.assertEqual(before, self._index_snapshot())
        self.assertFalse(self.quarantine.exists())
        publish.assert_not_called()
        quarantine.assert_not_called()

    def test_malformed_json_after_duplicate_still_uses_corruption_quarantine(
        self,
    ) -> None:
        raw = (
            b'{"version":1,"sessions":[{"session_id":"a","session_id":"b"}],"trailing":'
        )
        self._write_index(raw)
        before = self._index_snapshot()
        with patch.dict(os.environ, self._environment(), clear=True):
            result = owner.update_session_index({"cwd": "/synthetic"}, self.index)
        self.assertEqual("FAIL", result["result"])
        self.assertEqual("session_index_corrupt", result["reason_code"])
        self.assertEqual("malformed_json", result["corruption_kind"])
        self.assertEqual(before, self._index_snapshot())
        self.assertEqual(raw, Path(result["quarantine"]["path"]).read_bytes())

    def test_digest_and_doctor_report_failure_after_possible_digest_publication(
        self,
    ) -> None:
        self._write_index(
            b'{"version":1,"sessions":[{"session_id":"PRIVATE-ONE"}],'
            b'"sessions":[{"session_id":"PRIVATE-TWO"}]}'
        )
        before = self._index_snapshot()
        run = self._run("session_digest.py", "run", "--reason", "manual")
        self.assertEqual(1, run.returncode, run.stderr)
        self.assertEqual("", run.stderr)
        self.assertIn("session_index_reason: session_index_duplicate_key", run.stdout)
        self.assertNotIn("PRIVATE-ONE", run.stdout + run.stderr)
        self.assertNotIn("PRIVATE-TWO", run.stdout + run.stderr)
        self.assertEqual(before, self._index_snapshot())
        self.assertTrue(self.digest.is_file())
        self.assertFalse(self.quarantine.exists())
        saved = json.loads(self.digest.read_text(encoding="utf-8"))
        self.assertEqual(
            "session_index_duplicate_key", saved["session_index"]["reason_code"]
        )
        doctor = self._run("session_digest.py", "doctor", "--json")
        self.assertEqual(1, doctor.returncode, doctor.stderr)
        self.assertEqual("", doctor.stderr)
        self.assertNotIn("PRIVATE-ONE", doctor.stdout)
        self.assertNotIn("PRIVATE-TWO", doctor.stdout)
        report = json.loads(doctor.stdout)
        self.assertEqual(
            saved["session_index"]["recovery_steps"], report["quick_fixes"]
        )
        self.assertNotIn("run /digest run --reason manual", report["quick_fixes"])
        self.assertEqual(before, self._index_snapshot())


if __name__ == "__main__":
    unittest.main()
