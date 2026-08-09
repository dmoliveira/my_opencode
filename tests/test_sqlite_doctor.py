from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import doctor_command  # type: ignore
import shared_memory_runtime  # type: ignore
import sqlite_doctor_command  # type: ignore


class SqliteDoctorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = importlib.reload(sqlite_doctor_command)

    def _session_report(self) -> dict:
        return {
            "result": "PASS",
            "index_path": "/tmp/sessions/index.json",
            "runtime_db_path": "/tmp/opencode.db",
            "runtime_db_scan_mode": "indexed_snapshot",
            "runtime_db_missing_tables": [],
            "runtime_permission_status": "private",
            "runtime_permission_findings": [],
            "stuck_findings": [],
            "generic_stale_count": 0,
            "generic_stale_problem_threshold": 25,
            "sidecar_findings": [
                {"target": "index", "state": "private"},
                {"target": "digest", "state": "private"},
            ],
            "warnings": [],
            "problems": [],
            "quick_fixes": [],
        }

    def test_build_report_has_stable_four_store_contract_and_precedence(self) -> None:
        runtime = {
            "result": "PASS",
            "path": "/tmp/opencode.db",
            "warnings": [],
            "problems": [],
            "quick_fixes": [],
            "diagnostics": {},
        }
        sidecars = {
            "result": "PASS",
            "path": "/tmp/index.json",
            "warnings": [],
            "problems": [],
            "quick_fixes": [],
            "diagnostics": {},
        }
        shared = {
            "result": "WARN",
            "path": "/tmp/shared.db",
            "warnings": ["needs attention"],
            "problems": [],
            "quick_fixes": ["/memory doctor --json"],
        }
        codememory = {
            "result": "FAIL",
            "path": "/tmp/codememory.db",
            "warnings": [],
            "problems": ["plan is unhealthy"],
            "quick_fixes": [],
        }
        with (
            patch.object(self.module, "_session_reports", return_value=(runtime, sidecars)),
            patch.object(self.module, "_shared_memory_store", return_value=shared),
            patch.object(self.module, "_codememory_store", return_value=codememory),
        ):
            report = self.module.build_report()

        self.assertEqual("FAIL", report["result"])
        self.assertEqual(
            ["runtime_history", "session_sidecars", "shared_memory", "codememory"],
            report["store_order"],
        )
        self.assertEqual(report["store_order"], list(report["stores"]))
        self.assertIn("shared_memory: needs attention", report["warnings"])
        self.assertIn("codememory: plan is unhealthy", report["problems"])

    def test_runtime_and_private_sidecars_are_pass(self) -> None:
        report = self._session_report()
        runtime = self.module._runtime_store(report)
        sidecars = self.module._sidecar_store(report)
        self.assertEqual("PASS", runtime["result"])
        self.assertEqual("PASS", sidecars["result"])

    def test_missing_shared_memory_is_warn_without_creating_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "shared.db"
            with patch.object(self.module, "DEFAULT_DB_PATH", path):
                report = self.module._inspect_shared_memory()
            self.assertEqual("WARN", report["result"])
            self.assertFalse(path.exists())
            self.assertFalse(path.parent.exists())

    def test_shared_memory_health_uses_readonly_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shared.db"
            connection = shared_memory_runtime.connect(path)
            connection.close()
            before = path.read_bytes()
            with patch.object(self.module, "DEFAULT_DB_PATH", path):
                report = self.module._inspect_shared_memory()
            self.assertEqual("PASS", report["result"])
            self.assertEqual(before, path.read_bytes())

    def test_invalid_shared_memory_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shared.db"
            path.write_text("not sqlite", encoding="utf-8")
            with patch.object(self.module, "DEFAULT_DB_PATH", path):
                report = self.module._inspect_shared_memory()
            self.assertEqual("FAIL", report["result"])
            self.assertTrue(report["problems"])

    def test_codememory_probe_uses_scope_json_and_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.yaml"
            config.write_text(
                "database:\n  path: /tmp/codememory.db\ndefaults:\n  scope_key: test/scope\n",
                encoding="utf-8",
            )
            expected = {"status": "ok", "open_task_count": 0}
            calls: list[tuple[list[str], Path]] = []

            def fake_run(command, *, cwd, **_kwargs):
                calls.append((list(command), cwd))
                return {
                    "kind": "completed",
                    "exit_code": 0,
                    "stdout": json.dumps(expected).encode("utf-8"),
                    "stderr": b"",
                }

            with (
                patch.object(self.module, "_config_path", return_value=config),
                patch.object(
                    self.module,
                    "_codememory_db_path",
                    return_value=Path(tmp) / "codememory.db",
                ),
                patch.object(self.module.shutil, "which", return_value="/usr/bin/oc"),
                patch.object(self.module, "_run_bounded_command", side_effect=fake_run),
            ):
                Path(tmp, "codememory.db").touch()
                report = self.module._codememory_store()

            self.assertEqual("PASS", report["result"])
            self.assertEqual(1, len(calls))
            self.assertEqual(
                [
                    "/usr/bin/oc",
                    "--config",
                    str(config),
                    "plan",
                    "doctor",
                    "--scope",
                    "test/scope",
                    "--format",
                    "json",
                ],
                calls[0][0],
            )
            self.assertEqual(REPO_ROOT, calls[0][1])

    def test_codememory_status_and_fields_cannot_fail_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.yaml"
            config.write_text("defaults:\n  scope_key: test/scope\n", encoding="utf-8")
            db_path = Path(tmp) / "codememory.db"
            db_path.touch()

            def report_payload(payload: dict) -> dict:
                return {
                    "kind": "completed",
                    "exit_code": 0,
                    "stdout": json.dumps(payload).encode("utf-8"),
                    "stderr": b"",
                }

            with (
                patch.object(self.module, "_config_path", return_value=config),
                patch.object(self.module, "_codememory_db_path", return_value=db_path),
                patch.object(self.module.shutil, "which", return_value="/usr/bin/oc"),
                patch.object(
                    self.module,
                    "_run_bounded_command",
                    return_value=report_payload(
                        {"status": "ok", "problems": ["unexpected problem"]}
                    ),
                ),
            ):
                contradictory = self.module._codememory_store()
            self.assertEqual("FAIL", contradictory["result"])

            with (
                patch.object(self.module, "_config_path", return_value=config),
                patch.object(self.module, "_codememory_db_path", return_value=db_path),
                patch.object(self.module.shutil, "which", return_value="/usr/bin/oc"),
                patch.object(
                    self.module,
                    "_run_bounded_command",
                    return_value=report_payload(
                        {"status": "warn", "warnings": "not-a-list"}
                    ),
                ),
            ):
                malformed = self.module._codememory_store()
            self.assertEqual("FAIL", malformed["result"])

            with (
                patch.object(self.module, "_config_path", return_value=config),
                patch.object(self.module, "_codememory_db_path", return_value=db_path),
                patch.object(self.module.shutil, "which", return_value="/usr/bin/oc"),
                patch.object(
                    self.module,
                    "_run_bounded_command",
                    return_value=report_payload({"status": "unknown"}),
                ),
            ):
                unknown = self.module._codememory_store()
            self.assertEqual("FAIL", unknown["result"])

    def test_doctor_sqlite_route_delegates_to_store_dashboard(self) -> None:
        with patch.object(self.module, "main", return_value=17) as dashboard:
            self.assertEqual(17, doctor_command.command_sqlite(["--json"]))
            dashboard.assert_called_once_with(["--json"])

        with patch.object(doctor_command, "command_sqlite", return_value=17) as route:
            self.assertEqual(17, doctor_command.main(["sqlite", "--json"]))
            route.assert_called_once_with(["--json"])

    def test_worker_memory_limit_fails_closed_and_can_be_enforced(self) -> None:
        failing_resource = types.SimpleNamespace(
            RLIMIT_AS=1,
            RLIM_INFINITY=-1,
            getrlimit=lambda _: (_ for _ in ()).throw(OSError("blocked")),
        )
        with patch.dict(sys.modules, {"resource": failing_resource}):
            failure = self.module._apply_worker_memory_limit()
        self.assertIn("memory limit unavailable", failure or "")

        set_calls: list[tuple[int, tuple[int, int]]] = []

        def set_limit(resource_id: int, limits: tuple[int, int]) -> None:
            set_calls.append((resource_id, limits))

        working_resource = types.SimpleNamespace(
            RLIMIT_AS=1,
            RLIM_INFINITY=-1,
            getrlimit=lambda _: (-1, -1),
            setrlimit=set_limit,
        )
        with patch.dict(sys.modules, {"resource": working_resource}):
            self.assertIsNone(self.module._apply_worker_memory_limit())
        self.assertEqual([(1, (self.module.SHARED_MEMORY_WORKER_MEMORY_BYTES, -1))], set_calls)

    def test_bounded_child_output_and_timeout_are_failures(self) -> None:
        output = self.module._run_bounded_command(
            [sys.executable, "-c", "print('x' * 1000)"],
            cwd=REPO_ROOT,
            max_output_bytes=32,
        )
        self.assertEqual("output_limit", output["kind"])
        timeout = self.module._run_bounded_command(
            [sys.executable, "-c", "import time; time.sleep(1)"],
            cwd=REPO_ROOT,
            timeout_seconds=0.05,
        )
        self.assertEqual("timeout", timeout["kind"])

    @unittest.skipUnless(os.name != "nt", "process groups require Unix")
    def test_timeout_terminates_descendant_processes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "descendant-alive"
            child_code = (
                "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "time.sleep(0.4); "
                f"open({str(marker)!r}, 'w', encoding='utf-8').write('alive')"
            )
            parent_code = (
                "import subprocess, sys, time; "
                f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
                "print(child.pid, flush=True); time.sleep(2)"
            )
            result = self.module._run_bounded_command(
                [sys.executable, "-c", parent_code],
                cwd=REPO_ROOT,
                timeout_seconds=0.05,
            )
            self.assertEqual("timeout", result["kind"])
            time.sleep(0.6)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
