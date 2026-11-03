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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

gateway = importlib.import_module("gateway_command")


class GatewayMemoryRecoverySafetyTest(unittest.TestCase):
    def test_direct_apply_and_protection_enable_fail_before_side_effects(self) -> None:
        cases = (
            ["recover", "memory", "--apply", "--json"],
            ["recover", "memory", "--apply", "--resume", "--compress", "--continue-prompt", "--force-kill", "--json"],
            ["protection", "enable", "--interval-seconds", "1", "--json"],
        )
        for args in cases:
            with self.subTest(args=args), contextlib.redirect_stdout(io.StringIO()) as stdout, \
                    patch.object(gateway, "load_config", side_effect=AssertionError("config accessed")), \
                    patch.object(gateway, "status_payload", side_effect=AssertionError("status sampled")), \
                    patch.object(gateway.subprocess, "run", side_effect=AssertionError("subprocess started")), \
                    patch.object(gateway.os, "kill", side_effect=AssertionError("process signaled")), \
                    patch.object(Path, "write_text", side_effect=AssertionError("file written")):
                result = gateway._main(args)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(result, 1)
                self.assertEqual(payload["result"], "FAIL")
                self.assertEqual(payload["reason_code"], gateway.RECOVERY_IDENTITY_UNVERIFIED)
                self.assertIn("No process was signaled", payload["error"])

    def test_direct_python_entrypoints_also_refuse_apply(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as stdout, \
                patch.object(gateway, "load_config", side_effect=AssertionError("config accessed")), \
                patch.object(gateway.subprocess, "run", side_effect=AssertionError("subprocess started")), \
                patch.object(gateway.os, "kill", side_effect=AssertionError("process signaled")):
            result = gateway.command_recover_memory(True, apply=True, force_kill=True)
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(stdout.getvalue())["reason_code"], gateway.RECOVERY_IDENTITY_UNVERIFIED)

    def test_human_preview_does_not_advertise_force_kill(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            gateway.print_gateway_recover_human({"result": "PASS", "mode": "dry_run", "policy": {"force_kill_min_pressure_mb": 1}})
        self.assertIn("automatic termination is disabled", stdout.getvalue())
        self.assertNotIn("force_kill>=", stdout.getvalue())
        self.assertNotIn("--apply", stdout.getvalue())

    def test_loaded_agent_status_does_not_claim_its_code_is_safe(self) -> None:
        with tempfile.TemporaryDirectory(prefix="recovery-status-") as raw:
            home = Path(raw)
            for action in ("status", "report"):
                stdout = io.StringIO()
                with self.subTest(action=action), patch.dict(os.environ, {"HOME": str(home)}), \
                        patch.object(gateway.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")), \
                        contextlib.redirect_stdout(stdout):
                    result = gateway.command_protection(
                        True, action, interval_seconds=1, max_cycles=1, limit=10, clear_cache=False,
                    )
                payload = json.loads(stdout.getvalue())
                self.assertEqual(result, 0)
                self.assertTrue(payload["loaded"])
                self.assertFalse(payload["local_code_automatic_recovery_available"])
                self.assertFalse(payload["loaded_agent_code_verified"])

    @staticmethod
    def preview_payload() -> dict:
        return {
            "result": "PASS", "candidate_count": 1,
            "status_snapshot": {"process_pressure": {"max_pressure_mb": 3000, "swap": {"used_mb": 0}}},
            "actions": [{"pid": 12345, "action": "candidate", "result": "unqualified"}],
        }

    def test_watch_requested_apply_is_diagnostic_only_and_reports_block(self) -> None:
        with tempfile.TemporaryDirectory(prefix="recovery-watch-") as raw:
            home = Path(raw)
            state = home / ".config/opencode/my_opencode/runtime/gateway-protection-state.json"
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps({"runs": [{"synthetic": "preserve"}]}), encoding="utf-8")
            completed = subprocess.CompletedProcess([], 0, json.dumps(self.preview_payload()), "")
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.dict(os.environ, {"HOME": str(home)}), \
                    patch.object(gateway, "load_config", return_value=({}, home / "config")), \
                    patch.object(gateway.subprocess, "run", return_value=completed) as child, \
                    patch.object(gateway.os, "kill", side_effect=AssertionError("process signaled")), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = gateway.command_recover_memory_watch(
                    True, apply=True, resume=True, compress=True, continue_prompt=True,
                    force_kill=True, interval_seconds=1, max_cycles=1,
                )
            report = json.loads(stdout.getvalue())
            self.assertEqual(result, 1)
            self.assertEqual(report["result"], "FAIL")
            self.assertFalse(report["automatic_recovery_available"])
            self.assertTrue(report["options"]["apply_requested"])
            for option in ("apply", "resume", "compress", "continue_prompt", "force_kill"):
                self.assertFalse(report["options"][option])
            self.assertEqual(report["cycles"][0]["result"], "BLOCKED")
            self.assertEqual(report["cycles"][0]["reason_code"], gateway.RECOVERY_IDENTITY_UNVERIFIED)
            self.assertIn("diagnostic-only", stderr.getvalue())
            command = child.call_args.args[0]
            self.assertEqual(command[2:], ["recover", "memory", "--json"])
            self.assertEqual(len(child.call_args_list), 1)
            rows = json.loads(state.read_text(encoding="utf-8"))["runs"]
            self.assertEqual(rows[0], {"synthetic": "preserve"})
            self.assertTrue(rows[1]["apply_blocked"])

    def test_unbounded_existing_watcher_remains_alive_without_signaling(self) -> None:
        class StopAfterOneCycle(Exception):
            pass

        with tempfile.TemporaryDirectory(prefix="recovery-keepalive-") as raw:
            home = Path(raw)
            completed = subprocess.CompletedProcess([], 0, json.dumps(self.preview_payload()), "")
            with patch.dict(os.environ, {"HOME": str(home)}), \
                    patch.object(gateway, "load_config", return_value=({}, home / "config")), \
                    patch.object(gateway.subprocess, "run", return_value=completed) as child, \
                    patch.object(gateway.os, "kill", side_effect=AssertionError("process signaled")), \
                    patch.object(gateway.time, "sleep", side_effect=StopAfterOneCycle) as sleep, \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(StopAfterOneCycle):
                gateway.command_recover_memory_watch(
                    True, apply=True, resume=True, compress=True, continue_prompt=True,
                    force_kill=True, interval_seconds=2, max_cycles=0,
                )
            self.assertEqual(len(child.call_args_list), 1)
            sleep.assert_called_once_with(2)
            self.assertNotIn("--apply", child.call_args.args[0])

    def test_preview_neither_updates_cache_nor_looks_up_live_sessions(self) -> None:
        for title in ("ses_Synthetic1", "no-session"):
            with self.subTest(title=title), tempfile.TemporaryDirectory(prefix="recovery-preview-") as raw:
                home = Path(raw)
                cache = home / ".config/opencode/my_opencode/runtime/gateway-pane-session-cache.json"
                cache.parent.mkdir(parents=True)
                cache.write_text('{"panes":{"%old":"ses_Preserve"}}\n', encoding="utf-8")
                before = (cache.read_bytes(), cache.stat().st_ino, cache.stat().st_mtime_ns)
                calls = []

                def fake_run(command, *, captured_calls=calls, captured_title=title, **kwargs):
                    captured_calls.append(command)
                    if command[:2] == ["ps", "-o"]:
                        return subprocess.CompletedProcess(command, 0, "12345 ttys011\n", "")
                    if command[:2] == ["ps", "eww"]:
                        return subprocess.CompletedProcess(command, 0, "12345 opencode PWD=/synthetic TMUX_PANE=%7\n", "")
                    if command[:2] == ["tmux", "list-panes"]:
                        return subprocess.CompletedProcess(command, 0, f"fixture\t0\t1\t%7\t/dev/ttys011\t0\topencode\t{captured_title}\n", "")
                    raise AssertionError("unexpected subprocess")

                status = {"process_pressure": {"high_rss": [{"pid": 12345, "rss_mb": 2000, "command": "opencode serve --service"}]}}
                stdout = io.StringIO()
                with patch.dict(os.environ, {"HOME": str(home)}), \
                        patch.object(gateway, "load_config", return_value=({}, home / "config")), \
                        patch.object(gateway, "status_payload", return_value=status), \
                        patch.object(gateway.subprocess, "run", side_effect=fake_run), \
                        patch.object(gateway.os, "kill", side_effect=AssertionError("process signaled")), \
                        contextlib.redirect_stdout(stdout):
                    result = gateway.command_recover_memory(True, resume=True, compress=True)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(result, 0)
                self.assertFalse(payload["automatic_recovery_available"])
                self.assertEqual(payload["actions"][0]["result"], "unqualified")
                self.assertFalse(payload["actions"][0]["process_identity_verified"])
                self.assertFalse(payload["actions"][0]["resume_planned"])
                self.assertEqual(before, (cache.read_bytes(), cache.stat().st_ino, cache.stat().st_mtime_ns))
                self.assertEqual([call[:2] for call in calls], [["ps", "-o"], ["ps", "eww"], ["tmux", "list-panes"]])
                self.assertNotIn("--apply", json.dumps(payload["recommended_commands"]))
                self.assertNotIn("--apply", json.dumps(payload["next_steps"]))

    @unittest.skipUnless(os.name == "posix", "fixture executables require POSIX")
    def test_real_cli_refuses_without_subprocess_or_signal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="recovery-cli-") as raw:
            root = Path(raw)
            home, bin_dir, site = root / "home", root / "bin", root / "site"
            for directory in (home, bin_dir, site):
                directory.mkdir()
            sentinel = home / "runtime-sentinel"
            sentinel.write_text("synthetic live-state sentinel\n", encoding="utf-8")
            tripwire = root / "tripwire"
            (site / "sitecustomize.py").write_text(
                "import os, subprocess\n"
                "def forbidden(*args, **kwargs):\n"
                "    with open(os.environ['TRIPWIRE'], 'a') as stream: stream.write('called\\n')\n"
                "    raise RuntimeError('forbidden side effect')\n"
                "os.kill = forbidden\nsubprocess.run = forbidden\n",
                encoding="utf-8",
            )
            for name in ("ps", "tmux", "opencode", "launchctl"):
                stub = bin_dir / name
                stub.write_text('#!/bin/sh\nprintf called >> "$TRIPWIRE"\nexit 99\n', encoding="utf-8")
                stub.chmod(0o700)
            env = {"HOME": str(home), "PATH": str(bin_dir), "PYTHONPATH": str(site),
                   "PYTHONDONTWRITEBYTECODE": "1", "TRIPWIRE": str(tripwire), "CI": "true"}
            before = (sentinel.read_bytes(), sentinel.stat().st_ino)
            cases = (["recover", "memory", "--apply", "--force-kill", "--resume", "--json"],
                     ["protection", "enable", "--json"])
            for args in cases:
                result = subprocess.run([sys.executable, str(ROOT / "scripts/gateway_command.py"), *args],
                                        env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10, check=False)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(json.loads(result.stdout)["reason_code"], gateway.RECOVERY_IDENTITY_UNVERIFIED)
                self.assertFalse(tripwire.exists())
                self.assertEqual(before, (sentinel.read_bytes(), sentinel.stat().st_ino))
                self.assertEqual([path.name for path in home.iterdir()], ["runtime-sentinel"])

    @unittest.skipUnless(os.name == "posix", "fixture executables require POSIX")
    def test_real_watcher_uses_synthetic_diagnostics_without_signaling(self) -> None:
        with tempfile.TemporaryDirectory(prefix="recovery-watch-cli-") as raw:
            root = Path(raw)
            home, bin_dir, site, project, temporary = (root / name for name in ("home", "bin", "site", "project", "tmp"))
            for directory in (home, bin_dir, site, project, temporary):
                directory.mkdir()
            (project / "opencode.json").write_text('{"memoryRecovery":{"notificationsEnabled":false}}\n', encoding="utf-8")
            sentinel = home / "runtime-sentinel"
            sentinel.write_text("synthetic live-state sentinel\n", encoding="utf-8")
            state = home / ".config/opencode/my_opencode/runtime/gateway-protection-state.json"
            state.parent.mkdir(parents=True)
            state.write_text('{"runs":[{"synthetic":"preserve"}]}\n', encoding="utf-8")
            tripwire = root / "tripwire"
            (site / "sitecustomize.py").write_text(
                "import os\n"
                "def forbidden(*args, **kwargs):\n"
                "    with open(os.environ['TRIPWIRE'], 'a') as stream: stream.write('signal\\n')\n"
                "    raise RuntimeError('forbidden signal')\n"
                "os.kill = forbidden\nos.killpg = forbidden\n",
                encoding="utf-8",
            )
            scripts = {
                "ps": 'case "$1" in\n-axo) printf "12345 1 1 1 2097152 00:10 ?? /synthetic/opencode serve --service\\n";;\n-o) printf "12345 ??\\n";;\neww) printf "12345 opencode PWD=/synthetic\\n";;\nesac',
                "top": 'printf "12345 opencode 8G\\n"',
                "sysctl": 'printf "total = 16G used = 1G free = 15G\\n"',
                "opencode": 'if [ "$1" = "--version" ]; then printf "opencode v2.2.5\\n"; else printf session >> "$TRIPWIRE"; exit 99; fi',
                "tmux": 'if [ "$1" = "send-keys" ]; then printf tmux >> "$TRIPWIRE"; fi; exit 1',
                "launchctl": 'printf launchctl >> "$TRIPWIRE"; exit 99',
            }
            for name, script in scripts.items():
                binary = bin_dir / name
                binary.write_text("#!/bin/sh\n" + script + "\n", encoding="utf-8")
                binary.chmod(0o700)
            env = {
                "HOME": str(home), "PATH": str(bin_dir), "TMPDIR": str(temporary),
                "XDG_CONFIG_HOME": str(home / ".config"), "XDG_CACHE_HOME": str(home / ".cache"),
                "XDG_DATA_HOME": str(home / ".local/share"), "XDG_STATE_HOME": str(home / ".local/state"),
                "PYTHONPATH": str(site), "PYTHONDONTWRITEBYTECODE": "1", "TRIPWIRE": str(tripwire), "CI": "true",
            }
            before = (sentinel.read_bytes(), sentinel.stat().st_ino)
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/gateway_command.py"), "recover", "memory", "--watch", "--apply", "--force-kill", "--resume", "--max-cycles", "1", "--json"],
                cwd=project, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20, check=False,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["options"]["apply_requested"])
            self.assertFalse(report["options"]["apply"])
            self.assertEqual(report["cycles"][0]["result"], "BLOCKED")
            self.assertEqual(report["cycles"][0]["candidate_count"], 1)
            self.assertIn("diagnostic-only", result.stderr)
            self.assertFalse(tripwire.exists())
            self.assertEqual(before, (sentinel.read_bytes(), sentinel.stat().st_ino))
            rows = json.loads(state.read_text(encoding="utf-8"))["runs"]
            self.assertEqual(rows[0], {"synthetic": "preserve"})
            self.assertTrue(rows[1]["apply_blocked"])


if __name__ == "__main__":
    unittest.main()
