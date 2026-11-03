from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import opencode_version_probe


class OpenCodeVersionProbeTest(unittest.TestCase):
    def test_child_environment_is_isolated_and_scrubbed(self) -> None:
        completed = subprocess.CompletedProcess([], 0, b"opencode v2.2.5\n", b"")
        with tempfile.TemporaryDirectory() as raw:
            user_home = Path(raw) / "user-home"
            user_home.mkdir()
            user_db = user_home / "runtime.sqlite"
            with (
                patch.dict(
                    os.environ,
                    {
                        "HOME": str(user_home),
                        "OPENCODE_DB": str(user_db),
                        "OPENCODE_PASSWORD": "synthetic-secret",
                        "XDG_CONFIG_HOME": str(user_home / "custom-config"),
                    },
                    clear=False,
                ),
                patch.object(
                    opencode_version_probe, "run_bounded", return_value=completed
                ) as run,
            ):
                version = opencode_version_probe.probe_opencode_version(
                    "opencode-fixture"
                )
            self.assertEqual(version, "opencode v2.2.5")
            args, kwargs = run.call_args
            child_env = kwargs["env"]
            self.assertEqual(args[0][-1], "--version")
            self.assertNotEqual(child_env["HOME"], str(user_home))
            self.assertEqual(kwargs["cwd"], child_env["HOME"])
            self.assertEqual(child_env["CI"], "true")
            self.assertEqual(child_env["GIT_TERMINAL_PROMPT"], "0")
            self.assertEqual(child_env["GCM_INTERACTIVE"], "never")
            self.assertEqual(child_env["USERPROFILE"], child_env["HOME"])
            self.assertTrue(child_env["XDG_CONFIG_HOME"].startswith(child_env["HOME"]))
            self.assertNotIn("OPENCODE_DB", child_env)
            self.assertNotIn("OPENCODE_PASSWORD", child_env)
            self.assertEqual(kwargs["max_output_bytes"], 512)
            self.assertFalse(Path(child_env["HOME"]).exists())
            self.assertFalse(user_db.exists())

    @unittest.skipUnless(os.name == "posix", "fixture executable requires POSIX")
    def test_gateway_status_and_fingerprint_do_not_touch_user_home(self) -> None:
        module = importlib.import_module("gateway_command")
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = root / "home"
            binary_dir = root / "bin"
            home.mkdir()
            binary_dir.mkdir()
            database = home / "runtime.sqlite"
            database.write_text("user runtime\n", encoding="utf-8")
            binary = binary_dir / "opencode"
            binary.write_text(
                "#!/bin/sh\n"
                'printf touched > "$HOME/version-probe-marker"\n'
                'printf touched > "$PWD/version-probe-cwd"\n'
                'if [ -n "${OPENCODE_DB:-}" ]; then printf changed > "$OPENCODE_DB"; fi\n'
                'printf "opencode v2.2.5\\n"\n',
                encoding="utf-8",
            )
            binary.chmod(0o700)
            before = {path.name: path.read_bytes() for path in home.iterdir()}
            with (
                patch.dict(
                    os.environ,
                    {
                        "HOME": str(home),
                        "OPENCODE_DB": str(database),
                        "PATH": str(binary_dir)
                        + os.pathsep
                        + os.environ.get("PATH", ""),
                    },
                    clear=False,
                ),
                patch.object(
                    module, "_gateway_smoke_fingerprint_files", return_value=[]
                ),
            ):
                self.assertEqual(2, module.opencode_major_version())
                self.assertEqual(64, len(module._gateway_smoke_fingerprint()))
            self.assertEqual(
                before, {path.name: path.read_bytes() for path in home.iterdir()}
            )

    @unittest.skipUnless(os.name == "posix", "fixture executable requires POSIX")
    def test_failed_invalid_and_oversized_output_are_rejected(self) -> None:
        cases = (
            'printf "2.2.5\\n"; exit 1',
            "printf '\\377'",
            "printf '" + ("x" * 513) + "'",
        )
        with tempfile.TemporaryDirectory() as raw:
            binary = Path(raw) / "opencode"
            for script in cases:
                with self.subTest(script=script):
                    binary.write_text("#!/bin/sh\n" + script + "\n", encoding="utf-8")
                    binary.chmod(0o700)
                    with self.assertRaises(
                        opencode_version_probe.OpenCodeVersionProbeError
                    ):
                        opencode_version_probe.probe_opencode_version(str(binary))

    @unittest.skipUnless(os.name == "posix", "fixture executable requires POSIX")
    def test_hung_descendant_is_bounded_after_leader_exits(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            binary = root / "opencode"
            binary.write_text("#!/bin/sh\n/bin/sleep 30 & exit 0\n", encoding="utf-8")
            binary.chmod(0o700)
            started = time.monotonic()
            with (
                patch.dict(
                    os.environ, {"MY_OPENCODE_VERSION_PROBE_TIMEOUT_SECONDS": "0.5"}
                ),
                self.assertRaises(opencode_version_probe.OpenCodeVersionProbeError),
            ):
                opencode_version_probe.probe_opencode_version(str(binary))
            self.assertLess(time.monotonic() - started, 4.0)


if __name__ == "__main__":
    unittest.main()
