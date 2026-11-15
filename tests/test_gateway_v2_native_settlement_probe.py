from __future__ import annotations

import copy
import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gateway_v2_native_settlement_probe as probe


@contextmanager
def retained_directory() -> Iterator[Path]:
    yield Path(tempfile.mkdtemp(prefix="v2-native-settlement-unit-"))


def evidence() -> tuple[list[dict], list[dict]]:
    rows = [
        {"phase": "ready", "version": "2.2.5"},
        {"phase": "target_context", "n": 1},
        {"phase": "native_interrupt", "n": 1, "accepted": True, "target": True},
        {"phase": "wait_start", "n": 1, "target": True},
        {"phase": "after_return", "n": 1},
        {"phase": "wait_native_return", "n": 1},
        {"phase": "peer_context"},
        {"phase": "target_context", "n": 2},
        {"phase": "native_interrupt", "n": 2, "accepted": True, "target": True},
        {"phase": "after_return", "n": 2},
        {"phase": "wait_delivered", "n": 1},
        {"phase": "wait_start", "n": 2, "target": True},
        {"phase": "wait_native_return", "n": 2},
        {"phase": "guards", "allBlocked": True, "peerUnaffected": True, "waits": 2},
        {"phase": "wait_delivered", "n": 2},
        {"phase": "released", "target": True},
    ]
    requests = [{
        "markers": [], "system_canary": False, "message_canary": False,
        "message_marker": True, "redacted": False,
    }]
    return rows, requests


class NativeSettlementEvidenceTests(unittest.TestCase):
    def test_complete_order_and_correlated_peer_are_measured(self) -> None:
        rows, requests = evidence()
        self.assertEqual({"peer_provider": 1}, probe.assess("native", rows, requests))
        reordered = copy.deepcopy(rows)
        reordered[3], reordered[4] = reordered[4], reordered[3]
        self.assertEqual({"peer_provider": 1}, probe.assess("native", reordered, requests))

    def test_missing_duplicate_unknown_and_reordered_events_fail_closed(self) -> None:
        rows, requests = evidence()
        for candidate in (
            rows[:-1], rows + [copy.deepcopy(rows[8])],
            [*rows, {"phase": "unknown"}], [rows[0], rows[2], rows[1], *rows[3:]],
            [*rows[:5], rows[7], rows[6], rows[5], *rows[8:]],
            [{"phase": []}],
        ):
            with self.subTest(candidate=candidate), self.assertRaises(probe.ProbeFailure):
                probe.assess("native", candidate, requests)

    def test_interrupt_wait_and_guard_controls_must_be_valid(self) -> None:
        rows, requests = evidence()
        for index, key, value in (
            (0, "version", "2.2.6"), (2, "accepted", False), (8, "accepted", False),
            (2, "target", False), (11, "target", False), (13, "allBlocked", False),
            (13, "peerUnaffected", False), (13, "waits", 1), (15, "target", False),
            (2, "accepted", 1), (13, "waits", True), (3, "n", True),
        ):
            altered = copy.deepcopy(rows)
            altered[index][key] = value
            with self.subTest(index=index, key=key), self.assertRaises(probe.ProbeFailure):
                probe.assess("native", altered, requests)

    def test_peer_provider_observation_and_types_are_required(self) -> None:
        rows, requests = evidence()
        cases = [[], [{**requests[0], "message_marker": False}],
                 [{**requests[0], "message_marker": 1}], [{**requests[0], "raw": "secret"}],
                 [{**requests[0], "markers": [[]]}], [{**requests[0], "markers": ["unknown"]}], [None]]
        for candidate in cases:
            with self.subTest(candidate=candidate), self.assertRaises(probe.ProbeFailure):
                probe.assess("native", rows, candidate)
        with self.assertRaises(probe.ProbeFailure):
            probe.assess("other", rows, requests)

    def test_plugin_delegates_to_host_but_injects_error_and_gates_delivery(self) -> None:
        source = probe.fixture_plugin(12345, "synthetic-token")
        self.assertIn("await ctx.session.interrupt(input)", source)
        self.assertIn("await ctx.session.wait(input)", source)
        self.assertIn('await gate("wait" + n)', source)
        self.assertIn("await after(event())", source)
        self.assertNotIn("writeFile", source)


