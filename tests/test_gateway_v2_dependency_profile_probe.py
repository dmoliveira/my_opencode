from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gateway_v2_dependency_profile_probe as profile


def sample_request() -> dict:
    return {"messages": [], "tools": [{"function": {"name": "shell", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}}]}


def state(case: str = "baseline", root: Path = Path("/unit-owned")) -> profile.ProfileState:
    return profile.ProfileState(case, root, time.monotonic() + 5)


def evidence() -> tuple[dict, list[dict]]:
    identity = {"sessionID": "unit-session", "messageID": "unit-message", "id": profile.CALL_ID, "agent": "build"}
    control = {"session_id": "unit-session", "foreign_session_id": "unit-foreign", "outcome": "succeeded", "terminal_tool_states": [{**identity, "name": "shell", "status": "completed"}], "ownership": {"expected_pid": 12345, "observed_pid": 12345}, "loader_checked": True, "wait_completed": True, "owner_id": "unit-owner", "inventory": [{"id": "profile-owned", "source": "owned", "status": "active"}], "admission": {"admitted": True, "reason": "owned-exclusive-ready"}}
    rows = [
        {"phase": "setup", "version": "2.2.5"},
        {"phase": "native.wrapped", "nativeID": "shell", "executeType": "function"},
        {"phase": "ready"},
        {"phase": "before", "identity": {**identity}, "tool": "shell", "command": "baseline"},
        {"phase": "executor.entry", "identity": {**identity}, "live": True, "command": "baseline"},
        {"phase": "shell.entry", "cwdMatches": True, "shellMatches": True, "command": "baseline"},
        {"phase": "shell.binding", "command": "baseline", "matches": {"cwd": True, "shell": True, "env": True}},
        {"phase": "permission", "sessionID": identity["sessionID"], "action": "shell", "source": {"type": "tool", "id": profile.CALL_ID, "messageID": identity["messageID"]}, "resources": ["baseline"]},
        {"phase": "raw", "identity": {**identity}, "exit": 0},
        {"phase": "after.entry", "identity": {**identity}, "status": "completed", "pending": True},
        {"phase": "after.continue", "identity": {**identity}, "pending": True},
    ]
    rows = [{**row, "owner": "unit-owner", "epoch": 1} for row in rows]
    return control, rows


def row_named(rows: list[dict], name: str) -> dict:
    return next(row for row in rows if row["phase"] == name)


