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
SCRIPT = ROOT / "scripts" / "session_command.py"
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import session_metadata_index as owner


class SessionShowDuplicateIdsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="session-show-duplicates-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.index = self.root / "index.json"
        self.digest = self.root / "digest.json"

    def _write_index(self, rows: list[dict]) -> None:
        self.index.write_text(
            json.dumps({"version": 1, "sessions": rows}), encoding="utf-8"
        )
        self.index.chmod(0o600)

    def _snapshot(self) -> dict:
        result = {}
        for path in self.root.iterdir():
            info = path.stat()
            result[path.name] = (
                path.read_bytes(),
                info.st_mode,
                info.st_ino,
                info.st_nlink,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
            )
        return result

    def _run(
        self,
        args: list[str],
        *,
        session_id: str = "",
        redact_default: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        env = {
            "HOME": str(self.root),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_CACHE_HOME": str(self.root / "cache"),
            "XDG_STATE_HOME": str(self.root / "state"),
            "MY_OPENCODE_SESSION_INDEX_PATH": str(self.index),
            "MY_OPENCODE_DIGEST_PATH": str(self.digest),
            "MY_OPENCODE_SESSION_REDACT_DEFAULT": "true" if redact_default else "false",
            "OPENCODE_SESSION_ID": session_id,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPT), *args],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def _show(
        self, identifier: str, *, json_output: bool
    ) -> subprocess.CompletedProcess[str]:
        argv = ["show", identifier]
        if json_output:
            argv.append("--json")
        return self._run(argv)

    def test_duplicate_exact_id_fails_without_returning_a_row_or_identifier(
        self,
    ) -> None:
        target = "PRIVATE-ID-CANARY"
        rows = [
            {
                "session_id": target,
                "cwd": "/PRIVATE-OLDER",
                "last_event_at": "2024-01-01T00:00:00Z",
            },
            {"session_id": "ses_unrelated", "cwd": "/synthetic/other"},
            {
                "session_id": target,
                "cwd": "/PRIVATE-NEWER",
                "last_event_at": "2025-01-01T00:00:00Z",
            },
        ]
        for ordered in (rows, list(reversed(rows))):
            with self.subTest(reversed=ordered is not rows):
                self._write_index(ordered)
                before = self._snapshot()
                for json_output in (True, False):
                    result = self._show(target, json_output=json_output)
                    self.assertEqual(1, result.returncode)
                    self.assertEqual("", result.stderr)
                    for canary in (target, "PRIVATE-OLDER", "PRIVATE-NEWER"):
                        self.assertNotIn(canary, result.stdout + result.stderr)
                    if json_output:
                        payload = json.loads(result.stdout)
                        self.assertEqual("FAIL", payload["result"])
                        self.assertEqual("show", payload["command"])
                        self.assertEqual(
                            "session_index_duplicate_id", payload["reason_code"]
                        )
                        self.assertNotIn("session", payload)
                    else:
                        self.assertIn("result: FAIL", result.stdout)
                        self.assertIn(
                            "reason_code: session_index_duplicate_id", result.stdout
                        )
                    self.assertEqual(before, self._snapshot())

    def test_owner_generated_fallback_id_also_fails_on_duplicate(self) -> None:
        with patch.dict(os.environ, {"OPENCODE_SESSION_ID": ""}):
            identifier = owner._session_id(
                "2025-01-01T00:00:00Z", "/synthetic/cwd::name"
            )
        self._write_index(
            [
                {"session_id": identifier, "cwd": "/PRIVATE-ONE"},
                {"session_id": identifier, "cwd": "/PRIVATE-TWO"},
            ]
        )
        before = self._snapshot()
        result = self._show(identifier, json_output=True)
        self.assertEqual(1, result.returncode)
        self.assertEqual(
            "session_index_duplicate_id", json.loads(result.stdout)["reason_code"]
        )
        self.assertNotIn(identifier, result.stdout + result.stderr)
        self.assertNotIn("PRIVATE-ONE", result.stdout + result.stderr)
        self.assertNotIn("PRIVATE-TWO", result.stdout + result.stderr)
        self.assertEqual(before, self._snapshot())

    def test_unrelated_duplicates_do_not_block_unique_or_missing_ids(self) -> None:
        self._write_index(
            [
                {"session_id": "ses_duplicate", "cwd": "/synthetic/a"},
                {"session_id": "ses_duplicate", "cwd": "/synthetic/b"},
                {"session_id": "ses_unique", "cwd": "/synthetic/lower"},
                {"session_id": "SES_unique", "cwd": "/synthetic/upper"},
            ]
        )
        before = self._snapshot()
        for identifier, cwd in (
            ("ses_unique", "/synthetic/lower"),
            ("SES_unique", "/synthetic/upper"),
        ):
            with self.subTest(identifier=identifier):
                result = self._show(identifier, json_output=True)
                self.assertEqual(0, result.returncode, result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual("PASS", payload["result"])
                self.assertEqual(cwd, payload["session"]["cwd"])
                self.assertEqual(before, self._snapshot())
        missing = self._show("ses_missing", json_output=True)
        self.assertEqual(1, missing.returncode)
        self.assertIn("session not found", json.loads(missing.stdout)["error"])
        self.assertEqual(before, self._snapshot())

    def test_current_and_handoff_reject_ambiguous_selected_id(self) -> None:
        target = "PRIVATE-ID-CANARY"
        self._write_index(
            [
                {
                    "session_id": target,
                    "cwd": str(self.root),
                    "last_event_at": "2024-01-01T00:00:00Z",
                },
                {
                    "session_id": target,
                    "cwd": "/PRIVATE-OTHER",
                    "last_event_at": "2025-01-01T00:00:00Z",
                },
                {"session_id": "ses_unique", "cwd": "/synthetic/unique"},
            ]
        )
        # A duplicate selection must fail before handoff tries to read the digest.
        self.digest.write_text("{PRIVATE-DIGEST-CANARY", encoding="utf-8")
        self.digest.chmod(0o600)
        before = self._snapshot()
        cases = (
            (["current", "--json"], target, False, "current", False),
            (["current"], target, False, "current", False),
            (["current", "--json"], "", False, "current", False),
            (
                ["handoff", "--id", target, "--json"],
                "ses_unique",
                False,
                "handoff",
                False,
            ),
            (["handoff", "--json"], target, False, "handoff", False),
            (
                ["handoff", "--id", target, "--redact", "--json"],
                "",
                False,
                "handoff",
                True,
            ),
            (["handoff", "--id", target, "--redact"], "", False, "handoff", True),
            (["handoff", "--json"], target, True, "handoff", True),
            (["handoff", "--redact", "--json"], "", False, "handoff", True),
        )
        for args, active, redact_default, command, redacted in cases:
            with self.subTest(
                args=args, active=bool(active), redact_default=redact_default
            ):
                result = self._run(
                    args, session_id=active, redact_default=redact_default
                )
                self.assertEqual(1, result.returncode)
                self.assertEqual("", result.stderr)
                for canary in (target, "PRIVATE-OTHER", "PRIVATE-DIGEST-CANARY"):
                    self.assertNotIn(canary, result.stdout + result.stderr)
                if "--json" in args:
                    payload = json.loads(result.stdout)
                    if redacted:
                        self.assertEqual(
                            {
                                "result": "FAIL",
                                "command": "handoff",
                                "redacted": True,
                                "error_code": "session_index_unavailable",
                            },
                            payload,
                        )
                    else:
                        self.assertEqual("FAIL", payload["result"])
                        self.assertEqual(command, payload["command"])
                        self.assertEqual(
                            "session_index_duplicate_id", payload["reason_code"]
                        )
                        self.assertNotIn("session", payload)
                        self.assertNotIn("resume_command", payload)
                elif redacted:
                    self.assertEqual(
                        "error_code: session_index_unavailable", result.stdout.strip()
                    )
                else:
                    self.assertIn(
                        "reason_code: session_index_duplicate_id", result.stdout
                    )
                self.assertEqual(before, self._snapshot())

    def test_other_duplicates_do_not_block_unique_or_env_only_selection(self) -> None:
        self._write_index(
            [
                {"session_id": "ses_duplicate", "cwd": "/synthetic/a"},
                {"session_id": "ses_duplicate", "cwd": "/synthetic/b"},
                {
                    "session_id": "ses_unique",
                    "cwd": str(self.root),
                    "last_event_at": "2025-01-01T00:00:00Z",
                },
            ]
        )
        self.digest.write_text(
            json.dumps({"git": {"branch": "synthetic"}}), encoding="utf-8"
        )
        self.digest.chmod(0o600)
        before = self._snapshot()
        current = self._run(["current", "--json"], session_id="ses_unique")
        self.assertEqual(0, current.returncode, current.stderr)
        self.assertEqual(
            "ses_unique", json.loads(current.stdout)["session"]["session_id"]
        )
        # A duplicate environment selection must not block a distinct explicit target.
        handoff = self._run(
            ["handoff", "--id", "ses_unique", "--json"], session_id="ses_duplicate"
        )
        self.assertEqual(0, handoff.returncode, handoff.stderr)
        self.assertEqual("ses_unique", json.loads(handoff.stdout)["session_id"])
        redacted = self._run(["handoff", "--id", "ses_unique", "--redact", "--json"])
        self.assertEqual(0, redacted.returncode, redacted.stderr)
        self.assertTrue(json.loads(redacted.stdout)["redacted"])
        env_only = self._run(["current", "--json"], session_id="ses_unindexed")
        self.assertEqual(0, env_only.returncode, env_only.stderr)
        self.assertEqual("env_only", json.loads(env_only.stdout)["source"])
        missing = self._run(["handoff", "--id", "ses_missing", "--redact", "--json"])
        self.assertEqual(1, missing.returncode)
        self.assertEqual("session_not_found", json.loads(missing.stdout)["error_code"])
        unindexed = self._run(
            ["handoff", "--redact", "--json"], session_id="ses_unindexed"
        )
        self.assertEqual(1, unindexed.returncode)
        self.assertEqual(
            "session_not_indexed", json.loads(unindexed.stdout)["error_code"]
        )
        self.assertEqual(before, self._snapshot())


if __name__ == "__main__":
    unittest.main()
