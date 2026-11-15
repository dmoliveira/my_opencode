from __future__ import annotations

import copy
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gateway_v2_dependency_contract_probe as probe


@contextmanager
def retained_directory() -> Iterator[str]:
    """Retain synthetic fixtures and version-probe roots."""
    yield tempfile.mkdtemp(prefix="v2-boundary-unit-")


class BoundaryProbeTests(unittest.TestCase):
    def test_environment_is_allowlisted_not_filtered(self) -> None:
        poison = {
            "OPENCODE_DB": "/real/database", "OPENCODE_SESSION_ID": "real_session",
            "OPENCODE_SERVER": "https://external.invalid", "OPENCODE_CONFIG": "/real/config",
            "OPENCODE_CONFIG_CONTENT": "poison", "OPENAI_API_KEY": "SECRET_CANARY",
            "AWS_PROFILE": "real", "NODE_OPTIONS": "--import=poison", "BASH_ENV": "poison",
            "HTTP_PROXY": "https://external.invalid", "PATH": "/poison", "HOME": "/real/home",
        }
        with patch.dict(os.environ, poison, clear=True):
            env = probe.child_env(Path("/owned"))
            self.assertEqual(os.environ, poison)
        self.assertEqual(env["OPENCODE_DB"], "/owned/runtime.sqlite")
        self.assertEqual(env["HOME"], "/owned/home")
        self.assertTrue(env["PATH"].startswith("/owned/bin:"))
        self.assertFalse(set(poison) - {"OPENCODE_DB", "PATH", "HOME"} & env.keys())
        self.assertNotIn("SECRET_CANARY", json.dumps(env))

    def test_preflight_rejects_ancestor_configuration_and_dangling_links(self) -> None:
        with retained_directory() as temp:
            root = Path(temp)
            child = root / "child"
            child.mkdir()
            for name in ("opencode.json", "opencode.jsonc", ".opencode"):
                config = root / name
                config.symlink_to(root / "nonexistent")
                with self.assertRaisesRegex(probe.ProbeFailure, "ancestor_configuration_present"):
                    probe.preflight(child)
                self.assertTrue(config.is_symlink())
                config.unlink()

    def test_preflight_does_not_bypass_system_policy(self) -> None:
        with retained_directory() as temp:
            original = Path.exists

            def exists(path: Path) -> bool:
                return str(path) == "/etc/opencode" or original(path)

            with patch.object(Path, "exists", exists), self.assertRaisesRegex(probe.ProbeFailure, "system_configuration_present"):
                probe.preflight(Path(temp))

    def test_provisioning_is_owned_and_private(self) -> None:
        with retained_directory() as temp:
            root = Path(temp)
            sentinel = root / "sentinel"
            sentinel.write_text("UNCHANGED")
            probe.write_fixture(root, "project/plugin/index.ts", "fixture")
            self.assertEqual((root / "project/plugin/index.ts").stat().st_mode & 0o777, 0o600)
            self.assertEqual(sentinel.read_text(), "UNCHANGED")
            for path in ("../outside", "/absolute"):
                with self.assertRaisesRegex(probe.ProbeFailure, "fixture_path_outside_root"):
                    probe.write_fixture(root, path, "bad")
            (root / "link").symlink_to(root / "project", target_is_directory=True)
            with self.assertRaisesRegex(probe.ProbeFailure, "fixture_parent_is_symlink"):
                probe.write_fixture(root, "link/new-file", "bad")

    def test_cleanup_preserves_replaced_fixture_and_host_sentinel(self) -> None:
        with retained_directory() as temp:
            parent = Path(temp)
            sentinel = parent / "host-sentinel"
            sentinel.write_text("UNCHANGED")
            with self.assertRaisesRegex(probe.ProbeFailure, "fixture_identity_changed"), probe.owned_fixture(parent) as root:
                original = parent / "preserved-original"
                root.rename(original)
                root.symlink_to(parent, target_is_directory=True)
            self.assertEqual(sentinel.read_text(), "UNCHANGED")
            self.assertTrue(original.is_dir())
            self.assertTrue(root.is_symlink())

    def test_owned_fixture_retains_success_and_failure_without_removal(self) -> None:
        with retained_directory() as temp:
            parent = Path(temp)
            with patch.object(probe.shutil, "rmtree", side_effect=AssertionError("unexpected deletion")):
                with probe.owned_fixture(parent) as success:
                    (success / "witness").write_text("synthetic")
                with self.assertRaisesRegex(probe.ProbeFailure, "synthetic_failure"), probe.owned_fixture(parent) as failure:
                    raise probe.ProbeFailure("synthetic_failure")
            self.assertTrue(success.is_dir())
            self.assertEqual((success / "witness").read_text(), "synthetic")
            self.assertTrue(failure.is_dir())

    def test_owned_fixture_privacy_change_fails_without_removing_it(self) -> None:
        with retained_directory() as temp:
            with (
                patch.object(probe.shutil, "rmtree", side_effect=AssertionError("unexpected deletion")),
                self.assertRaisesRegex(probe.ProbeFailure, "fixture_identity_changed"),
                probe.owned_fixture(Path(temp)) as root,
            ):
                root.chmod(0o755)
            self.assertTrue(root.is_dir())

    def test_provider_thread_start_failure_closes_unstarted_server(self) -> None:
        with retained_directory() as temp:
            server = MagicMock()
            with (
                patch.object(probe, "BoundedProvider", return_value=server),
                patch.object(probe.threading, "Thread") as thread,
            ):
                thread.return_value.start.side_effect = RuntimeError("synthetic startup failure")
                with self.assertRaises(RuntimeError):
                    probe.run_case(Path(temp), "baseline", "/not-executed")
            server.shutdown.assert_not_called()
            server.close_connections.assert_called_once()
            server.server_close.assert_called_once()
            thread.return_value.join.assert_not_called()

    def test_provider_cleanup_failure_still_attempts_each_teardown_step(self) -> None:
        with retained_directory() as temp:
            server = MagicMock()
            server.shutdown.side_effect = OSError("synthetic failure")
            with (
                patch.object(probe, "BoundedProvider", return_value=server),
                patch.object(probe.threading, "Thread") as thread,
                patch.object(probe, "write_fixture", side_effect=probe.ProbeFailure("setup_failed")),
            ):
                thread.return_value.is_alive.return_value = False
                with self.assertRaisesRegex(probe.ProbeFailure, "provider_cleanup_failed"):
                    probe.run_case(Path(temp), "baseline", "/not-executed")
            server.shutdown.assert_called_once()
            server.close_connections.assert_called_once()
            server.server_close.assert_called_once()
            thread.return_value.join.assert_called_once()

    def test_process_success_and_nonzero_are_not_relabelled(self) -> None:
        with retained_directory() as temp:
            root = Path(temp)
            code, out, err = probe.run_child([sys.executable, "-c", "print('SAFE'); raise SystemExit(7)"], root, probe.child_env(root), timeout=5)
            self.assertEqual((code, out, err), (7, b"SAFE\n", b""))

    def test_process_timeout_and_overflow_are_failures_and_reaped(self) -> None:
        with retained_directory() as temp:
            root = Path(temp)
            for code, timeout, reason in (
                ("import time; time.sleep(30)", 0.1, "child_timeout"),
                ("import sys; sys.stdout.write('x' * 200000); sys.stdout.flush()", 5, "child_output_limit"),
            ):
                with self.assertRaisesRegex(probe.ProbeFailure, reason):
                    probe.run_child([sys.executable, "-c", code], root, probe.child_env(root), timeout=timeout)

    def test_cleanup_signals_before_reap_even_after_eof(self) -> None:
        process = MagicMock(spec=subprocess.Popen)
        process.pid = 12345
        calls = []
        process.wait.side_effect = lambda **kwargs: calls.append("reap")
        with patch.object(probe.os, "killpg", side_effect=lambda pid, sig: calls.append(sig)), patch.object(probe.threading, "Event"):
            probe.stop_group(process)
        self.assertEqual(calls, [probe.signal.SIGTERM, probe.signal.SIGKILL, "reap"])

    def test_schema_is_native_and_does_not_publish_descriptions(self) -> None:
        schema = {"type": "object", "properties": {"command": {"type": "string", "description": "SECRET_CANARY"}}, "required": ["command"], "additionalProperties": False}
        measured = probe.schema_summary(schema)
        self.assertNotIn("SECRET_CANARY", json.dumps(measured))
        self.assertEqual(probe.native_input(measured, "printf safe", Path("/owned")), {"command": "printf safe"})
        measured["required"].append("unknown")
        with self.assertRaisesRegex(probe.ProbeFailure, "unsupported_native_shell_required_fields"):
            probe.native_input(measured, "printf safe", Path("/owned"))
        with self.assertRaises(probe.ProbeFailure):
            probe.native_input({}, "printf safe", Path("/owned"))

    def test_provider_dispatches_once_then_requires_real_tool_continuation(self) -> None:
        state = probe.ProviderState(Path("/owned/project"), probe.COMMANDS["baseline"])
        request = {"messages": [], "tools": [{"function": {"name": "shell", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}}]}
        delta, reason = state.response(request)
        self.assertEqual(reason, "tool_calls")
        self.assertEqual(delta["tool_calls"][0]["function"]["name"], "shell")
        with self.assertRaisesRegex(probe.ProbeFailure, "unexpected_provider_request"):
            state.response(request)
        delta, reason = state.response({"messages": [{"role": "tool", "tool_call_id": probe.CALL_ID, "content": "synthetic"}]})
        self.assertEqual(reason, "stop")
        self.assertEqual(delta["content"], "PROBE_FINISHED")

    def test_missing_shell_and_request_limits_fail(self) -> None:
        state = probe.ProviderState(Path("/owned"), "printf safe")
        with self.assertRaisesRegex(probe.ProbeFailure, "native_shell_not_exposed"):
            state.response({})
        state.requests = probe.MAX_REQUESTS
        with self.assertRaisesRegex(probe.ProbeFailure, "provider_request_limit"):
            state.response({})

    def test_unrelated_tool_reply_never_counts_as_continuation(self) -> None:
        state = probe.ProviderState(Path("/owned"), "printf safe", dispatched=1)
        with self.assertRaisesRegex(probe.ProbeFailure, "provider_tool_correlation_failed"):
            state.response({"messages": [{"role": "tool", "tool_call_id": "unrelated", "content": "synthetic"}]})
        self.assertFalse(state.continued)

    def test_provider_limits_all_connection_admissions_before_headers(self) -> None:
        state = probe.ProviderState(Path("/owned"), "synthetic")
        with probe.BoundedProvider(state) as server:
            connection = MagicMock()
            for _ in range(probe.MAX_REQUESTS):
                self.assertTrue(server.verify_request(connection, ("127.0.0.1", 1)))
            self.assertFalse(server.verify_request(connection, ("127.0.0.1", 1)))
            connection.settimeout.assert_called_with(2)
            self.assertEqual(len(server.admitted), probe.MAX_REQUESTS)
            self.assertEqual(state.failure, "provider_connection_limit")
            server.close_connections()

    def test_partial_headers_cannot_stall_provider_cleanup(self) -> None:
        state = probe.ProviderState(Path("/owned"), "synthetic")
        server = probe.BoundedProvider(state)
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        worker.start()
        client = socket.create_connection(server.server_address, timeout=2)
        try:
            client.sendall(b"POST /v1/chat/completions HTTP/1.1\r\nX-Incomplete: ")
            deadline = time.monotonic() + 2
            while not server.admitted and time.monotonic() < deadline:
                threading.Event().wait(0.01)
            self.assertTrue(server.admitted)
            start = time.monotonic()
            server.shutdown()
            server.close_connections()
            server.server_close()
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive())
            self.assertLess(time.monotonic() - start, 1)
        finally:
            client.close()
            if worker.is_alive():
                server.shutdown()
                server.close_connections()
                server.server_close()
                worker.join(timeout=1)

    def test_darwin_zombie_exception_rejects_incomplete_or_live_groups(self) -> None:
        for raw in (b"", b"12345 12345 Z\n4 12345 S\n", b"4 12345 Z\n", b"12345 99 Z\n", b"malformed\n"):
            with patch.object(probe.sys, "platform", "darwin"), patch.object(probe.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, raw, b"")):
                self.assertFalse(probe.darwin_zombie_group(12345))
        with patch.object(probe.sys, "platform", "darwin"), patch.object(probe.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"12345 12345 Z\n", b"")):
            self.assertTrue(probe.darwin_zombie_group(12345))

    def test_unconfirmed_signal_denial_fails_and_still_attempts_reap(self) -> None:
        process = MagicMock(spec=subprocess.Popen)
        process.pid = 12345
        with patch.object(probe.os, "killpg", side_effect=PermissionError()), patch.object(probe, "darwin_zombie_group", return_value=False), self.assertRaisesRegex(probe.ProbeFailure, "owned_group_signal_denied"):
            probe.stop_group(process)
        process.wait.assert_called_once_with(timeout=5)

    def test_no_custom_executor_or_auto_approval_is_generated(self) -> None:
        combined = probe.OBSERVER_PLUGIN + probe.LATE_PLUGIN
        self.assertNotIn("editor.update", combined)
        self.assertNotIn("editor.add", combined)
        self.assertNotIn("execute:", combined)
        config = probe.fixture_config(Path("/owned/project"), 12345)
        self.assertEqual(config["permissions"][0]["effect"], "deny")
        self.assertEqual(config["agents"]["build"]["permissions"], config["permissions"])
        self.assertEqual(len(config["plugins"]), 2)
        self.assertEqual(config["providers"]["boundary"]["settings"]["baseURL"], "http://127.0.0.1:12345/v1")

    def test_trace_bounds_fail_closed(self) -> None:
        with retained_directory() as temp:
            path = Path(temp) / "trace.jsonl"
            with self.assertRaises(probe.ProbeFailure):
                probe.read_trace(path)
            path.write_text("{}\n" * (probe.MAX_ROWS + 1))
            with self.assertRaisesRegex(probe.ProbeFailure, "trace_rows_invalid"):
                probe.read_trace(path)
            path.write_text("x" * (probe.MAX_TRACE + 1))
            with self.assertRaisesRegex(probe.ProbeFailure, "trace_missing_or_oversized"):
                probe.read_trace(path)

    def test_absent_witness_differs_from_invalid_entries(self) -> None:
        with retained_directory() as temp:
            path = Path(temp) / "witness"
            self.assertIsNone(probe.read_witness(path))
            path.write_text("PROBE_DENIED")
            self.assertEqual(probe.read_witness(path), "PROBE_DENIED")
            path.write_text("x" * 128)
            with self.assertRaisesRegex(probe.ProbeFailure, "witness_invalid"):
                probe.read_witness(path)
            path.unlink()
            path.symlink_to(Path(temp) / "missing")
            with self.assertRaisesRegex(probe.ProbeFailure, "witness_invalid"):
                probe.read_witness(path)
            path.unlink()
            path.mkdir()
            with self.assertRaisesRegex(probe.ProbeFailure, "witness_invalid"):
                probe.read_witness(path)

    def test_failure_never_echoes_native_diagnostics_or_qualifies_authority(self) -> None:
        with retained_directory() as temp, patch.object(probe, "run_child", side_effect=OSError("SECRET_CANARY /real/consumer/path")), patch.object(probe.shutil, "rmtree", side_effect=AssertionError("unexpected deletion")):
            report = probe.probe("/native/host", Path(temp))
            self.assertTrue((Path(temp) / report["retained_version_fixture"]).is_dir())
            self.assertFalse(report["version_teardown_complete"])
        self.assertEqual(report["result"], "FAIL")
        self.assertEqual(report["authority"], "disabled-unqualified")
        self.assertNotIn("SECRET_CANARY", json.dumps(report))
        self.assertNotIn("/real/consumer", json.dumps(report))

    def test_wrong_version_stops_before_fixtures(self) -> None:
        with retained_directory() as temp, patch.object(probe, "run_child", return_value=(0, b"opencode v9.9.9\n", b"")), patch.object(probe, "run_case") as case, patch.object(probe.shutil, "rmtree", side_effect=AssertionError("unexpected deletion")):
            report = probe.probe("/native/host", Path(temp))
            self.assertTrue((Path(temp) / report["retained_version_fixture"]).is_dir())
            self.assertTrue(report["version_teardown_complete"])
        self.assertEqual(report["reason"], "unsupported_host_version")
        case.assert_not_called()

    def test_cli_resolves_make_default_binary_from_path(self) -> None:
        with patch.object(sys, "argv", ["probe", "--opencode-bin", "opencode"]), patch.object(probe.shutil, "which", return_value="/trusted/opencode"), patch.object(probe, "probe", return_value={"result": "PASS"}) as run, patch("builtins.print"):
            self.assertEqual(probe.main(), 0)
        self.assertEqual(run.call_args.args[0], "/trusted/opencode")

    def test_measurement_requires_all_cases_and_keeps_authority_disabled(self) -> None:
        with retained_directory() as temp:
            with patch.object(probe, "run_child", return_value=(0, (probe.VERSION + "\n").encode(), b"")), patch.object(probe, "run_case", side_effect=lambda root, case, binary: {"case": case, "measurement": "PASS", "teardown_complete": True}), patch.object(probe.shutil, "rmtree", side_effect=AssertionError("unexpected deletion")):
                report = probe.probe("/native/host", Path(temp))
            roots = [report["retained_version_fixture"], *report["retained_case_fixtures"]]
            self.assertEqual(len(roots), len(probe.CASES) + 1)
            self.assertEqual(len(set(roots)), len(roots))
            self.assertTrue(all((Path(temp) / name).is_dir() for name in roots))
        self.assertEqual(report["result"], "PASS")
        self.assertEqual([case["case"] for case in report["cases"]], list(probe.CASES))
        self.assertEqual(report["authority"], "disabled-unqualified")
        self.assertIn("captured executor snapshots", report["unproven"])

    def test_failed_case_preserves_its_fixture_and_does_not_claim_teardown(self) -> None:
        with retained_directory() as temp:
            child = (0, (probe.VERSION + "\n").encode(), b"")
            with (
                patch.object(probe, "run_child", return_value=child),
                patch.object(probe, "run_case", side_effect=RuntimeError("SECRET_CANARY")),
                patch.object(probe.shutil, "rmtree", side_effect=AssertionError("unexpected deletion")),
            ):
                report = probe.probe("/native/host", Path(temp))
            self.assertEqual(report["result"], "FAIL")
            self.assertEqual(report["reason"], "probe_internal_error")
            self.assertNotIn("SECRET_CANARY", json.dumps(report))
            self.assertEqual(len(report["retained_case_fixtures"]), 1)
            self.assertTrue((Path(temp) / report["retained_case_fixtures"][0]).is_dir())

    def test_missing_case_teardown_cannot_pass_measurement(self) -> None:
        with retained_directory() as temp:
            child = (0, (probe.VERSION + "\n").encode(), b"")
            with (
                patch.object(probe, "run_child", return_value=child),
                patch.object(probe, "run_case", return_value={"case": "baseline", "measurement": "PASS", "teardown_complete": False}),
                patch.object(probe.shutil, "rmtree", side_effect=AssertionError("unexpected deletion")),
            ):
                report = probe.probe("/native/host", Path(temp))
            self.assertEqual(report["result"], "FAIL")
            self.assertEqual(report["reason"], "teardown_unconfirmed")
            self.assertTrue((Path(temp) / report["retained_case_fixtures"][0]).is_dir())

    def test_case_reports_conservative_child_settlement(self) -> None:
        with retained_directory() as temp:
            for fail in (False, True):
                with (
                    self.subTest(fail=fail),
                    patch.object(probe.shutil, "rmtree", side_effect=AssertionError("unexpected deletion")),
                    probe.owned_fixture(Path(temp)) as root,
                ):
                    child = probe.ProbeFailure("child_timeout") if fail else (0, b"PROBE_FINISHED", b"")
                    with (
                        patch.object(probe, "run_child", side_effect=child if fail else None, return_value=child if not fail else None),
                        patch.object(probe, "read_trace", return_value=[]),
                        patch.object(probe, "read_witness", return_value="PROBE_BASELINE\n"),
                        patch.object(probe, "assess", return_value={"case": "baseline", "measurement": "PASS"}),
                    ):
                        observed = probe.run_case(root, "baseline", "/not-executed")
                self.assertEqual(observed["measurement"], "FAIL" if fail else "PASS")
                self.assertIs(observed["teardown_complete"], not fail)
                self.assertTrue(root.is_dir())

    def test_late_provider_failure_cannot_be_measured_as_success(self) -> None:
        with retained_directory() as temp:
            root = Path(temp)
            state = probe.ProviderState(root / "project", "synthetic")

            def assessment(*_args: object) -> dict:
                state.failure = "provider_handler_error"
                return {"case": "baseline", "measurement": "PASS"}

            with (
                patch.object(probe, "ProviderState", return_value=state),
                patch.object(probe, "run_child", return_value=(0, b"PROBE_FINISHED", b"")),
                patch.object(probe, "read_trace", return_value=[]),
                patch.object(probe, "read_witness", return_value="PROBE_BASELINE\n"),
                patch.object(probe, "assess", side_effect=assessment),
            ):
                observed = probe.run_case(root, "baseline", "/not-executed")
            self.assertEqual(observed["measurement"], "FAIL")
            self.assertEqual(observed["reason"], "provider_handler_error")
            self.assertTrue(observed["teardown_complete"])

    def test_cli_preserves_symlink_parent_for_preflight_refusal(self) -> None:
        with retained_directory() as temp:
            parent = Path(temp)
            link = parent / "link"
            link.symlink_to(parent, target_is_directory=True)
            with (
                patch.object(sys, "argv", ["probe", "--opencode-bin", sys.executable, "--temp-parent", str(link)]),
                patch.object(probe, "probe", return_value={"result": "FAIL"}) as run,
                patch("builtins.print"),
            ):
                self.assertEqual(probe.main(), 1)
            self.assertEqual(run.call_args.args[1], link.absolute())
            with patch.object(probe, "run_child") as child:
                report = probe.probe(sys.executable, link)
            self.assertEqual(report["reason"], "temporary_parent_unavailable")
            child.assert_not_called()

    def test_measured_missing_exit_is_not_missing_collection(self) -> None:
        state = probe.ProviderState(Path("/owned"), "synthetic", requests=2, dispatched=1, continued=True, schema={"type": "object"}, tool_outcome={"call_id": probe.CALL_ID, "content_type": "str", "baseline_marker": True, "late_error_marker": False})
        identity = {"id": probe.CALL_ID, "sessionID": "native-session", "messageID": "native-message", "tool": "shell", "agent": "build"}
        rows = [
            {"phase": "observer.setup", "version": "2.2.5"}, {"phase": "late.setup"},
            {"phase": "native.definition", "id": "shell", "name": "shell", "present": True, "executeType": "function", "shape": {"execute": "function"}},
            {"phase": "observer.before", "directoryMatches": True, "identity": identity, "command": "baseline", "keys": ["input", *identity]},
            {"phase": "late.before", "command": "baseline"},
            {"phase": "observer.shell", "command": "baseline", "directoryMatches": True, "shellMatches": True, "keys": ["command", "cwd", "shell", "timeout", "env"]},
            {"phase": "late.shell", "command": "baseline"},
            {"phase": "observer.after", "status": "completed", "exits": [], "shape": {}, "keys": ["status", "result"], "identity": identity}, {"phase": "late.after", "status": "completed"},
        ]
        result = probe.assess("baseline", rows, "PROBE_BASELINE\n", state, 0, True)
        self.assertEqual(result["measurement"], "PASS")
        self.assertEqual(result["observations"][-2]["exits"], [])
        for incomplete in (rows[:-1], [row for row in rows if row["phase"] != "observer.after"]):
            with self.assertRaisesRegex(probe.ProbeFailure, "required_observation_missing"):
                probe.assess("baseline", incomplete, "PROBE_BASELINE\n", state, 0, True)
        with self.assertRaisesRegex(probe.ProbeFailure, "late_error_not_exercised"):
            probe.assess("late-after-error", rows, "PROBE_BASELINE\n", state, 0, True)
        for index, field, value, reason in (
            (5, "shellMatches", False, "shell_observation_mismatch"),
            (5, "directoryMatches", False, "shell_observation_mismatch"),
            (5, "command", "unknown", "command_observation_mismatch"),
            (7, "status", None, "after_observation_incomplete"),
        ):
            altered = [dict(row) for row in rows]
            altered[index][field] = value
            with self.assertRaisesRegex(probe.ProbeFailure, reason):
                probe.assess("baseline", altered, "PROBE_BASELINE\n", state, 0, True)