class ProfileProbeTests(unittest.TestCase):
    def test_finite_matrix_and_no_authority_switch(self) -> None:
        self.assertEqual(len(profile.CASES), 18)
        self.assertEqual(len(set(profile.CASES)), 18)
        self.assertEqual(profile.AUTHORITY, "disabled-unqualified")
        self.assertNotIn("createDependencyRiskGuardHook", profile.PLUGIN)
        self.assertNotIn("capability", profile.PLUGIN)
        self.assertIn("return execute(input, context)", profile.PLUGIN)
        self.assertIn('import { Error as ToolError } from "@opencode/plugin/promise/tool"', profile.PLUGIN)
        self.assertNotIn('import { Tool } from "@opencode/plugin"', profile.PLUGIN)
        self.assertNotIn("editor.add", profile.PLUGIN)

    def test_barrier_timeout_is_not_success(self) -> None:
        barrier = profile.Barrier()
        with self.assertRaisesRegex(profile.ProbeFailure, "barrier_timeout"):
            barrier.hold(time.monotonic() - 1, threading.Event())
        self.assertTrue(barrier.arrived.is_set())

    def test_stop_releases_every_barrier(self) -> None:
        current = state()
        current.stop()
        for barrier in (current.model, current.callback, current.control):
            self.assertTrue(barrier.released.is_set())
            with self.assertRaisesRegex(profile.ProbeFailure, "controller_stopped"):
                barrier.hold(current.deadline, current.stopped)

    def test_model_hold_does_not_hold_state_lock(self) -> None:
        current = state("captured-dispose")
        result = []
        worker = threading.Thread(target=lambda: result.append(current.answer(sample_request())))
        worker.start()
        try:
            self.assertTrue(current.model.arrived.wait(1))
            self.assertTrue(current.lock.acquire(timeout=0.1))
            current.lock.release()
            current.model.release()
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result[0][1], "tool_calls")
        finally:
            current.stop()
            worker.join(1)

    def test_provider_requires_real_correlated_continuation(self) -> None:
        current = state()
        current.answer(sample_request())
        with self.assertRaisesRegex(profile.ProbeFailure, "tool_correlation_failed"):
            current.answer({"messages": [{"role": "tool", "tool_call_id": "unrelated"}]})
        self.assertFalse(current.continued)
        delta, reason = current.answer({"messages": [{"role": "tool", "tool_call_id": profile.CALL_ID, "content": "PROFILE_BASELINE"}]})
        self.assertEqual((delta["content"], reason), ("PROFILE_FINISHED", "stop"))
        self.assertTrue(current.consumer["baseline"])

    def test_provider_limits_and_schema_fail_closed(self) -> None:
        current = state()
        with self.assertRaisesRegex(profile.ProbeFailure, "native_shell_missing"):
            current.answer({})
        current.requests = profile.MAX_CONNECTIONS
        with self.assertRaisesRegex(profile.ProbeFailure, "provider_request_limit"):
            current.answer(sample_request())

    def test_fixture_uses_native_sdk_only_and_tripwires_are_not_invoked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = profile.prepare_fixture(root, state(root=root), 12345)
            self.assertIn('@opencode/plugin/effect', (root / "project/owned/index.ts").read_text())
            self.assertIn('"\n"'.replace("\n", "\\n"), (root / "project/rogue/index.ts").read_text())
            self.assertEqual(config["providers"]["profile"]["settings"]["baseURL"], "http://127.0.0.1:12345/v1")
            self.assertFalse((root / "installer-requested").exists())
            for manager in profile.MANAGERS:
                self.assertTrue((root / "bin" / manager).is_file())
            self.assertTrue(all(rule["effect"] == "deny" for rule in config["permissions"] if rule["action"] == "*"))

    def test_native_plugin_policy_is_path_scoped_not_an_identity_claim(self) -> None:
        root = Path("/unit-owned")
        config = profile.make_config(root, 12345, "rogue-blocked")
        rules = [rule for rule in config["policies"] if rule["action"] == "plugin.use"]
        self.assertEqual(rules[0], {"action": "plugin.use", "resource": "*", "effect": "deny"})
        self.assertEqual(rules[-1]["resource"], "/unit-owned/project/owned")
        control = profile.make_config(root, 12345, "rogue-unrestricted-control")
        self.assertFalse(any(rule["action"] == "plugin.use" for rule in control["policies"]))

    def test_owned_rewrite_is_atomic_and_private(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile.prepare_fixture(root, state(root=root), 12345)
            profile.rewrite_config(root, {"plugins": []})
            self.assertEqual(json.loads((root / "project/opencode.json").read_text()), {"plugins": []})
            self.assertEqual((root / "project/opencode.json").stat().st_mode & 0o777, 0o600)
            self.assertFalse((root / "replacement-config.json").exists())

    def test_identifier_cannot_inject_api_paths(self) -> None:
        for value in ("../../other", "with/slash", "\nsecret", None, "x" * 161):
            with self.assertRaisesRegex(profile.ProbeFailure, "native_identifier_invalid"):
                profile.native_id(value)
        self.assertEqual(profile.native_id("ses_unit-1"), "ses_unit-1")

    def test_terminal_history_uses_native_content_not_guessed_parts(self) -> None:
        context = {"data": [{"id": "unit-message", "type": "assistant", "content": [{"type": "tool", "id": profile.CALL_ID, "name": "shell", "state": {"status": "error"}}]}]}
        self.assertEqual(profile.terminal_tools(context, "unit-session")[0]["status"], "error")
        context["data"][0]["parts"] = context["data"][0].pop("content")
        with self.assertRaisesRegex(profile.ProbeFailure, "native_terminal_tool_missing"):
            profile.terminal_tools(context, "unit-session")

    def test_streaming_or_uncorrelated_history_is_not_terminal(self) -> None:
        for tool_id, status in (("unrelated", "completed"), (profile.CALL_ID, "running")):
            context = {"data": [{"id": "unit-message", "type": "assistant", "content": [{"type": "tool", "id": tool_id, "name": "shell", "state": {"status": status}}]}]}
            with self.assertRaisesRegex(profile.ProbeFailure, "native_terminal_tool_invalid"):
                profile.terminal_tools(context, "unit-session")

    def test_complete_counterexample_is_distinct_from_missing_collection(self) -> None:
        current = state()
        current.dispatched, current.schema = 1, {"type": "object"}
        current.continued, current.consumer = True, {"baseline": True}
        control, rows = evidence()
        passed, violations = profile.assess(current, control, rows, "WRONG_WITNESS")
        self.assertFalse(passed)
        self.assertIn("native-raw-baseline", violations)
        with self.assertRaises(profile.ProbeFailure):
            profile.assess(current, control, [], None)

    def test_identity_and_final_history_must_correlate(self) -> None:
        current = state()
        current.dispatched, current.schema = 1, {"type": "object"}
        current.continued, current.consumer = True, {"baseline": True}
        control, rows = evidence()
        control["terminal_tool_states"][0]["messageID"] = "wrong-message"
        with self.assertRaisesRegex(profile.ProbeFailure, "native_terminal_identity_mismatch"):
            profile.assess(current, control, rows, "PROFILE_BASELINE")

    def test_expected_predispatch_refusal_does_not_invent_native_ids(self) -> None:
        current = state("owned-missing")
        control = {"refused": True, "ownership": {"expected_pid": 12345, "observed_pid": 12345}, "loader_checked": True, "inventory": [], "admission": {"admitted": False, "reason": "owned-unavailable"}}
        self.assertEqual(profile.assess(current, control, [], None), (True, []))
        current.dispatched = 1
        passed, violations = profile.assess(current, control, [], None)
        self.assertFalse(passed)
        self.assertIn("pre-dispatch-refusal", violations)

    def test_tolerated_failure_must_revoke_before_continuation(self) -> None:
        current = state("after-tolerated")
        current.dispatched, current.schema = 1, {"type": "object"}
        current.continued, current.consumer = True, {"baseline": True}
        control, rows = evidence()
        identity = row_named(rows, "executor.entry")["identity"]
        rows.insert(-1, {"phase": "revoked", "identity": identity, "targetPending": False, "foreignPending": True, "foreignSessionID": "unit-foreign", "owner": "unit-owner", "epoch": 1})
        passed, violations = profile.assess(current, control, rows, "PROFILE_BASELINE")
        self.assertFalse(passed)
        self.assertIn("tolerated-continuation-before-revocation", violations)

    def test_missing_post_shell_permission_is_collection_failure(self) -> None:
        current = state("permission-after-shell")
        current.dispatched, current.schema = 1, {"type": "object"}
        current.continued, current.consumer = True, {"baseline": True}
        control, rows = evidence()
        rows = [row for row in rows if row["phase"] != "permission"]
        with self.assertRaisesRegex(profile.ProbeFailure, "post-shell-native-permission-missing"):
            profile.assess(current, control, rows, None)

    def test_captured_wrapper_cannot_delegate_after_close(self) -> None:
        current = state("captured-dispose")
        current.dispatched, current.schema = 1, {"type": "object"}
        current.continued, current.consumer = True, {"closed": True}
        control, rows = evidence()
        entry = row_named(rows, "executor.entry")
        entry.update({"live": False, "epoch": 2})
        rows = rows[:3] + [
            {"phase": "owner.closed", "owner": "unit-owner", "epoch": 2, "why": "explicit-disposal", "pendingCount": 0},
            {"phase": "registrations.disposed", "owner": "unit-owner", "epoch": 2}, entry,
        ]
        current.controller_notes.append("closed-before-model-release")
        passed, violations = profile.assess(current, control, rows, "PROFILE_BASELINE")
        self.assertFalse(passed)
        self.assertIn("captured-executor-revocation", violations)
        control["terminal_tool_states"][0]["status"] = "error"
        self.assertEqual(profile.assess(current, control, rows, None), (True, []))

    def test_no_api_mutation_before_pid_verification(self) -> None:
        runtime = object.__new__(profile.PrivateRuntime)
        runtime.verified = False
        with self.assertRaisesRegex(profile.ProbeFailure, "runtime_owner_unverified"):
            runtime.request("POST", "/api/session", {})

    def test_pid_mismatch_does_not_become_readiness(self) -> None:
        runtime = object.__new__(profile.PrivateRuntime)
        runtime.process = MagicMock(pid=12345)
        runtime.request = MagicMock(return_value={"pid": 99999})
        runtime.verified = False
        with self.assertRaisesRegex(profile.ProbeFailure, "runtime_pid_mismatch"):
            runtime.verify_owner()
        self.assertFalse(runtime.verified)

    def test_each_mutation_verifies_owned_server_first(self) -> None:
        runtime = object.__new__(profile.PrivateRuntime)
        calls = []
        runtime.verify_owner = lambda: calls.append("verify")
        runtime.request = lambda *args: calls.append("mutate")
        runtime.mutate("POST", "/api/location/reload")
        self.assertEqual(calls, ["verify", "mutate"])

    def test_reader_output_is_capped_during_execution(self) -> None:
        runtime = object.__new__(profile.PrivateRuntime)
        runtime.reader_stop = threading.Event()
        runtime.output = [bytearray(), bytearray()]
        runtime.fault = None
        read_fd, write_fd = os.pipe()
        stream = os.fdopen(read_fd, "rb")
        writer = threading.Thread(target=lambda: (os.write(write_fd, b"x" * 8192), os.close(write_fd)))
        writer.start()
        try:
            with patch.object(profile, "MAX_OUTPUT", 32):
                runtime._read(stream, 0)
            self.assertEqual(len(runtime.output[0]), 32)
            self.assertEqual(runtime.fault, "runtime_output_limit")
        finally:
            stream.close()
            writer.join(1)

    def test_partial_headers_and_unreleased_control_are_closed(self) -> None:
        current = state()
        server = profile.ProfileProvider(current)
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        worker.start()
        client = socket.create_connection(server.server_address, timeout=1)
        client.sendall(b"POST /v1/chat/completions HTTP/1.1\r\nX-Incomplete: ")
        try:
            deadline = time.monotonic() + 1
            while not server.admitted and time.monotonic() < deadline:
                threading.Event().wait(0.01)
            current.stop()
            server.shutdown()
            server.close_connections()
            server.server_close()
            worker.join(1)
            for handler in server.workers:
                handler.join(1)
            self.assertFalse(worker.is_alive())
            self.assertTrue(all(not handler.is_alive() for handler in server.workers))
        finally:
            client.close()
            if worker.is_alive():
                current.stop(); server.shutdown(); server.close_connections(); server.server_close(); worker.join(1)

    def test_wrong_host_stops_before_native_cases_and_hides_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary);binary = parent / "fake-opencode";binary.write_bytes(b"unit-binary")
            with patch.object(profile, "run_child", return_value=(0, b"opencode v9.9.9\n", b"SECRET_CANARY")), patch.object(profile, "run_case") as run:
                result = profile.probe(str(binary), parent)
            self.assertEqual(result["reason"], "unsupported_host_version")
            self.assertEqual(result["authority"], "disabled-unqualified")
            self.assertNotIn("SECRET_CANARY", json.dumps(result))
            run.assert_not_called()

    def test_all_required_cases_and_only_complete_witnesses_qualify(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary);binary = parent / "fake-opencode";binary.write_bytes(b"unit-binary")
            child = (0, b"opencode v2.2.5\n", b"")
            with patch.object(profile, "run_child", return_value=child), patch.object(profile, "run_case", side_effect=lambda b, p, case: {"case": case, "measurement": "PASS", "witnesses_pass": True, "cleanup_complete": True}):
                result = profile.probe(str(binary), parent)
            self.assertEqual((result["measurement"], result["profile_qualification"], result["authority"]), ("PASS", "QUALIFIED", "disabled-unqualified"))
            with patch.object(profile, "run_child", return_value=child), patch.object(profile, "run_case", return_value={"case": "unit", "measurement": "PASS", "witnesses_pass": False, "cleanup_complete": True}):
                result = profile.probe(str(binary), parent)
            self.assertEqual((result["measurement"], result["profile_qualification"]), ("PASS", "UNQUALIFIED"))

    def test_debug_subset_cannot_claim_required_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary);binary = parent / "fake-opencode";binary.write_bytes(b"unit-binary")
            with patch.object(profile, "run_child", return_value=(0, b"opencode v2.2.5\n", b"")), patch.object(profile, "run_case", return_value={"measurement": "PASS", "witnesses_pass": True, "cleanup_complete": True}):
                result = profile.probe(str(binary), parent, ("baseline",))
            self.assertEqual(result["reason"], "incomplete_case_selection")
            self.assertEqual(result["profile_qualification"], "UNQUALIFIED")

    def test_invalid_selections_are_rejected_before_any_child(self) -> None:
        for selection in ((), ("baseline", "baseline"), ("baseline",) * 100, ("unknown",)):
            with patch.object(profile, "run_child") as child, patch.object(profile, "run_case") as case:
                result = profile.probe("/not-executed", Path("/not-created"), selection)
            self.assertEqual(result["reason"], "invalid_case_selection")
            child.assert_not_called();case.assert_not_called()

    def test_reader_startup_failure_retains_process_handle_for_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = profile.PrivateRuntime("/not-executed", Path(temporary), time.monotonic() + 1)
            process = MagicMock()
            with patch.object(profile.subprocess, "Popen", return_value=process), patch.object(profile.threading, "Thread") as thread, patch.object(profile, "stop_group") as stop:
                thread.return_value.start.side_effect = RuntimeError("injected startup failure")
                with self.assertRaises(RuntimeError):
                    runtime.start()
                self.assertIs(runtime.process, process)
                runtime.close(time.monotonic() + 1)
                stop.assert_called_once_with(process)

    def test_unstarted_provider_is_never_shutdown_or_joined(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            provider = MagicMock(workers=[], admissions=0)
            timer = MagicMock(ident=None);timer.is_alive.return_value = False
            with patch.object(profile, "ProfileProvider", return_value=provider), patch.object(profile.threading, "Timer", return_value=timer), patch.object(profile.threading, "Thread") as thread:
                thread.return_value.start.side_effect = RuntimeError("injected startup failure")
                result = profile.run_case("/not-executed", Path(temporary), "baseline")
            provider.shutdown.assert_not_called()
            thread.return_value.join.assert_not_called()
            provider.server_close.assert_called_once()
            self.assertEqual(result["measurement"], "FAIL")
            self.assertTrue(result["cleanup_complete"])

    def test_watchdog_cancels_active_controller_connections(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cancelled = threading.Event()
            controller_entered = threading.Event()
            runtime = MagicMock()
            runtime.abort_connections.side_effect = cancelled.set
            real_timer = threading.Timer

            def blocked_controller(*args: object) -> None:
                controller_entered.set()
                self.assertTrue(cancelled.wait(3))
                raise profile.ProbeFailure("cancelled_controller")

            def coordinated_timer(_delay: float, expire: Callable[[], None]) -> threading.Timer:
                def fire() -> None:
                    if controller_entered.wait(3):
                        expire()
                return real_timer(0, fire)

            with patch.object(profile, "PRIMARY_SECONDS", 10), patch.object(profile.threading, "Timer", side_effect=coordinated_timer), patch.object(profile, "PrivateRuntime", return_value=runtime), patch.object(profile, "control_case", side_effect=blocked_controller):
                result = profile.run_case("/not-executed", Path(temporary), "baseline")
            self.assertEqual(result["reason"], "case_timeout")
            runtime.abort_connections.assert_called_once()
            runtime.close.assert_called_once()
            self.assertTrue(result["cleanup_complete"])

    def test_expiry_during_fixture_setup_does_not_start_a_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            def slow_fixture(_root: Path, current: profile.ProfileState, _port: int) -> dict:
                self.assertTrue(current.stopped.wait(3))
                return {}

            with patch.object(profile, "PRIMARY_SECONDS", 0.02), patch.object(profile, "prepare_fixture", side_effect=slow_fixture), patch.object(profile, "PrivateRuntime") as runtime:
                result = profile.run_case("/not-executed", Path(temporary), "baseline")
            self.assertEqual(result["reason"], "case_timeout")
            self.assertTrue(result["cleanup_complete"])
            runtime.assert_not_called()

    def test_expired_or_cancelled_runtime_never_spawns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            for expired in (True, False):
                with self.subTest(expired=expired):
                    deadline = time.monotonic() + (-1 if expired else 10)
                    runtime = profile.PrivateRuntime("/not-executed", Path(temporary), deadline)
                    if not expired:
                        runtime.cancelled.set()
                    with patch.object(profile.subprocess, "Popen") as spawn:
                        with self.assertRaisesRegex(profile.ProbeFailure, "case_timeout"):
                            runtime.start()
                        spawn.assert_not_called()

            runtime = profile.PrivateRuntime("/not-executed", Path(temporary), time.monotonic() + 10)
            def cancelled_during_environment(_root: Path) -> dict:
                runtime.cancelled.set()
                return {}
            with patch.object(profile, "child_env", side_effect=cancelled_during_environment), patch.object(profile.subprocess, "Popen") as spawn:
                with self.assertRaisesRegex(profile.ProbeFailure, "case_timeout"):
                    runtime.start()
                spawn.assert_not_called()

    def test_abort_interrupts_partial_native_response_headers(self) -> None:
        with socket.socket() as server, tempfile.TemporaryDirectory() as temporary:
            server.bind(("127.0.0.1", 0));server.listen(1);server.settimeout(1)
            runtime = profile.PrivateRuntime("/not-executed", Path(temporary), time.monotonic() + 1)
            runtime.port = server.getsockname()[1]
            accepted = threading.Event()

            def incomplete() -> None:
                connection, _ = server.accept()
                with connection:
                    connection.settimeout(1)
                    connection.recv(4096)
                    connection.sendall(b"HTTP/1.1 200 OK\r\nX-Incomplete: ")
                    accepted.set()
                    try:
                        connection.recv(4096)
                    except OSError:
                        pass

            worker = threading.Thread(target=incomplete);worker.start()
            timer = threading.Timer(0.03, runtime.abort_connections);timer.start()
            try:
                with self.assertRaises((OSError, profile.http.client.HTTPException, profile.ProbeFailure)):
                    runtime.request("GET", "/api/info")
                self.assertTrue(accepted.is_set())
            finally:
                timer.cancel();timer.join(1);runtime.abort_connections();worker.join(1)
            self.assertFalse(worker.is_alive())

    def test_late_reader_fault_prevents_measurement_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = profile.PrivateRuntime("/not-executed", Path(temporary), time.monotonic() + 1)
            runtime.fault = "runtime_output_limit"
            with self.assertRaisesRegex(profile.ProbeFailure, "runtime_output_limit"):
                runtime.close(time.monotonic() + 1)

    def test_foreign_or_replaced_fixture_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = root.lstat()
            self.assertTrue(profile.owned_fixture(root, identity))
            with patch.object(profile.os, "getuid", return_value=identity.st_uid + 1):
                self.assertFalse(profile.owned_fixture(root, identity))
            (root / "foreign-link").symlink_to("/not-followed")
            self.assertFalse(profile.owned_fixture(root, identity))

    def test_missing_required_baseline_observations_fail_collection(self) -> None:
        for name in ("native.wrapped", "before", "shell.entry", "shell.binding", "permission", "raw", "after.entry", "after.continue"):
            current = state();current.dispatched = 1;current.schema = {"type": "object"};current.continued = True;current.consumer = {"baseline": True}
            control, rows = evidence()
            with self.subTest(name=name), self.assertRaises(profile.ProbeFailure):
                profile.assess(current, control, [row for row in rows if row["phase"] != name], "PROFILE_BASELINE")

    def test_replayed_tool_transforms_are_not_duplicate_native_calls(self) -> None:
        current = state();current.dispatched = 1;current.schema = {"type": "object"};current.continued = True;current.consumer = {"baseline": True}
        control, rows = evidence();definition = row_named(rows, "native.wrapped")
        rows.insert(rows.index(definition) + 1, dict(definition))
        self.assertEqual(profile.assess(current, control, rows, "PROFILE_BASELINE"), (True, []))
        invalid = dict(definition);invalid["nativeID"] = "replacement-tool";rows.insert(2, invalid)
        with self.assertRaisesRegex(profile.ProbeFailure, "native_wrapper_collection_missing"):
            profile.assess(current, control, rows, "PROFILE_BASELINE")

    def test_replayed_definition_from_another_owner_cannot_qualify(self) -> None:
        current = state();current.dispatched = 1;current.schema = {"type": "object"};current.continued = True;current.consumer = {"baseline": True}
        control, rows = evidence();definition = dict(row_named(rows, "native.wrapped"));definition["owner"] = "other-owner"
        rows.insert(2, definition)
        passed, violations = profile.assess(current, control, rows, "PROFILE_BASELINE")
        self.assertFalse(passed)
        self.assertIn("native-definition-owner", violations)
        definition["nativeID"] = "other-tool"
        with self.assertRaisesRegex(profile.ProbeFailure, "native_wrapper_collection_missing"):
            profile.assess(current, control, rows, "PROFILE_BASELINE")

    def test_native_session_outcome_allowlist_rejects_nested_or_private_data(self) -> None:
        for value in (None, 0, True, {"outcome": "succeeded", "secret": "SECRET_CANARY"}, ["failed"], "SECRET_CANARY"):
            with self.subTest(value=type(value)), self.assertRaisesRegex(profile.ProbeFailure, "native_outcome_invalid") as caught:
                profile.native_outcome(value)
            self.assertNotIn("SECRET_CANARY", str(caught.exception))
        for value in ("succeeded", "failed", "interrupted"):
            self.assertEqual(profile.native_outcome(value), value)

    def test_replayed_definition_does_not_excuse_duplicate_native_execution(self) -> None:
        current = state();current.dispatched = 1;current.schema = {"type": "object"};current.continued = True;current.consumer = {"baseline": True}
        control, rows = evidence();entry = row_named(rows, "executor.entry")
        rows.insert(rows.index(entry) + 1, dict(entry))
        with self.assertRaisesRegex(profile.ProbeFailure, "required_observation_missing:executor.entry"):
            profile.assess(current, control, rows, "PROFILE_BASELINE")

    def test_missing_or_non_numeric_raw_exit_is_collection_failure(self) -> None:
        for exit_value in (None, True, "0", float("nan")):
            current = state();current.dispatched = 1;current.schema = {"type": "object"};current.continued = True;current.consumer = {"baseline": True}
            control, rows = evidence();row_named(rows, "raw")["exit"] = exit_value
            with self.assertRaisesRegex(profile.ProbeFailure, "native_numeric_exit_collection_missing"):
                profile.assess(current, control, rows, "PROFILE_BASELINE")

    def test_raw_identity_cannot_be_borrowed(self) -> None:
        current = state();current.dispatched = 1;current.schema = {"type": "object"};current.continued = True;current.consumer = {"baseline": True}
        control, rows = evidence();row_named(rows, "raw")["identity"] = {"id": "wrong-call"}
        with self.assertRaises(profile.ProbeFailure):
            profile.assess(current, control, rows, "PROFILE_BASELINE")

    def test_complete_binding_permission_and_generation_contradictions_do_not_qualify(self) -> None:
        def changed_env(rows: list[dict]) -> None:
            row_named(rows, "shell.binding")["matches"]["env"] = False

        def changed_command(rows: list[dict]) -> None:
            row_named(rows, "shell.binding")["command"] = "changed"

        def wrong_source(rows: list[dict]) -> None:
            row_named(rows, "permission")["source"]["type"] = "command"

        def early_permission(rows: list[dict]) -> None:
            permission = row_named(rows, "permission");rows.remove(permission);rows.insert(0, permission)

        def wrong_generation(rows: list[dict]) -> None:
            row_named(rows, "raw")["epoch"] = 2

        for mutate in (changed_env, changed_command, wrong_source, early_permission, wrong_generation):
            current = state();current.dispatched = 1;current.schema = {"type": "object"};current.continued = True;current.consumer = {"baseline": True}
            control, rows = evidence();mutate(rows)
            with self.subTest(mutation=mutate.__name__):
                passed, violations = profile.assess(current, control, rows, "PROFILE_BASELINE")
                self.assertFalse(passed);self.assertTrue(violations)

    def test_plugin_mutable_ownership_is_per_effect_instance(self) -> None:
        entry = profile.PLUGIN.index('effect: ctx => Effect.gen(function* () {')
        for declaration in ("const owner =", "const pending =", "let sequence =", "const emit =", "const revoke =", "const closeOwner ="):
            self.assertGreater(profile.PLUGIN.index(declaration), entry)

    def test_loader_activation_barrier_precedes_fresh_inventory(self) -> None:
        runtime = MagicMock();calls = []
        runtime.request.side_effect = lambda method, path: calls.append((method, path))

        def listed(*args: object) -> list:
            self.assertEqual(calls[0][0], "GET")
            self.assertTrue(calls[0][1].startswith("/api/agent?location%5Bdirectory%5D="))
            calls.append(("GET", "fresh-inventory"));return []

        with patch.object(profile, "plugin_list", side_effect=listed):
            result = profile.control_case(Path("/unit-owned"), state("owned-missing"), runtime, {"plugins": []})
        self.assertEqual(len(calls), 2)
        self.assertTrue(result["refused"])
        runtime.mutate.assert_not_called()

    def test_readiness_retries_bootstrap_503_but_not_other_failures(self) -> None:
        runtime = object.__new__(profile.PrivateRuntime);runtime.deadline = time.monotonic() + 5
        runtime.verify_owner = MagicMock(side_effect=[profile.ProbeFailure("native_api_status_503"), None])
        with patch.object(profile.threading, "Event"):
            runtime.ready()
        self.assertEqual(runtime.verify_owner.call_count, 2)
        for reason in ("native_api_status_401", "runtime_pid_mismatch"):
            runtime.verify_owner = MagicMock(side_effect=profile.ProbeFailure(reason))
            with self.assertRaisesRegex(profile.ProbeFailure, reason):
                runtime.ready()
            runtime.verify_owner.assert_called_once()

    def test_persistent_bootstrap_503_has_finite_readiness_deadline(self) -> None:
        runtime = object.__new__(profile.PrivateRuntime);runtime.deadline = time.monotonic() + 0.02
        runtime.verify_owner = MagicMock(side_effect=profile.ProbeFailure("native_api_status_503"))
        with self.assertRaisesRegex(profile.ProbeFailure, "runtime_readiness_timeout"):
            runtime.ready()
        self.assertLessEqual(runtime.verify_owner.call_count, 2)

    def test_witness_absence_is_distinct_from_invalid_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);path = root / "witness"
            self.assertIsNone(profile.read_witness(path))
            path.write_text("PROFILE_BASELINE")
            self.assertEqual(profile.read_witness(path), "PROFILE_BASELINE")
            path.write_text("SECRET_CANARY")
            self.assertEqual(profile.read_witness(path), "unrecognized-witness")
            (root / "hardlink").hardlink_to(path)
            with self.assertRaisesRegex(profile.ProbeFailure, "witness_invalid"):
                profile.read_witness(path)
            path.unlink();path.symlink_to("missing")
            with self.assertRaisesRegex(profile.ProbeFailure, "witness_invalid"):
                profile.read_witness(path)
            path.unlink();path.mkdir()
            with self.assertRaisesRegex(profile.ProbeFailure, "witness_invalid"):
                profile.read_witness(path)
            path.rmdir();path.write_text("x" * 128)
            with self.assertRaisesRegex(profile.ProbeFailure, "witness_invalid"):
                profile.read_witness(path)

    def test_reload_awaits_replacement_activation_before_admission(self) -> None:
        root = Path("/unit-owned");runtime = MagicMock();rows = [{"phase": "ready", "owner": "old", "epoch": 1}];barriers = []
        item = {"id": "profile-owned", "source": {"type": "local", "path": str(root / "project/owned")}, "state": {"status": "active"}}

        def reloaded(method: str, path: str) -> None:
            self.assertEqual((method, path), ("POST", "/api/location/reload"))
            rows.append({"phase": "owner.closed", "owner": "old", "epoch": 2})

        def activated(method: str, path: str) -> None:
            self.assertTrue(path.startswith("/api/agent?"));barriers.append(path)
            if len(barriers) == 2:
                self.assertTrue(any(row["phase"] == "owner.closed" for row in rows))
                rows.append({"phase": "ready", "owner": "replacement", "epoch": 1})

        def listed(*args: object) -> list:
            self.assertEqual(len(barriers), 1 if len(rows) == 1 else 2)
            return [item]

        runtime.mutate.side_effect = reloaded;runtime.request.side_effect = activated
        with patch.object(profile, "traces", side_effect=lambda root: rows), patch.object(profile, "rewrite_config"), patch.object(profile, "plugin_list", side_effect=listed):
            result = profile.control_case(root, state("topology-change", root), runtime, {"plugins": [str(root / "project/owned")]})
        self.assertEqual(len(barriers), 2)
        self.assertEqual(result["admission"], {"admitted": False, "reason": "unexpected-plugin-topology"})
        self.assertTrue(result["refused"])

    def test_assessment_failure_preserves_collected_control_details(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = MagicMock(observed_pid=12345);runtime.process.pid = 12345
            control = {"admission": {"admitted": False, "reason": "measured-gate"}}
            with patch.object(profile, "PrivateRuntime", return_value=runtime), patch.object(profile, "control_case", return_value=control), patch.object(profile, "assess", side_effect=profile.ProbeFailure("collection-failed")):
                report = profile.run_case("/not-executed", Path(temporary), "topology-change")
            self.assertEqual(report["reason"], "collection-failed")
            self.assertEqual(report["control"]["admission"]["reason"], "measured-gate")

    def test_closed_entry_alone_is_not_captured_lifecycle_proof(self) -> None:
        current = state("captured-dispose");current.dispatched = 1;current.schema = {"type": "object"};current.continued = True;current.consumer = {"closed": True}
        control, rows = evidence();entry = row_named(rows, "executor.entry");entry["live"] = False
        with self.assertRaises(profile.ProbeFailure):
            profile.assess(current, control, [entry], None)

    def test_stale_completion_requires_real_fresh_reuse(self) -> None:
        current = state("stale-completion-reuse");current.dispatched = 2;current.schema = {"type": "object"}
        control, rows = evidence();identity = row_named(rows, "executor.entry")["identity"]
        control["outcome"] = "failed";control["terminal_tool_states"][0]["status"] = "error"
        rows.pop()
        rows += [
            {"phase": "after.suspended", "identity": identity, "owner": "unit-owner", "epoch": 1},
            {"phase": "owner.closed", "owner": "unit-owner", "epoch": 2, "why": "explicit-disposal", "pendingCount": 0},
            {"phase": "registrations.disposed", "owner": "unit-owner", "epoch": 2},
            {"phase": "stale.rejected", "identity": identity, "owner": "unit-owner", "epoch": 2, "pending": False},
            {"phase": "revoked", "identity": identity, "owner": "unit-owner", "epoch": 2, "targetPending": False, "foreignPending": False, "foreignSessionID": "unit-foreign"},
        ]
        with self.assertRaisesRegex(profile.ProbeFailure, "native_reuse_collection_missing"):
            profile.assess(current, control, rows, "PROFILE_BASELINE")
        current.reuse_started, current.reuse_continued = True, True;current.reuse_consumer = {"reuse": True}
        control["reuse"] = {"outcome": "succeeded", "witness": "PROFILE_REUSE", "terminal_tools": [{"sessionID": "unit-session", "messageID": "unit-message-reuse", "id": profile.REUSE_ID, "status": "completed"}]}
        passed, violations = profile.assess(current, control, rows, "PROFILE_BASELINE")
        self.assertFalse(passed)
        self.assertEqual(violations, ["fresh-executor-escaped-disposal-fence"])

    def test_provider_allows_exactly_two_distinct_native_attempts(self) -> None:
        current = state("stale-completion-reuse")
        first, _ = current.answer(sample_request())
        self.assertEqual(first["tool_calls"][0]["id"], profile.CALL_ID)
        current.reuse_started = True
        request = sample_request();request["messages"] = [{"role": "tool", "tool_call_id": profile.CALL_ID, "content": "first failure"}]
        second, _ = current.answer(request)
        self.assertEqual(second["tool_calls"][0]["id"], profile.REUSE_ID)
        self.assertIn("PROFILE_REUSE", second["tool_calls"][0]["function"]["arguments"])
        with self.assertRaisesRegex(profile.ProbeFailure, "unexpected_provider_request"):
            current.answer(request)


if __name__ == "__main__":
    unittest.main()
