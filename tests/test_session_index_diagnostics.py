from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
DIGEST_SCRIPT = SCRIPTS_DIR / "session_digest.py"


class SessionIndexDiagnosticsTest(unittest.TestCase):
    def _session_module(self):
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        return importlib.reload(importlib.import_module("session_command"))

    def test_plain_session_readers_fail_before_command_specific_rendering(self) -> None:
        module = self._session_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "index.json"
            quarantine = root / "quarantine"
            index_path.write_bytes(b"{malformed-reader-canary")
            commands = [
                ("current", module._command_current, []),
                ("list", module._command_list, []),
                ("show", module._command_show, ["session-id"]),
                ("search", module._command_search, ["query"]),
                (
                    "doctor",
                    module._command_doctor,
                    ["--db-path", str(root / "missing.db")],
                ),
                ("handoff", module._command_handoff, []),
            ]
            with patch.dict(
                os.environ,
                {"MY_OPENCODE_SESSION_INDEX_QUARANTINE_DIR": str(quarantine)},
            ):
                for command, handler, arguments in commands:
                    with self.subTest(command=command), contextlib.redirect_stdout(
                        io.StringIO()
                    ) as output:
                        code = handler(arguments, index_path)
                    self.assertEqual(1, code)
                    self.assertIn("result: FAIL", output.getvalue())
                    self.assertIn(
                        "reason_code: session_index_corrupt",
                        output.getvalue(),
                    )
            self.assertFalse(quarantine.exists(), "reader commands must not quarantine")
            self.assertEqual(b"{malformed-reader-canary", index_path.read_bytes())

    def test_session_reader_json_uses_stable_unsupported_version_reason(self) -> None:
        module = self._session_module()
        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "index.json"
            index_path.write_text(
                json.dumps({"version": 2, "sessions": "future-schema"}),
                encoding="utf-8",
            )
            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = module._command_list(["--json"], index_path)
            self.assertEqual(1, code)
            payload = json.loads(output.getvalue())
            self.assertEqual("session_index_unsupported_version", payload["reason_code"])
            self.assertNotIn("quarantine", payload)

    def test_digest_run_show_and_doctor_surface_quarantine_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "sessions" / "index.json"
            digest_path = root / "digests" / "last-session.json"
            quarantine = root / "state" / "quarantine"
            index_path.parent.mkdir(parents=True)
            original = b"{digest-malformed-canary"
            index_path.write_bytes(original)
            env = {
                **os.environ,
                "CI": "true",
                "HOME": str(root),
                "MY_OPENCODE_SESSION_INDEX_PATH": str(index_path),
                "MY_OPENCODE_SESSION_INDEX_QUARANTINE_DIR": str(quarantine),
                "MY_OPENCODE_DIGEST_PATH": str(digest_path),
                "OPENCODE_SESSION_ID": "diagnostic-test-session",
            }

            run = subprocess.run(
                [
                    sys.executable,
                    str(DIGEST_SCRIPT),
                    "run",
                    "--reason",
                    "manual",
                    "--path",
                    str(digest_path),
                ],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(1, run.returncode, run.stderr)
            self.assertIn("session_index_result: FAIL", run.stdout)
            self.assertIn(
                "session_index_reason: session_index_corrupt",
                run.stdout,
            )
            self.assertEqual(original, index_path.read_bytes())
            digest = json.loads(digest_path.read_text(encoding="utf-8"))
            self.assertEqual("FAIL", digest["session_index"]["result"])
            self.assertEqual(
                "session_index_corrupt",
                digest["session_index"]["reason_code"],
            )

            show = subprocess.run(
                [sys.executable, str(DIGEST_SCRIPT), "show", "--path", str(digest_path)],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, show.returncode, show.stderr)
            self.assertIn("session_index_reason: session_index_corrupt", show.stdout)

            doctor = subprocess.run(
                [
                    sys.executable,
                    str(DIGEST_SCRIPT),
                    "doctor",
                    "--path",
                    str(digest_path),
                    "--json",
                ],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(1, doctor.returncode, doctor.stderr)
            doctor_payload = json.loads(doctor.stdout)
            self.assertEqual("FAIL", doctor_payload["result"])
            self.assertEqual(
                "session_index_corrupt",
                doctor_payload["session_index"]["reason_code"],
            )


if __name__ == "__main__":
    unittest.main()
