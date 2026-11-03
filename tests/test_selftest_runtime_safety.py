from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_VARS = (
    "MY_OPENCODE_CLAIMS_PATH",
    "MY_OPENCODE_AGENT_POOL_PATH",
    "MY_OPENCODE_AUDIT_PATH",
    "MY_OPENCODE_WORKFLOW_STATE_PATH",
    "MY_OPENCODE_DAEMON_STATE_PATH",
    "MY_OPENCODE_DELIVERY_STATE_PATH",
    "MY_OPENCODE_TASK_GRAPH_PATH",
)
BG_VAR = "MY_OPENCODE_BG_DIR"
GRAPH_LOCK_VAR = "MY_OPENCODE_TASK_GRAPH_LOCK_PATH"


class SelftestRuntimeSafetyTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="selftest-runtime-safety-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.tmp = self.root / "tmp"
        self.external = self.root / "synthetic-external"
        for path in (self.home, self.tmp, self.external):
            path.mkdir(mode=0o700)
        self.paths = {
            STATE_VARS[0]: self.external / "claims.json",
            STATE_VARS[1]: self.external / "pool.json",
            STATE_VARS[2]: self.external / "audit.json",
            STATE_VARS[3]: self.external / "workflow.json",
            STATE_VARS[4]: self.external / "daemon.json",
            STATE_VARS[5]: self.external / "delivery.json",
            STATE_VARS[6]: self.external / "graph.json",
        }
        values = (
            {"version": 1, "claims": {"synthetic-existing": {"status": "active"}}},
            {"agents": [{"agent_id": "orchestrator", "load": 3}], "events": []},
            {"version": 1, "events": [{"id": "synthetic-existing"}]},
            {"active": None, "history": [], "synthetic_marker": "preserve"},
            {"status": "stopped", "synthetic_marker": "preserve"},
            {"version": 1, "runs": [{"run_id": "synthetic-existing"}]},
            {"format_version": 1, "updated_at": "2000-01-01T00:00:00Z", "tasks": []},
        )
        for path, value in zip(self.paths.values(), values, strict=True):
            path.write_text(json.dumps(value) + "\n", encoding="utf-8")
            path.chmod(0o600)
        self.paths[GRAPH_LOCK_VAR] = self.external / "graph.lock"
        self.paths[GRAPH_LOCK_VAR].write_text("synthetic external lock sentinel\n", encoding="utf-8")
        external_bg = self.external / "bg"
        external_bg.mkdir(mode=0o700)
        self.add_terminal_sentinels(external_bg, self.paths, "external")
        self.before = self.external_state()
        self.checkout_paths: dict[str, Path] = {}
        if os.name == "posix":
            checkout = self.root / "synthetic-checkout"
            checkout_runtime = checkout / "runtime"
            checkout_runtime.mkdir(parents=True, mode=0o700)
            link = self.home / ".config" / "opencode" / "my_opencode"
            link.parent.mkdir(parents=True, mode=0o700)
            link.symlink_to(checkout, target_is_directory=True)
            checkout_names = (
                "claims.json", "agent_pool.json", "audit_log.json", "workflow_state.json",
                "daemon_state.json", "delivery_runs.json", "task_graph.json",
            )
            for name, filename, value in zip(STATE_VARS, checkout_names, values, strict=True):
                path = checkout_runtime / filename
                path.write_text(json.dumps(value) + "\n", encoding="utf-8")
                path.chmod(0o600)
                self.checkout_paths[name] = path
            self.checkout_paths[GRAPH_LOCK_VAR] = checkout_runtime / "task_graph.lock"
            self.checkout_paths[GRAPH_LOCK_VAR].write_text("synthetic checkout lock sentinel\n", encoding="utf-8")
            checkout_bg = checkout / "bg"
            checkout_bg.mkdir(mode=0o700)
            self.add_terminal_sentinels(checkout_bg, self.checkout_paths, "checkout")
        self.checkout_before = self.path_state(self.checkout_paths)
        self.env = {
            "HOME": str(self.home),
            "TMPDIR": str(self.tmp),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(ROOT / "scripts"),
            **{name: str(self.paths[name]) for name in STATE_VARS},
            GRAPH_LOCK_VAR: str(self.paths[GRAPH_LOCK_VAR]),
            BG_VAR: str(external_bg),
        }

    @staticmethod
    def add_terminal_sentinels(directory: Path, paths: dict[str, Path], label: str) -> None:
        log = directory / "synthetic.log"
        log.write_text(f"{label} terminal log must survive\n", encoding="utf-8")
        jobs = directory / "jobs.json"
        jobs.write_text(json.dumps({
            "version": 1,
            "jobs": [{
                "id": f"synthetic-{label}", "status": "completed",
                "created_at": "2000-01-01T00:00:00Z", "log_path": str(log),
            }],
        }) + "\n", encoding="utf-8")
        paths[f"{label}_jobs"] = jobs
        paths[f"{label}_log"] = log

    @staticmethod
    def path_state(paths: dict[str, Path]) -> dict[str, tuple[bytes, int, int, int]]:
        return {
            name: (path.read_bytes(), path.stat().st_ino, path.stat().st_mode, path.stat().st_mtime_ns)
            for name, path in paths.items()
        }

    def external_state(self) -> dict[str, tuple[bytes, int, int, int]]:
        return self.path_state(self.paths)

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

    def test_runtime_commands_use_owned_not_inherited_paths(self) -> None:
        owned = self.root / "owned-selftest"
        owned.mkdir(mode=0o700)
        plan = owned / "synthetic-workflow.json"
        plan.write_text(json.dumps({"name": "synthetic", "steps": [{"id": "prep", "action": "gather-context"}]}) + "\n", encoding="utf-8")
        program = (
            "import json, os, subprocess, sys\n"
            "from pathlib import Path\n"
            "import selftest\n"
            "bindings = selftest._selftest_runtime_paths(Path(sys.argv[1]))\n"
            "env = dict(os.environ); env.update(bindings)\n"
            "result = subprocess.run([sys.executable, str(selftest.CLAIMS_SCRIPT), "
            "'claim', 'issue-101', '--by', 'agent:orchestrator', '--json'], "
            "env=env, capture_output=True, text=True, timeout=30, check=False)\n"
            "workflow = subprocess.run([sys.executable, str(selftest.WORKFLOW_SCRIPT), "
            "'run', '--file', sys.argv[2], '--execute', '--json'], "
            "env=env, capture_output=True, text=True, timeout=30, check=False)\n"
            "daemon = subprocess.run([sys.executable, str(selftest.DAEMON_SCRIPT), 'start', '--json'], "
            "env=env, capture_output=True, text=True, timeout=30, check=False)\n"
            "delivery = subprocess.run([sys.executable, str(selftest.DELIVERY_SCRIPT), 'start', "
            "'--issue', 'issue-102', '--by', 'agent:orchestrator', '--workflow', sys.argv[2], '--json'], "
            "env=env, capture_output=True, text=True, timeout=30, check=False)\n"
            "bg = Path(bindings['MY_OPENCODE_BG_DIR']); bg.mkdir(parents=True)\n"
            "log = bg / 'owned-terminal.log'; log.write_text('owned synthetic terminal log')\n"
            "(bg / 'jobs.json').write_text(json.dumps({'version': 1, 'jobs': ["
            "{'id': 'owned-terminal', 'status': 'completed', 'created_at': '2000-01-01T00:00:00Z', "
            "'log_path': str(log)}]}))\n"
            "cleanup = subprocess.run([sys.executable, str(selftest.BG_MANAGER_SCRIPT), 'cleanup', "
            "'--max-terminal', '0', '--json'], env=env, capture_output=True, text=True, timeout=30, check=False)\n"
            "print(json.dumps({'bindings': bindings, 'exit': result.returncode, 'stderr': result.stderr, "
            "'workflow_exit': workflow.returncode, 'workflow_stderr': workflow.stderr, "
            "'daemon_exit': daemon.returncode, 'daemon_stderr': daemon.stderr, "
            "'delivery_exit': delivery.returncode, 'delivery_stderr': delivery.stderr, "
            "'cleanup_exit': cleanup.returncode, 'cleanup_stdout': cleanup.stdout, "
            "'cleanup_stderr': cleanup.stderr, 'owned_log_exists': log.exists()}))\n"
        )
        result = self.run_python(program, str(owned), str(plan))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["exit"], 0, report["stderr"])
        self.assertEqual(report["workflow_exit"], 0, report["workflow_stderr"])
        self.assertEqual(report["daemon_exit"], 0, report["daemon_stderr"])
        self.assertEqual(report["delivery_exit"], 0, report["delivery_stderr"])
        self.assertEqual(report["cleanup_exit"], 0, report["cleanup_stderr"])
        self.assertEqual(json.loads(report["cleanup_stdout"])["pruned"], 1)
        self.assertFalse(report["owned_log_exists"])
        self.assertEqual(set(report["bindings"]), {*STATE_VARS, BG_VAR, GRAPH_LOCK_VAR})
        for name in (*STATE_VARS, GRAPH_LOCK_VAR):
            path = Path(report["bindings"][name])
            self.assertTrue(path.is_relative_to(owned), path)
            self.assertTrue(path.is_file(), path)
            self.assertNotEqual(path, self.paths[name])
        bg = Path(report["bindings"][BG_VAR])
        self.assertTrue(bg.is_relative_to(owned), bg)
        self.assertNotEqual(bg, self.external / "bg")
        self.assertEqual(self.before, self.external_state())
        self.assertEqual(self.checkout_before, self.path_state(self.checkout_paths))

    def test_main_binds_paths_before_first_child_fixture(self) -> None:
        program = (
            "import json, os\n"
            "from pathlib import Path\n"
            "import selftest\n"
            "class StopBeforeChildren(Exception): pass\n"
            "original = Path.mkdir\n"
            "def mkdir(path, *args, **kwargs):\n"
            " if path.name == 'bin' and path.parent.name == 'home':\n"
            "  print(json.dumps({name: os.environ.get(name) for name in "
            "('MY_OPENCODE_CLAIMS_PATH', 'MY_OPENCODE_AGENT_POOL_PATH', 'MY_OPENCODE_AUDIT_PATH', "
            "'MY_OPENCODE_WORKFLOW_STATE_PATH', 'MY_OPENCODE_DAEMON_STATE_PATH', "
            "'MY_OPENCODE_DELIVERY_STATE_PATH', 'MY_OPENCODE_TASK_GRAPH_PATH', "
            "'MY_OPENCODE_TASK_GRAPH_LOCK_PATH', 'MY_OPENCODE_BG_DIR')}))\n"
            "  raise StopBeforeChildren()\n"
            " return original(path, *args, **kwargs)\n"
            "Path.mkdir = mkdir\n"
            "try: selftest.main()\n"
            "except StopBeforeChildren: pass\n"
        )
        result = self.run_python(program)
        self.assertEqual(result.returncode, 0, result.stderr)
        bindings = json.loads(result.stdout)
        for name in (*STATE_VARS, GRAPH_LOCK_VAR, BG_VAR):
            self.assertIsInstance(bindings[name], str)
            path = Path(bindings[name])
            self.assertTrue(path.is_relative_to(self.tmp), path)
            self.assertNotEqual(path, self.external / "bg" if name == BG_VAR else self.paths[name])
        self.assertEqual(self.before, self.external_state())
        self.assertEqual(self.checkout_before, self.path_state(self.checkout_paths))


if __name__ == "__main__":
    unittest.main()
