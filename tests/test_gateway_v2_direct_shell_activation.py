from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

if os.name == "posix":
    sys.path.insert(
        0, str(Path(__file__).resolve().parents[1] / "plugin/gateway-core/test/v2")
    )
    import direct_shell_activation_live_smoke as probe


def complete_measurement() -> dict[str, object]:
    return {
        "host": "opencode v2.2.6",
        "first_response_created": True,
        "first_witness_before_plugin_ready": True,
        "configured_plugin_active": True,
        "second_response_created": True,
        "second_witness_after_plugin_ready": True,
        "post_activation_hook_seen": True,
        "post_activation_host_session_set": False,
        "post_activation_block_refused": True,
        "positive_witness_control": True,
        "blocked_witness_not_observed": True,
        "teardown_complete": True,
        "retained_fixture": "v2-direct-shell-synthetic",
    }


@contextmanager
def retained_directory() -> Iterator[Path]:
    yield Path(tempfile.mkdtemp(prefix="v2-direct-shell-unit-"))


@contextmanager
def controller_fixture() -> Iterator[tuple[object, object]]:
    state = probe.DirectState("test", Path("/synthetic"), time.monotonic() + 10)
    controller = probe.DirectController(state)
    thread = threading.Thread(
        target=controller.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        yield state, controller
    finally:
        state.stop()
        controller.shutdown()
        controller.close_connections()
        controller.server_close()
        for worker in controller.workers:
            worker.join(timeout=2)
            if worker.is_alive():
                raise AssertionError("controller worker did not settle")
        thread.join(timeout=2)
        if thread.is_alive():
            raise AssertionError("controller did not settle")


def request(
    port: int, method: str, path: str, key: str, body: bytes | None = None
) -> int:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request(method, path, body, {"Authorization": f"Bearer {key}"})
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


@unittest.skipUnless(os.name == "posix", "native shell probe is POSIX-only")
class DirectShellActivationTests(unittest.TestCase):
    def test_wait_keeps_runtime_leader_unreaped_until_group_cleanup(self) -> None:
        process = Mock()
        runtime = SimpleNamespace(process=process, deadline=time.monotonic() + 1)
        probe.wait_for(lambda: True, runtime, "not_observed")
        process.poll.assert_not_called()

    def test_direct_shell_requires_matching_successful_exit_and_output(self) -> None:
        command = "printf FIRST"
        cwd = Path("/private-owned-fixture")
        created = {"data": {"id": "shell_owned"}}
        info = {
            "id": "shell_owned",
            "command": command,
            "cwd": str(cwd),
            "shell": "/bin/sh",
        }
        status = {**info, "status": "exited", "exit": 0}
        output = {"output": "FIRST", "cursor": 5, "size": 5, "truncated": False}

        def api(_method: str, path: str) -> dict:
            return {"data": output if "/output?" in path else status}

        runtime = SimpleNamespace(request=Mock(side_effect=api))
        probe.wait_for_shell_exit(runtime, created, command, cwd, "FIRST")
        for update in (
            {"status": "timeout"},
            {"status": "exited", "exit": 1},
            {"status": "exited", "exit": False},
            {"status": "exited", "exit": 0, "id": "shell_other"},
            {"status": "exited", "exit": 0, "shell": "/other"},
        ):
            with self.subTest(update=update):
                runtime.request.side_effect = lambda _method, _path, change=update: {
                    "data": {**info, **change}
                }
                with self.assertRaises(probe.ProbeFailure):
                    probe.wait_for_shell_exit(runtime, created, command, cwd, "FIRST")
        for update in (
            {"output": "OTHER"},
            {"cursor": True},
            {"size": 6},
            {"truncated": True},
        ):
            with self.subTest(output=update):
                runtime.request.side_effect = lambda _method, path, change=update: {
                    "data": {**output, **change} if "/output?" in path else status
                }
                with self.assertRaises(probe.ProbeFailure):
                    probe.wait_for_shell_exit(runtime, created, command, cwd, "FIRST")

    def test_measurement_requires_all_observations_and_successful_cleanup(self) -> None:
        evidence = complete_measurement()
        self.assertTrue(probe.measured(evidence))
        for name in evidence:
            with self.subTest(missing=name):
                incomplete = dict(evidence)
                del incomplete[name]
                self.assertFalse(probe.measured(incomplete))
        for change in (
            {"host": "opencode v2.2.7"},
            {"post_activation_host_session_set": True},
            {"teardown_complete": False},
            {"retained_fixture": "../untrusted"},
            {"positive_witness_control": False},
            {"blocked_witness_not_observed": False},
            {"reason": "probe_failed"},
        ):
            with self.subTest(change=change):
                self.assertFalse(probe.measured({**evidence, **change}))

    def test_controller_requires_authentication_and_releases_gate(self) -> None:
        with controller_fixture() as (state, controller):
            self.assertNotEqual(state.control_key, state.witness_key)
            result: list[int] = []
            gate = threading.Thread(
                target=lambda: result.append(
                    request(controller.server_port, "GET", "/gate", state.control_key)
                ),
                daemon=True,
            )
            gate.start()
            self.assertTrue(state.control.arrived.wait(2))
            self.assertTrue(gate.is_alive())
            self.assertEqual(
                200,
                request(
                    controller.server_port,
                    "POST",
                    "/trace",
                    state.control_key,
                    json.dumps({"event": "setup"}).encode(),
                ),
            )
            state.control.release()
            gate.join(timeout=2)
            self.assertFalse(gate.is_alive())
            self.assertEqual([200], result)
            self.assertEqual(
                200,
                request(
                    controller.server_port,
                    "POST",
                    "/witness/positive",
                    state.witness_key,
                    b"",
                ),
            )
            self.assertEqual((["setup"], ["positive"]), probe.observations(state))

        for path, key in (("/trace", "wrong"), ("/witness/positive", "wrong")):
            with self.subTest(path=path), controller_fixture() as (state, controller):
                body = (
                    json.dumps({"event": "setup"}).encode() if path == "/trace" else b""
                )
                self.assertEqual(
                    400, request(controller.server_port, "POST", path, key, body)
                )
                self.assertIsNotNone(state.failure)
                self.assertEqual([], state.witnesses)

        with controller_fixture() as (state, controller):
            self.assertEqual(
                400, request(controller.server_port, "GET", "/gate", "wrong")
            )
            self.assertEqual("control_authentication_failed", state.failure)

    def test_blocked_witness_and_witness_overflow_are_detected(self) -> None:
        with controller_fixture() as (state, controller):
            for name in ("positive", "blocked"):
                self.assertEqual(
                    200,
                    request(
                        controller.server_port,
                        "POST",
                        f"/witness/{name}",
                        state.witness_key,
                        b"",
                    ),
                )
            self.assertTrue(state.blocked_seen.is_set())
            self.assertEqual(["positive", "blocked"], state.witnesses)
            self.assertEqual(
                400,
                request(
                    controller.server_port,
                    "POST",
                    "/witness/positive",
                    state.witness_key,
                    b"",
                ),
            )
            self.assertEqual("witness_limit", state.failure)
            with self.assertRaises(probe.ProbeFailure):
                probe.observations(state)

    def test_unexpected_trace_shapes_and_witness_commands_fail_closed(self) -> None:
        state = probe.DirectState("test", Path("/synthetic"), time.monotonic() + 10)
        for row in ({"event": "unknown"}, {"event": "setup", "extra": 1}, None):
            with self.subTest(row=row):
                state.trace_rows = [row]
                with self.assertRaises(probe.ProbeFailure):
                    probe.observations(state)
        with self.assertRaises(probe.ProbeFailure):
            probe.witness_command(1234, "synthetic", "other")
        for kind in ("positive", "blocked"):
            command = probe.witness_command(1234, "synthetic", kind)
            self.assertIn(f"/witness/{kind}", command)
            self.assertNotIn(" > ", command)

    def test_setup_failure_retains_fixture_without_recursive_removal(self) -> None:
        with retained_directory() as parent:
            with (
                patch.object(probe, "preflight"),
                patch.object(
                    probe, "prepare", side_effect=probe.ProbeFailure("setup_failed")
                ),
                patch.object(
                    probe.shutil,
                    "rmtree",
                    side_effect=AssertionError("unexpected deletion"),
                ),
            ):
                report = probe.run_probe("unused", parent)
            self.assertTrue(report["teardown_complete"])
            self.assertEqual(report["reason"], "setup_failed")
            self.assertEqual(report["result"], "FAIL")
            self.assertTrue((parent / report["retained_fixture"]).is_dir())

    def run_mock_measurement(
        self, *, created_blocked_shell: bool, owner_verification_fails: bool = False
    ) -> dict:
        with retained_directory() as parent:
            active: list[probe.DirectState] = []
            runtime = Mock()

            def prepare(
                _root: Path, _port: int, state: probe.DirectState, _cmd: str
            ) -> None:
                state.trace_rows.append({"event": "setup"})
                active.append(state)

            def wait(_predicate: object, _runtime: object, reason: str) -> None:
                if reason == "plugin_ready_not_observed":
                    active[0].trace_rows.append({"event": "ready"})

            def mutate(_method: str, _path: str, body: dict) -> dict:
                state = active[0]
                calls = runtime.mutate.call_count
                if calls > 1:
                    state.trace_rows.append({"event": "hook"})
                if calls == 3:
                    state.witnesses.append("positive")
                if calls == 4:
                    state.trace_rows.append({"event": "blocked"})
                    if not created_blocked_shell:
                        raise probe.ProbeFailure("native_api_status_500")
                return {"data": {"id": f"shell_{calls}"}}

            def shell_exit(
                _runtime: object, _response: object, command: str, *_args: object
            ) -> None:
                if created_blocked_shell and "/witness/blocked" in command:
                    raise probe.ProbeFailure("native_api_status_500")

            def verify_owner() -> None:
                if owner_verification_fails:
                    active[0].trace_rows.extend(
                        [{"event": "hook"}, {"event": "blocked"}]
                    )
                    raise probe.ProbeFailure("native_api_status_500")

            def request_native(
                method: str, _path: str, body: dict | None = None
            ) -> dict:
                if method == "POST":
                    active[0].trace_rows.extend(
                        [{"event": "hook"}, {"event": "blocked"}]
                    )
                    if not created_blocked_shell:
                        raise probe.ProbeFailure("native_api_status_500")
                    return {"data": {"id": "shell_4"}}
                return {}

            runtime.mutate.side_effect = mutate
            runtime.verify_owner.side_effect = verify_owner
            runtime.request.side_effect = request_native
            with (
                patch.object(probe, "preflight"),
                patch.object(probe, "prepare", side_effect=prepare),
                patch.object(
                    probe, "run_child", return_value=(0, b"opencode v2.2.6", b"")
                ),
                patch.object(probe, "PrivateRuntime", return_value=runtime),
                patch.object(probe, "wait_for", side_effect=wait),
                patch.object(probe, "wait_for_shell_exit", side_effect=shell_exit),
                patch.object(
                    probe,
                    "activated_inventory",
                    return_value=[{"source": "owned", "status": "active"}],
                ),
                patch.object(probe, "WITNESS_OBSERVATION_SECONDS", 0.001),
                patch.object(
                    probe.shutil,
                    "rmtree",
                    side_effect=AssertionError("unexpected deletion"),
                ),
            ):
                report = probe.run_probe("unused", parent)
            self.assertTrue((parent / report["retained_fixture"]).is_dir())
            return report

    def test_success_retains_fixture_without_recursive_removal(self) -> None:
        report = self.run_mock_measurement(created_blocked_shell=False)
        self.assertEqual("MEASURED", report["result"])
        self.assertTrue(report["teardown_complete"])

    def test_status_500_after_shell_creation_is_not_a_rejected_request(self) -> None:
        report = self.run_mock_measurement(created_blocked_shell=True)
        self.assertEqual("FAIL", report["result"])
        self.assertFalse(report["teardown_complete"])
        self.assertIn("shell_settlement_unconfirmed", report["teardown_failures"])

    def test_owner_verification_500_is_not_a_rejected_request(self) -> None:
        report = self.run_mock_measurement(
            created_blocked_shell=False, owner_verification_fails=True
        )
        self.assertEqual("FAIL", report["result"])
        self.assertFalse(report["teardown_complete"])
        self.assertIn("shell_settlement_unconfirmed", report["teardown_failures"])

    def test_unknown_shell_settlement_preserves_the_fixture(self) -> None:
        with retained_directory() as parent:
            runtime = Mock()
            runtime.mutate.side_effect = probe.ProbeFailure("response_lost")
            with (
                patch.object(probe, "preflight"),
                patch.object(probe, "prepare"),
                patch.object(
                    probe, "run_child", return_value=(0, b"opencode v2.2.6", b"")
                ),
                patch.object(probe, "PrivateRuntime", return_value=runtime),
                patch.object(probe, "wait_for"),
            ):
                report = probe.run_probe("unused", parent)
            self.assertFalse(report["teardown_complete"])
            self.assertIn("shell_settlement_unconfirmed", report["teardown_failures"])
            self.assertEqual(report["result"], "FAIL")
            self.assertTrue((parent / report["retained_fixture"]).is_dir())


if __name__ == "__main__":
    unittest.main()
