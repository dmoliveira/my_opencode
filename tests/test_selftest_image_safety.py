from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SelftestImageSafetyTest(unittest.TestCase):
    def test_image_subprocesses_use_the_fixture_environment(self) -> None:
        tree = ast.parse((ROOT / "scripts" / "selftest.py").read_text(encoding="utf-8"))
        image_calls = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr != "run":
                continue
            if not isinstance(node.func.value, ast.Name) or node.func.value.id != "subprocess":
                continue
            if not any(
                isinstance(item, ast.Name) and item.id == "IMAGE_COMMAND_SCRIPT"
                for item in ast.walk(node.args[0])
            ):
                continue
            image_calls.append(node)
            environment = next((item.value for item in node.keywords if item.arg == "env"), None)
            self.assertIsInstance(environment, ast.Name, node.lineno)
            self.assertIn(environment.id, {"image_env", "codex_env"}, node.lineno)
        self.assertGreater(len(image_calls), 0)

    def test_hostile_credentials_and_codex_paths_stay_outside_image_fixture(self) -> None:
        with tempfile.TemporaryDirectory(prefix="selftest-image-safety-") as raw:
            root = Path(raw)
            external = root / "external"
            fixture = root / "fixture"
            host_home = external / "home"
            host_codex = external / "codex"
            host_bin = external / "bin"
            fixture_home = fixture / "home"
            for path in (external, fixture, host_home, host_codex, host_bin, fixture_home):
                path.mkdir(mode=0o700)
            sentinel = host_codex / "sentinel.json"
            sentinel.write_text('{"synthetic":"preserve"}\n', encoding="utf-8")
            preference = external / "provider.txt"
            location = external / "location.txt"
            preference.write_text("synthetic provider sentinel\n", encoding="utf-8")
            location.write_text("synthetic location sentinel\n", encoding="utf-8")
            for name in ("codex", "git"):
                spy = host_bin / name
                spy.write_text(
                    '#!/bin/sh\nprintf "unexpected invocation\\n" >> "$CODEX_HOME/invocations"\nexit 1\n',
                    encoding="utf-8",
                )
                spy.chmod(0o700)
            before = {
                path: (path.read_bytes(), path.stat().st_ino, path.stat().st_mode, path.stat().st_mtime_ns)
                for path in (sentinel, preference, location)
            }
            before_names = sorted(str(path.relative_to(external)) for path in external.rglob("*"))
            environment = {
                "HOME": str(host_home),
                "TMPDIR": str(root),
                "PATH": os.pathsep.join((str(host_bin), os.defpath)),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": os.pathsep.join((str(ROOT / "scripts"), str(external / "python"))),
                "OPENAI_API_KEY": "synthetic-openai-secret",
                "ANTHROPIC_API_KEY": "synthetic-other-secret",
                "AWS_SECRET_ACCESS_KEY": "synthetic-aws-secret",
                "CODEX_HOME": str(host_codex),
                "CODEX_UNEXPECTED": "synthetic-codex-control",
                "OPENAI_IMAGE_MODEL": "",
                "OPENAI_IMAGE_PROVIDER_CONFIG_PATH": str(preference),
                "OPENAI_IMAGE_PROVIDER_PREFERENCE": "invalid",
                "OPENAI_IMAGE_OUTPUT_LOCATION_CONFIG_PATH": str(location),
                "OPENAI_IMAGE_OUTPUT_LOCATION_PREFERENCE": "invalid",
            }
            program = (
                "import json, shutil, subprocess, sys\n"
                "from pathlib import Path\n"
                "import selftest\n"
                "root, home = map(Path, sys.argv[1:])\n"
                "env = selftest._selftest_image_environment(root, home)\n"
                "doctor = subprocess.run([sys.executable, str(selftest.IMAGE_COMMAND_SCRIPT), 'doctor', '--json'], "
                "cwd=root, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, check=False)\n"
                "access = subprocess.run([sys.executable, str(selftest.IMAGE_COMMAND_SCRIPT), 'access', '--json'], "
                "cwd=root, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, check=False)\n"
                "print(json.dumps({'keys': sorted(env), 'codex_home': env['CODEX_HOME'], "
                "'codex_binary': shutil.which('codex', path=env['PATH']), 'doctor_rc': doctor.returncode, "
                "'doctor': json.loads(doctor.stdout), 'access_rc': access.returncode, "
                "'access': json.loads(access.stdout)}))\n"
            )
            result = subprocess.run(
                [sys.executable, "-c", program, str(fixture), str(fixture_home)],
                cwd=root,
                env=environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            for name in (
                "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY",
                "CODEX_UNEXPECTED", "OPENAI_IMAGE_MODEL", "PYTHONPATH",
            ):
                self.assertNotIn(name, report["keys"])
            self.assertTrue(Path(report["codex_home"]).is_relative_to(fixture))
            self.assertTrue(Path(report["codex_binary"]).is_relative_to(fixture))
            self.assertEqual(report["doctor_rc"], 1)
            self.assertFalse(report["doctor"]["api_key_configured"])
            self.assertIn("OPENAI_API_KEY is not set", report["doctor"]["problems"])
            self.assertEqual(report["doctor"]["default_model"], "gpt-image-1")
            self.assertEqual(report["access_rc"], 0)
            self.assertEqual(report["access"]["effective_provider"], "openai_api")
            self.assertFalse((host_codex / "invocations").exists())
            self.assertEqual(before_names, sorted(str(path.relative_to(external)) for path in external.rglob("*")))
            for path, prior in before.items():
                self.assertEqual(prior, (path.read_bytes(), path.stat().st_ino, path.stat().st_mode, path.stat().st_mtime_ns))


if __name__ == "__main__":
    unittest.main()
