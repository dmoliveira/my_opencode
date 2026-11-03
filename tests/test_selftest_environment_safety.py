from __future__ import annotations

import ast
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XDG_VARS = (
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
    "XDG_CONFIG_DIRS",
    "XDG_DATA_DIRS",
    "XDG_RUNTIME_DIR",
)
UNTRUSTED_VARS = (
    "MY_OPENCODE_POLICY_PATH",
    "OPENCODE_NOTIFICATIONS_PATH",
    "OPENCODE_TELEMETRY_PATH",
    "MY_OPENCODE_AUTOPILOT_RUNTIME_PATH",
    "OPENCODE_CONFIG_PATH",
    "OPENCODE_DB",
    "MY_OPENCODE_UNEXPECTED_PATH",
    "OPENCODE_UNEXPECTED_PATH",
    "XDG_UNEXPECTED_PATH",
)


class SelftestEnvironmentSafetyTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="selftest-env-safety-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.tmp = self.root / "tmp"
        self.external = self.root / "external"
        self.home = self.external / "home"
        for path in (self.tmp, self.external, self.home):
            path.mkdir(mode=0o700)
        self.paths = {name: self.external / f"{name}.json" for name in UNTRUSTED_VARS}
        for path in self.paths.values():
            path.write_text('{"synthetic_marker":"preserve"}\n', encoding="utf-8")
            path.chmod(0o600)
        self.before = self.snapshot()
        self.env = {
            "HOME": str(self.home),
            "TMPDIR": str(self.tmp),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(ROOT / "scripts"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            **{name: str(path) for name, path in self.paths.items()},
            **{name: str(self.external / f"inherited-{name}") for name in XDG_VARS},
        }

    def snapshot(self) -> dict[str, tuple[bytes, int, int, int]]:
        return {
            name: (path.read_bytes(), path.stat().st_ino, path.stat().st_mode, path.stat().st_mtime_ns)
            for name, path in self.paths.items()
        }

    def run_python(self, program: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", program, *args],
            cwd=self.root,
            env=self.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def test_background_fixtures_never_launch_selftest_recursively(self) -> None:
        tree = ast.parse((ROOT / "scripts" / "selftest.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.List, ast.Tuple)):
                continue
            for flag, command in zip(node.elts, node.elts[1:]):
                if not isinstance(flag, ast.Constant) or flag.value != "--bg-command":
                    continue
                self.assertIsInstance(command, ast.Constant)
                self.assertIsInstance(command.value, str)
                tokens = shlex.split(command.value)
                self.assertFalse(any(Path(token).name == "selftest.py" for token in tokens))
                self.assertFalse(tokens and Path(tokens[0]).name == "make" and "selftest" in tokens)

    def test_background_wait_requires_terminal_metadata(self) -> None:
        program = (
            "import json, sys, threading, time\n"
            "from pathlib import Path\n"
            "import selftest\n"
            "bg = Path(sys.argv[1]); (bg / 'runs').mkdir(parents=True)\n"
            "(bg / 'jobs.json').write_text(json.dumps({'jobs': [{'id': 'fixture', 'status': 'completed'}]}))\n"
            "meta = bg / 'runs' / 'fixture.meta.json'\n"
            "def publish():\n"
            " time.sleep(0.2)\n"
            " meta.write_text(json.dumps({'id': 'fixture', 'status': 'completed'}))\n"
            "thread = threading.Thread(target=publish); thread.start()\n"
            "selftest._wait_for_fixture_background_job(bg, 'fixture')\n"
            "assert meta.exists()\n"
            "thread.join()\n"
        )
        result = self.run_python(program, str(self.root / "bg"))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_main_rebinds_environment_before_child_fixtures(self) -> None:
        names = (*UNTRUSTED_VARS, *XDG_VARS, "HOME", "TMPDIR", "MY_OPENCODE_CLAIMS_PATH")
        program = (
            "import json, os, tempfile\n"
            "from pathlib import Path\n"
            "import selftest\n"
            "class StopBeforeChildren(Exception): pass\n"
            "original = Path.mkdir\n"
            "def mkdir(path, *args, **kwargs):\n"
            " if path.name == 'bin' and path.parent.name == 'home':\n"
            f"  values = {{name: os.environ.get(name) for name in {names!r}}}\n"
            "  print(json.dumps({'values': values, 'tempfile_dir': tempfile.gettempdir(), "
            "'xdg_runtime_exists': Path(values['XDG_RUNTIME_DIR']).is_dir()}))\n"
            "  raise StopBeforeChildren()\n"
            " return original(path, *args, **kwargs)\n"
            "Path.mkdir = mkdir\n"
            "try: selftest.main()\n"
            "except StopBeforeChildren: pass\n"
        )
        result = self.run_python(program)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        values = report["values"]
        for name in UNTRUSTED_VARS:
            self.assertIsNone(values[name], name)
        for name in (*XDG_VARS, "HOME", "TMPDIR", "MY_OPENCODE_CLAIMS_PATH"):
            self.assertIsInstance(values[name], str, name)
            self.assertTrue(Path(values[name]).is_relative_to(self.tmp), (name, values[name]))
        self.assertEqual(report["tempfile_dir"], values["TMPDIR"])
        self.assertTrue(report["xdg_runtime_exists"])
        self.assertEqual(self.before, self.snapshot())

    def test_policy_telemetry_and_autopilot_keep_external_state_unchanged(self) -> None:
        owned = self.root / "owned"
        home = owned / "home"
        locks = owned / "config-locks"
        for path in (owned, home, locks):
            path.mkdir(mode=0o700)
        config = owned / "config.json"
        config.write_text("{}\n", encoding="utf-8")
        program = (
            "import json, os, subprocess, sys\n"
            "from pathlib import Path\n"
            "import selftest\n"
            "root, home, config, locks = map(Path, sys.argv[1:])\n"
            "env = selftest._isolated_application_environment(dict(os.environ), root, home)\n"
            "env['OPENCODE_CONFIG_PATH'] = str(config)\n"
            "runner = (\"import sys; from pathlib import Path; import config_layering; \"\n"
            "          \"config_layering._lock_registry=lambda: Path(sys.argv[1]); \"\n"
            "          \"module=__import__(sys.argv[2]); raise SystemExit(module.main(sys.argv[3:]))\")\n"
            "policy = subprocess.run([sys.executable, '-c', runner, str(locks), 'policy_command', "
            "'profile', 'strict'], env=env, cwd=root, capture_output=True, text=True, timeout=30, check=False)\n"
            "telemetry = subprocess.run([sys.executable, '-c', runner, str(locks), 'telemetry_command', "
            "'profile', 'local'], env=env, cwd=root, capture_output=True, text=True, timeout=30, check=False)\n"
            "os.environ.clear(); os.environ.update(env)\n"
            "result = selftest.initialize_run(config={'budget_runtime': {'profile':'balanced'}}, "
            "write_path=config, objective={'goal':'synthetic','scope':'synthetic', "
            "'done-criteria':['check'],'max-budget':'balanced'}, actor='selftest', directory=root)\n"
            "print(json.dumps({'policy': policy.returncode, 'policy_err': policy.stderr, "
            "'telemetry': telemetry.returncode, 'telemetry_err': telemetry.stderr, "
            "'autopilot': result.get('result'), 'runtime': result.get('runtime_path')}))\n"
        )
        result = self.run_python(program, str(owned), str(home), str(config), str(locks))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["policy"], 0, report["policy_err"])
        self.assertEqual(report["telemetry"], 0, report["telemetry_err"])
        self.assertEqual(report["autopilot"], "PASS")
        self.assertTrue(Path(report["runtime"]).is_relative_to(owned))
        config_data = json.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(config_data["policy"]["current"], "strict")
        self.assertFalse(config_data["notify"]["events"]["complete"])
        self.assertTrue(config_data["telemetry"]["enabled"])
        self.assertEqual(self.before, self.snapshot())


if __name__ == "__main__":
    unittest.main()