class NativeSettlementFixtureTests(unittest.TestCase):
    def _server(self, state: probe.NativeState) -> tuple[probe.NativeProvider, threading.Thread]:
        server = probe.NativeProvider(state)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        return server, thread

    def _stop(self, state: probe.NativeState, server: probe.NativeProvider, thread: threading.Thread) -> None:
        state.stop()
        server.shutdown()
        server.close_connections()
        server.server_close()
        for worker in server.workers:
            worker.join(2)
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(all(not worker.is_alive() for worker in server.workers))

    def test_ambiguous_or_unexpected_plugin_inventory_cannot_create_sessions(self) -> None:
        root = Path("/synthetic-owned")
        state = probe.NativeState("native", root, time.monotonic() + 5)
        config = {"plugins": [str(root / "project/owned")]}
        inventories = (
            [{"source": "owned", "status": "active"}, {"source": "rogue", "status": "failed"}],
            [{"source": "owned", "status": "active"}, {"source": "owned", "status": "failed"}],
            [{"source": "owned", "status": "failed"}],
        )
        for inventory in inventories:
            with self.subTest(inventory=inventory):
                runtime = Mock()
                with patch.object(probe, "activated_inventory", return_value=inventory), self.assertRaises(probe.ProbeFailure):
                    probe.exercise(runtime, root, config, state)
                runtime.mutate.assert_not_called()

    def test_gate_authentication_and_bounded_gate_release(self) -> None:
        for authorized in (True, False):
            state = probe.NativeState("native", Path("/synthetic"), time.monotonic() + 5)
            server, thread = self._server(state)
            try:
                if authorized:
                    state.gates["pre1"].release()
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                connection.request("GET", "/gate/pre1", headers={"Authorization": f"Bearer {state.control_key if authorized else 'wrong'}"})
                response = connection.getresponse()
                self.assertEqual(200 if authorized else 400, response.status)
                response.read()
                connection.close()
                if authorized:
                    self.assertTrue(state.gates["pre1"].arrived.is_set())
                    self.assertIsNone(state.failure)
                else:
                    self.assertEqual("control_authentication_failed", state.failure)
                    self.assertFalse(state.gates["pre1"].arrived.is_set())
            finally:
                self._stop(state, server, thread)

    def test_unknown_gate_fails_without_releasing_any_gate(self) -> None:
        state = probe.NativeState("native", Path("/synthetic"), time.monotonic() + 5)
        server, thread = self._server(state)
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            connection.request("GET", "/gate/unknown", headers={"Authorization": f"Bearer {state.control_key}"})
            response = connection.getresponse()
            self.assertEqual(400, response.status)
            response.read()
            connection.close()
            self.assertEqual("unexpected_control_path", state.failure)
            self.assertTrue(all(not gate.arrived.is_set() for gate in state.gates.values()))
        finally:
            self._stop(state, server, thread)

    def test_provider_rejects_connections_beyond_limit(self) -> None:
        state = probe.NativeState("native", Path("/synthetic"), time.monotonic() + 5)
        server = probe.NativeProvider(state)
        request = Mock()
        try:
            for _ in range(probe.MAX_ADMISSIONS):
                self.assertTrue(server.verify_request(request, ("127.0.0.1", 0)))
            self.assertFalse(server.verify_request(request, ("127.0.0.1", 0)))
            self.assertEqual("provider_connection_limit", state.failure)
        finally:
            server.server_close()

    def test_stopping_state_releases_all_controller_gates(self) -> None:
        state = probe.NativeState("native", Path("/synthetic"), time.monotonic() + 5)
        state.stop()
        self.assertTrue(state.stopped.is_set())
        self.assertTrue(all(gate.released.is_set() for gate in state.gates.values()))

    def test_stopping_state_drains_an_active_gate_connection(self) -> None:
        state = probe.NativeState("native", Path("/synthetic"), time.monotonic() + 5)
        server, thread = self._server(state)
        client = socket.create_connection(server.server_address, timeout=2)
        try:
            client.sendall(
                f"GET /gate/pre1 HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer {state.control_key}\r\n\r\n".encode()
            )
            self.assertTrue(state.gates["pre1"].arrived.wait(2))
            self._stop(state, server, thread)
        finally:
            client.close()
            if thread.is_alive():
                self._stop(state, server, thread)

    @unittest.skipUnless(os.name == "posix", "POSIX fixture ownership required")
    def test_probe_retains_version_root_and_requires_teardown_and_peer_evidence(self) -> None:
        with retained_directory() as root:
            binary = root / "binary"
            binary.write_bytes(b"synthetic-binary")
            adapter = root / "plugin/gateway-core/dist/v2/tool-output-redaction.js"
            adapter.parent.mkdir(parents=True)
            adapter.write_text("synthetic adapter")
            success = {"measurement": "PASS", "teardown_complete": True, "provider_requests_by_kind": {"peer_provider": 1}}
            with (
                patch.object(probe, "ROOT", root), patch.object(probe, "preflight"),
                patch.object(probe, "run_child", return_value=(0, b"opencode v2.2.5\n", b"")),
                patch.object(probe.auxiliary, "run_case", return_value=success),
            ):
                result = probe.probe(str(binary), root)
                self.assertEqual("PASS", result["measurement"])
                self.assertEqual("disabled-unqualified", result["authority"])
                self.assertTrue((root / result["version_fixture"]).is_dir())
                self.assertTrue(result["version_teardown_complete"])
                for altered in ({**success, "teardown_complete": False},
                                {**success, "provider_requests_by_kind": {"peer_provider": 0}},
                                {**success, "provider_requests_by_kind": {"peer_provider": True}}):
                    with patch.object(probe.auxiliary, "run_case", return_value=altered):
                        failed = probe.probe(str(binary), root)
                    self.assertEqual("case_failed", failed["reason"])
                    self.assertTrue((root / failed["version_fixture"]).is_dir())

    def test_wrong_version_and_child_failure_preserve_version_roots(self) -> None:
        with retained_directory() as root:
            binary = root / "binary"
            binary.write_bytes(b"synthetic-binary")
            adapter = root / "plugin/gateway-core/dist/v2/tool-output-redaction.js"
            adapter.parent.mkdir(parents=True)
            adapter.write_text("synthetic adapter")
            for child, expected, completed in (
                ((0, b"opencode v9.9.9\n", b""), "unsupported_host_version", True),
                (probe.ProbeFailure("child_timeout"), "child_timeout", False),
            ):
                with (
                    patch.object(probe, "ROOT", root), patch.object(probe, "preflight"),
                    patch.object(probe, "run_child", side_effect=child if isinstance(child, Exception) else None, return_value=child if not isinstance(child, Exception) else None),
                    patch.object(probe.auxiliary, "run_case") as case,
                ):
                    report = probe.probe(str(binary), root)
                self.assertEqual(expected, report["reason"])
                self.assertIs(report["version_teardown_complete"], completed)
                self.assertTrue((root / report["version_fixture"]).is_dir())
                case.assert_not_called()

    def test_version_identity_failure_preserves_fixture_and_skips_case(self) -> None:
        with retained_directory() as root:
            binary = root / "binary"
            binary.write_bytes(b"synthetic-binary")
            adapter = root / "plugin/gateway-core/dist/v2/tool-output-redaction.js"
            adapter.parent.mkdir(parents=True)
            adapter.write_text("synthetic adapter")
            with (
                patch.object(probe, "ROOT", root), patch.object(probe, "preflight"),
                patch.object(probe, "run_child", return_value=(0, b"opencode v2.2.5\n", b"")),
                patch.object(probe, "owned_fixture", return_value=False),
                patch.object(probe.auxiliary, "run_case") as case,
            ):
                result = probe.probe(str(binary), root)
            self.assertEqual("version_fixture_identity_changed", result["reason"])
            self.assertTrue((root / result["version_fixture"]).is_dir())
            case.assert_not_called()

    def test_changed_binary_or_adapter_fails_without_exposing_paths(self) -> None:
        for changed in ("binary", "adapter"):
            with self.subTest(changed=changed), retained_directory() as root:
                binary = root / "binary"
                binary.write_bytes(b"synthetic-binary")
                adapter = root / "plugin/gateway-core/dist/v2/tool-output-redaction.js"
                adapter.parent.mkdir(parents=True)
                adapter.write_text("synthetic adapter")

                def run_case(*_args: object, target: Path = binary if changed == "binary" else adapter, **_kwargs: object) -> dict:
                    target.write_text("changed")
                    return {"measurement": "PASS", "teardown_complete": True, "provider_requests_by_kind": {"peer_provider": 1}}

                with (
                    patch.object(probe, "ROOT", root), patch.object(probe, "preflight"),
                    patch.object(probe, "run_child", return_value=(0, b"opencode v2.2.5\n", b"")),
                    patch.object(probe.auxiliary, "run_case", side_effect=run_case),
                ):
                    report = probe.probe(str(binary), root)
                self.assertEqual("executable_or_adapter_changed", report["reason"])
                self.assertNotIn(str(root), json.dumps(report))
                self.assertTrue((root / report["version_fixture"]).is_dir())

    def test_symlink_fixture_parent_is_refused_without_starting_child(self) -> None:
        with retained_directory() as root:
            link = root / "parent-link"
            link.symlink_to(root, target_is_directory=True)
            with patch.object(probe, "run_child") as child:
                report = probe.probe(sys.executable, link)
            self.assertEqual("temporary_parent_unavailable", report["reason"])
            self.assertNotIn("version_fixture", report)
            child.assert_not_called()


if __name__ == "__main__":
    unittest.main()
