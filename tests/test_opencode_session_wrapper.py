from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "opencode_session.sh"


@unittest.skipUnless(os.name == "posix", "the wrapper requires POSIX executables")
class OpenCodeSessionWrapperTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="opencode-wrapper-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.project = self.root / "project"
        self.bin = self.root / "bin"
        self.digest_record = self.root / "digest-args"
        for directory in (self.home, self.project, self.bin):
            directory.mkdir()

        fake_opencode = self.bin / "opencode"
        fake_opencode.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "names = ('MY_OPENCODE_GATEWAY_EVENT_AUDIT', "
            "'MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH', "
            "'MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES', "
            "'MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BACKUPS')\n"
            "print(json.dumps({'args': sys.argv[1:], "
            "'env': {name: os.environ.get(name) for name in names}}))\n"
            "sys.exit(int(os.environ['FAKE_OPENCODE_EXIT']))\n",
            encoding="utf-8",
        )
        fake_opencode.chmod(0o700)
        fake_digest = self.bin / "python3"
        fake_digest.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$@" > "$FAKE_DIGEST_RECORD"\n',
            encoding="utf-8",
        )
        fake_digest.chmod(0o700)

    def run_wrapper(
        self, overrides: dict[str, str] | None = None
    ) -> tuple[subprocess.CompletedProcess[str], dict]:
        env = {
            "HOME": str(self.home),
            "PATH": str(self.bin),
            "LC_ALL": "C",
            "PYTHONDONTWRITEBYTECODE": "1",
            "FAKE_DIGEST_RECORD": str(self.digest_record),
            "FAKE_OPENCODE_EXIT": "17",
        }
        env.update(overrides or {})
        result = subprocess.run(
            ["/bin/bash", str(WRAPPER), "--session", "synthetic id"],
            cwd=self.project,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertFalse((self.project / ".opencode").exists())
        return result, json.loads(result.stdout)

    def test_unset_and_empty_flags_default_off(self) -> None:
        for overrides in (
            {},
            {"MY_OPENCODE_GATEWAY_EVENT_AUDIT": "", "MY_OPENCODE_AUTO_DIGEST": ""},
            {"MY_OPENCODE_GATEWAY_EVENT_AUDIT": "0", "MY_OPENCODE_AUTO_DIGEST": "0"},
        ):
            with self.subTest(overrides=overrides):
                _, payload = self.run_wrapper(overrides)
                self.assertEqual(payload["args"], ["--session", "synthetic id"])
                self.assertEqual(payload["env"]["MY_OPENCODE_GATEWAY_EVENT_AUDIT"], "0")
                self.assertEqual(
                    payload["env"]["MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH"],
                    str(self.project / ".opencode" / "gateway-events.jsonl"),
                )
                self.assertEqual(
                    payload["env"]["MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES"],
                    "8388608",
                )
                self.assertEqual(
                    payload["env"]["MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BACKUPS"], "5"
                )
                self.assertFalse(self.digest_record.exists())

    def test_audit_opt_in_and_overrides_are_forwarded_without_exit_digest(self) -> None:
        audit_path = self.root / "synthetic-audit.jsonl"
        _, payload = self.run_wrapper(
            {
                "MY_OPENCODE_GATEWAY_EVENT_AUDIT": "1",
                "MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH": str(audit_path),
                "MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES": "1234",
                "MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BACKUPS": "2",
            }
        )
        self.assertEqual(
            payload["env"],
            {
                "MY_OPENCODE_GATEWAY_EVENT_AUDIT": "1",
                "MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH": str(audit_path),
                "MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES": "1234",
                "MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BACKUPS": "2",
            },
        )
        self.assertFalse(audit_path.exists())
        self.assertFalse(self.digest_record.exists())

    def test_exit_digest_requires_separate_opt_in(self) -> None:
        digest_path = self.root / "synthetic-digest.json"
        _, payload = self.run_wrapper(
            {"MY_OPENCODE_AUTO_DIGEST": "1", "MY_OPENCODE_DIGEST_PATH": str(digest_path)}
        )
        self.assertEqual(payload["env"]["MY_OPENCODE_GATEWAY_EVENT_AUDIT"], "0")
        self.assertEqual(
            self.digest_record.read_text(encoding="utf-8").splitlines(),
            [
                str(self.home / ".config/opencode/my_opencode/scripts/session_digest.py"),
                "run",
                "--reason",
                "exit",
                "--path",
                str(digest_path),
                "--run-post",
            ],
        )
        self.assertFalse(digest_path.exists())


if __name__ == "__main__":
    unittest.main()