class DenialBoundaryProbeTests(unittest.TestCase):
    @staticmethod
    def sample(case: str, outcome: str):
        mode, variant = case.split("-", 1)
        initial = "denied" if variant == "direct" else "allowed"
        tool_command = "denied" if variant == "late-tool" else initial
        shell_command = "denied" if variant in ("late-tool", "late-shell") else initial
        identity = {"id": probe.CALL_ID, "sessionID": "synthetic-session", "messageID": "synthetic-message", "tool": "shell", "agent": "build"}
        status = "error" if outcome == "denied" else "completed"
        state = probe.ProviderState(
            Path("/owned"), "synthetic", requests=2, dispatched=1, continued=True,
            schema={"type": "object"}, schema_sha256="synthetic-hash",
            tool_outcome={"call_id": probe.CALL_ID, "content_type": "str",
                          "allowed_marker": variant == "late-env",
                          "permission_denied": outcome == "denied" and mode == "permission",
                          "policy_denied": outcome == "denied" and mode == "policy"},
        )
        rows = [
            {"phase": "observer.setup", "version": "2.2.5"}, {"phase": "late.setup"},
            {"phase": "native.definition", "id": "shell", "name": "shell", "present": True, "executeType": "function", "shape": {"execute": "function"}},
            {"phase": "observer.before", "directoryMatches": True, "identity": identity, "command": initial, "keys": ["input", *identity]},
            {"phase": "late.before", "command": tool_command},
            {"phase": "observer.shell", "command": tool_command, "directoryMatches": True, "shellMatches": True, "startupAbsent": True, "keys": ["command", "cwd", "shell", "timeout", "env"]},
            {"phase": "late.shell", "command": shell_command, "shellMatches": True, "startupMatches": True, "directoryMatches": True},
            {"phase": "observer.after", "status": status, "exits": [], "shape": {}, "identity": identity},
            {"phase": "late.after", "status": status},
        ]
        witness = {"denied": None, "allowed-executed": "PROBE_ALLOWED", "denied-command-executed": "PROBE_DENIED",
                   "startup-denied-command-executed": "PROBE_DENIED", "startup-not-observed": None}[outcome]
        return rows, witness, state

    def test_fixture_denies_only_the_synthetic_resource(self) -> None:
        project = Path("/owned/project")
        permission = probe.fixture_config(project, 12345, "permission")
        self.assertEqual(permission["permissions"][-1], {"action": "shell", "resource": "printf PROBE_DENIED*", "effect": "deny"})
        self.assertEqual(permission["agents"]["build"]["permissions"], permission["permissions"])
        self.assertNotIn("policies", permission)
        policy = probe.fixture_config(project, 12345, "policy")
        self.assertEqual(policy["policies"], [{"action": "tool.use", "resource": "shell:printf PROBE_DENIED*", "effect": "deny"}])
        self.assertFalse(any(rule["resource"] == "printf PROBE_DENIED*" for rule in policy["permissions"]))
        self.assertEqual(probe.ENV_COMMANDS["denied"], probe.DENIAL_COMMANDS["denied"])
        with self.assertRaisesRegex(probe.ProbeFailure, "invalid_denial_mode"):
            probe.fixture_config(project, 12345, "unexpected")

    def test_both_direct_controls_and_both_late_mutations_are_measured(self) -> None:
        for case in probe.DENIAL_CASES:
            outcome = "startup-denied-command-executed" if case.endswith("-late-env") else "allowed-executed" if case.endswith("-allow") else "denied"
            rows, witness, state = self.sample(case, outcome)
            with self.subTest(case=case):
                result = probe.assess(case, rows, witness, state, 0, True)
                self.assertEqual(result["outcome"], outcome)
                self.assertEqual(result["measurement"], "PASS")

    def test_late_execution_is_reported_not_mislabelled_as_denial(self) -> None:
        for mode in ("permission", "policy"):
            for variant in ("late-tool", "late-shell"):
                case = f"{mode}-{variant}"
                rows, witness, state = self.sample(case, "denied-command-executed")
                self.assertEqual(probe.assess(case, rows, witness, state, 0, True)["outcome"], "denied-command-executed")

    def test_startup_absence_is_not_invented_as_a_denial(self) -> None:
        for mode in ("permission", "policy"):
            case = f"{mode}-late-env"
            rows, witness, state = self.sample(case, "startup-not-observed")
            self.assertEqual(probe.assess(case, rows, witness, state, 0, True)["outcome"], "startup-not-observed")
            for index, field in ((5, "startupAbsent"), (6, "shellMatches"), (6, "startupMatches"), (6, "directoryMatches")):
                changed = copy.deepcopy(rows)
                changed[index][field] = False
                reason = "startup_observation_incomplete" if index == 5 else "late_shell_observation_incomplete"
                with self.subTest(mode=mode, field=field), self.assertRaisesRegex(probe.ProbeFailure, reason):
                    probe.assess(case, changed, witness, state, 0, True)
            state.tool_outcome["allowed_marker"] = False
            with self.assertRaisesRegex(probe.ProbeFailure, "startup_outcome_ambiguous"):
                probe.assess(case, rows, witness, state, 0, True)

    def test_provider_reports_only_fixed_denial_markers(self) -> None:
        state = probe.ProviderState(Path("/owned"), "synthetic", dispatched=1)
        state.response({"messages": [{"role": "tool", "tool_call_id": probe.CALL_ID, "content": "Permission denied: read SECRET_CANARY"}]})
        self.assertFalse(state.tool_outcome["permission_denied"])
        self.assertNotIn("SECRET_CANARY", json.dumps(state.tool_outcome))

    def test_controls_reject_wrong_outcomes_and_ambiguous_denials(self) -> None:
        for case, outcome in (("permission-allow", "denied"), ("policy-direct", "denied-command-executed"), ("policy-late-shell", "allowed-executed")):
            rows, witness, state = self.sample(case, outcome)
            with self.subTest(case=case), self.assertRaisesRegex(probe.ProbeFailure, "denial_control_mismatch"):
                probe.assess(case, rows, witness, state, 0, True)
        for markers in ((False, False), (True, True), (False, True)):
            rows, witness, state = self.sample("permission-direct", "denied")
            state.tool_outcome["permission_denied"], state.tool_outcome["policy_denied"] = markers
            with self.subTest(markers=markers), self.assertRaisesRegex(probe.ProbeFailure, "denial_outcome_ambiguous"):
                probe.assess("permission-direct", rows, witness, state, 0, True)

    def test_missing_or_forged_evidence_fails_closed(self) -> None:
        case = "policy-late-shell"
        rows, witness, state = self.sample(case, "denied")
        changes = (
            (lambda r: r.pop(6), "denial_observation_count_mismatch"),
            (lambda r: r.append(copy.deepcopy(r[6])), "denial_observation_count_mismatch"),
            (lambda r: r.__setitem__(slice(5, 7), [r[6], r[5]]), "denial_hook_order_mismatch"),
            (lambda r: r[2].pop("phase"), "trace_phase_invalid"),
            (lambda r: r.append(r.pop(2)), "native_shell_definition_unidentified"),
            (lambda r: r[2].__setitem__("shape", "not-a-definition"), "native_shell_definition_unidentified"),
            (lambda r: r[3].__setitem__("identity", None), "native_before_identity_missing"),
            (lambda r: r[5].__setitem__("directoryMatches", False), "shell_observation_mismatch"),
            (lambda r: r[6].__setitem__("command", "allowed"), "denial_command_observation_mismatch"),
            (lambda r: r[7].__setitem__("identity", {}), "after_observation_incomplete"),
            (lambda r: r[8].__setitem__("status", "completed"), "after_observation_incomplete"),
        )
        for change, reason in changes:
            altered = copy.deepcopy(rows)
            change(altered)
            with self.subTest(reason=reason), self.assertRaisesRegex(probe.ProbeFailure, reason):
                probe.assess(case, altered, witness, state, 0, True)
        for attribute, value in (("schema_sha256", None), ("continued", False), ("requests", 3)):
            bad_state = copy.copy(state)
            setattr(bad_state, attribute, value)
            with self.subTest(attribute=attribute), self.assertRaisesRegex(probe.ProbeFailure, "native_run_incomplete"):
                probe.assess(case, rows, witness, bad_state, 0, True)


if __name__ == "__main__":
    unittest.main()
