from __future__ import annotations

import copy
import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import gateway_v2_auxiliary_redaction_probe as probe


@contextmanager
def retained_test_directory() -> Iterator[str]:
    """Do not recursively remove version or runtime fixture paths after tests."""
    yield tempfile.mkdtemp(prefix="v2-aux-unit-")


def evidence(mode: str) -> tuple[list[dict], list[dict]]:
    unprotected = mode == "control"
    rows: list[dict] = [{"phase": "ready", "version": "2.2.5"}]
    requests: list[dict] = []
    for kind in probe.KINDS:
        rows.append(
            {
                "phase": "before",
                "kind": kind,
                "valid": True,
                "messageMarker": True,
                "messageCanary": True,
            }
        )
        rows.append(
            {
                "phase": "after",
                "kind": kind,
                "systemMarker": True,
                "messageMarker": True,
                "systemCanary": unprotected,
                "messageCanary": unprotected,
                "systemRedacted": not unprotected,
                "messageRedacted": not unprotected,
            }
        )
        requests.append(
            {
                "markers": [kind],
                "system_canary": unprotected,
                "message_canary": unprotected,
                "message_marker": True,
                "redacted": not unprotected,
            }
        )
    return rows, requests


class AuxiliaryRedactionEvidenceTest(unittest.TestCase):
    def test_both_modes_require_all_four_native_kinds(self) -> None:
        for mode in probe.MODES:
            with self.subTest(mode=mode):
                rows, requests = evidence(mode)
                requests.append(copy.deepcopy(requests[2]))
                counts = probe.assess(mode, rows, requests)
                self.assertEqual(set(probe.KINDS), set(counts))
                self.assertEqual(2, counts["compaction"])

    def test_missing_duplicate_or_out_of_order_hook_evidence_fails(self) -> None:
        rows, requests = evidence("protected")
        invalid = [
            rows[:-1],
            rows + [copy.deepcopy(rows[-1])],
            [rows[0], rows[2], rows[1], *rows[3:]],
            [{"phase": "ready", "version": "2.2.4"}, *rows[1:]],
            [*rows, {"phase": "unexpected", "raw": "synthetic"}],
        ]
        for candidate in invalid:
            with (
                self.subTest(candidate=candidate),
                self.assertRaises(probe.ProbeFailure),
            ):
                probe.assess("protected", candidate, requests)

    def test_requires_actual_input_canaries_and_distinct_controls(self) -> None:
        for mode in probe.MODES:
            rows, requests = evidence(mode)
            for key in ("valid", "messageMarker", "messageCanary"):
                changed = copy.deepcopy(rows)
                changed[1][key] = False
                with (
                    self.subTest(mode=mode, key=key),
                    self.assertRaises(probe.ProbeFailure),
                ):
                    probe.assess(mode, changed, requests)
            altered = copy.deepcopy(requests)
            altered[0]["system_canary"] = mode != "control"
            with self.subTest(mode=mode), self.assertRaises(probe.ProbeFailure):
                probe.assess(mode, rows, altered)

    def test_protected_case_rejects_leaked_or_unredacted_values(self) -> None:
        rows, requests = evidence("protected")
        for key in ("systemCanary", "messageCanary"):
            changed = copy.deepcopy(rows)
            changed[2][key] = True
            with self.subTest(key=key), self.assertRaises(probe.ProbeFailure):
                probe.assess("protected", changed, requests)
        for key in (
            "systemRedacted",
            "messageRedacted",
            "messageMarker",
            "systemMarker",
        ):
            changed = copy.deepcopy(rows)
            changed[2][key] = False
            with self.subTest(key=key), self.assertRaises(probe.ProbeFailure):
                probe.assess("protected", changed, requests)
        for key in ("system_canary", "message_canary"):
            changed = copy.deepcopy(requests)
            changed[0][key] = True
            with self.subTest(key=key), self.assertRaises(probe.ProbeFailure):
                probe.assess("protected", rows, changed)

    def test_missing_ambiguous_or_non_boolean_provider_evidence_fails(self) -> None:
        rows, requests = evidence("protected")
        cases = [
            requests[:-1],
            [],
            [*requests, {**requests[0], "markers": []}],
            [*requests, {**requests[0], "markers": ["context", "title"]}],
            [*requests, {**requests[0], "message_marker": 1}],
            [*requests, {**requests[0], "redacted": False}],
        ]
        for candidate in cases:
            with (
                self.subTest(candidate=candidate),
                self.assertRaises(probe.ProbeFailure),
            ):
                probe.assess("protected", rows, candidate)

    def test_malformed_evidence_never_becomes_a_pass(self) -> None:
        rows, requests = evidence("protected")
        for invalid_rows, invalid_requests in (
            ([None], requests),
            (rows, [None]),
            (rows, None),
        ):
            with (
                self.subTest(rows=invalid_rows, requests=invalid_requests),
                self.assertRaises(probe.ProbeFailure),
            ):
                probe.assess("protected", invalid_rows, invalid_requests)
        with self.assertRaises(probe.ProbeFailure):
            probe.assess("unknown", rows, requests)

    def test_provider_capture_retains_only_boolean_witnesses(self) -> None:
        state = probe.CaptureState("control", Path("/synthetic"), 0)
        response, finish = state.answer(
            {
                "system": f"{probe.SYSTEM_MARKER}context {probe.SYSTEM_CANARY}",
                "message": f"{probe.MESSAGE_MARKER} {probe.MESSAGE_CANARY}",
                "private": "SYNTHETIC_UNRELATED_PRIVATE_DATA",
            }
        )
        self.assertEqual("stop", finish)
        self.assertEqual({"role": "assistant", "content": "SYNTHETIC_OK"}, response)
        encoded = json.dumps(state.observations)
        self.assertNotIn(probe.SYSTEM_CANARY, encoded)
        self.assertNotIn(probe.MESSAGE_CANARY, encoded)
        self.assertNotIn("SYNTHETIC_UNRELATED_PRIVATE_DATA", encoded)
        self.assertEqual(["context"], state.observations[0]["markers"])

    @unittest.skipUnless(os.name == "posix", "POSIX shell required")
    def test_installer_stub_exits_without_writing_a_marker(self) -> None:
        result = subprocess.run(
            ["/bin/sh", "-c", probe.INSTALLER_STUB],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=2,
            check=False,
        )
        self.assertEqual(97, result.returncode)
        self.assertEqual(b"", result.stdout)
        self.assertEqual(b"", result.stderr)

    def test_trace_channel_rejects_oversized_and_excess_rows(self) -> None:
        for full in (False, True):
            with self.subTest(full=full):
                state = probe.CaptureState(
                    "control", Path("/synthetic"), time.monotonic() + 10
                )
                if full:
                    state.trace_rows = [{"phase": "ready"}] * probe.MAX_TRACE_ROWS
                provider = probe.CaptureProvider(state)
                thread = threading.Thread(
                    target=provider.serve_forever,
                    kwargs={"poll_interval": 0.05},
                    daemon=True,
                )
                thread.start()
                try:
                    body = b"{}" if full else b"x" * (probe.MAX_TRACE_BYTES + 1)
                    connection = http.client.HTTPConnection(
                        "127.0.0.1", provider.server_port, timeout=2
                    )
                    connection.request(
                        "POST",
                        "/trace",
                        body,
                        {"Authorization": f"Bearer {state.control_key}"},
                    )
                    response = connection.getresponse()
                    self.assertEqual(400, response.status)
                    response.read()
                    connection.close()
                    expected = "trace_row_limit" if full else "trace_request_size"
                    self.assertEqual(expected, state.failure)
                    self.assertEqual(
                        probe.MAX_TRACE_ROWS if full else 0, len(state.trace_rows)
                    )
                finally:
                    state.stop()
                    provider.shutdown()
                    provider.close_connections()
                    provider.server_close()
                    for worker in provider.workers:
                        worker.join(timeout=2)
                    thread.join(timeout=2)
                    self.assertFalse(thread.is_alive())

    def test_provider_connection_limit_includes_trace_connections(self) -> None:
        state = probe.CaptureState("control", Path("/synthetic"), time.monotonic() + 10)
        provider = probe.CaptureProvider(state)
        try:
            for _ in range(probe.MAX_CONNECTIONS):
                self.assertTrue(provider.verify_request(Mock(), ("127.0.0.1", 1)))
            self.assertFalse(provider.verify_request(Mock(), ("127.0.0.1", 1)))
            self.assertEqual("provider_connection_limit", state.failure)
            self.assertEqual(probe.MAX_CONNECTIONS, len(provider.admitted))
        finally:
            state.stop()
            provider.close_connections()
            provider.server_close()

    def test_provider_requires_its_own_per_case_token(self) -> None:
        for authorized in (False, True):
            with self.subTest(authorized=authorized):
                state = probe.CaptureState(
                    "control", Path("/synthetic"), time.monotonic() + 10
                )
                self.assertNotEqual(state.control_key, state.provider_key)
                provider = probe.CaptureProvider(state)
                thread = threading.Thread(
                    target=provider.serve_forever,
                    kwargs={"poll_interval": 0.05},
                    daemon=True,
                )
                thread.start()
                try:
                    connection = http.client.HTTPConnection(
                        "127.0.0.1", provider.server_port, timeout=2
                    )
                    credential = state.provider_key if authorized else "synthetic-only"
                    payload = {
                        "model": "mock",
                        "messages": [
                            {
                                "role": "user",
                                "content": f"{probe.MESSAGE_MARKER} {probe.MESSAGE_CANARY}",
                            }
                        ],
                    }
                    connection.request(
                        "POST",
                        "/v1/chat/completions",
                        json.dumps(payload),
                        {"Authorization": f"Bearer {credential}"},
                    )
                    response = connection.getresponse()
                    self.assertEqual(200 if authorized else 401, response.status)
                    response.read()
                    connection.close()
                    for worker in provider.workers:
                        worker.join(timeout=2)
                    if authorized:
                        self.assertEqual(1, state.requests)
                        self.assertEqual(1, state.responses)
                        self.assertIsNone(state.failure)
                    else:
                        self.assertEqual(0, state.requests)
                        self.assertEqual(
                            "provider_authentication_failed", state.failure
                        )
                finally:
                    state.stop()
                    provider.shutdown()
                    provider.close_connections()
                    provider.server_close()
                    for worker in provider.workers:
                        worker.join(timeout=2)
                    thread.join(timeout=2)
                    self.assertFalse(thread.is_alive())

    @unittest.skipUnless(os.name == "posix", "POSIX fixture ownership required")
    def test_setup_failure_settles_owned_provider_without_touching_other_files(
        self,
    ) -> None:
        with retained_test_directory() as raw:
            parent = Path(raw)
            sentinel = parent / "unrelated"
            sentinel.write_text("preserve", encoding="utf-8")
            with patch.object(
                probe,
                "prepare_fixture",
                side_effect=probe.ProbeFailure("synthetic_setup_failure"),
            ):
                report = probe.run_case("/nonexistent", parent, "control")
            self.assertEqual("FAIL", report["measurement"])
            self.assertEqual("synthetic_setup_failure", report["reason"])
            self.assertIs(report["teardown_complete"], True)
            self.assertTrue((parent / report["retained_fixture"]).is_dir())
            self.assertEqual("preserve", sentinel.read_text(encoding="utf-8"))

    @unittest.skipUnless(os.name == "posix", "POSIX fixture ownership required")
    def test_unsettled_runtime_retains_only_its_owned_fixture(self) -> None:
        with retained_test_directory() as raw:
            parent = Path(raw)
            sentinel = parent / "unrelated"
            sentinel.write_text("preserve", encoding="utf-8")
            runtime = Mock()
            runtime.close.side_effect = probe.ProbeFailure(
                "synthetic_unsettled_runtime"
            )
            with (
                patch.object(probe, "prepare_fixture", return_value={}),
                patch.object(probe, "PrivateRuntime", return_value=runtime),
                patch.object(probe, "exercise"),
            ):
                report = probe.run_case("/nonexistent", parent, "control")
            self.assertEqual("FAIL", report["measurement"])
            self.assertIs(report["teardown_complete"], False)
            self.assertIn("runtime-stop", report["teardown_failures"])
            retained = parent / report["retained_fixture"]
            self.assertTrue(retained.is_dir())
            self.assertEqual("preserve", sentinel.read_text(encoding="utf-8"))

    @unittest.skipUnless(os.name == "posix", "POSIX fixture creation required")
    def test_fixture_creation_is_exclusive_and_does_not_follow_links(self) -> None:
        with retained_test_directory() as raw:
            root = Path(raw)
            probe.write_fixture(root, "owned/config.json", "synthetic")
            target = root / "owned" / "config.json"
            self.assertEqual("synthetic", target.read_text(encoding="utf-8"))
            self.assertEqual(0o600, target.stat().st_mode & 0o777)
            with self.assertRaises(FileExistsError):
                probe.write_fixture(root, "owned/config.json", "overwrite")
            self.assertEqual("synthetic", target.read_text(encoding="utf-8"))

            (root / "link").symlink_to(root / "owned", target_is_directory=True)
            with self.assertRaises((OSError, probe.ProbeFailure)):
                probe.write_fixture(root, "link/other", "blocked")
            self.assertFalse((root / "owned" / "other").exists())
            (root / "dangling").symlink_to(root / "missing")
            with self.assertRaises((OSError, probe.ProbeFailure)):
                probe.write_fixture(root, "dangling", "blocked")
            for relative in ("../escape", "/absolute/path"):
                with (
                    self.subTest(relative=relative),
                    self.assertRaises(probe.ProbeFailure),
                ):
                    probe.write_fixture(root, relative, "blocked")

    def test_trace_channel_authenticates_and_keeps_provider_counts_separate(
        self,
    ) -> None:
        state = probe.CaptureState("control", Path("/synthetic"), time.monotonic() + 10)
        provider = probe.CaptureProvider(state)
        thread = threading.Thread(
            target=provider.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        thread.start()
        try:
            row = {"phase": "ready", "version": "2.2.5"}
            connection = http.client.HTTPConnection(
                "127.0.0.1", provider.server_port, timeout=2
            )
            connection.request(
                "POST",
                "/trace",
                json.dumps(row),
                {
                    "Authorization": f"Bearer {state.control_key}",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            self.assertEqual(200, response.status)
            response.read()
            connection.close()
            self.assertEqual([row], state.trace_rows)
            self.assertEqual(0, state.responses)
            self.assertEqual(0, state.requests)

            connection = http.client.HTTPConnection(
                "127.0.0.1", provider.server_port, timeout=2
            )
            connection.request(
                "POST", "/trace", "{}", {"Authorization": "Bearer wrong"}
            )
            response = connection.getresponse()
            self.assertEqual(400, response.status)
            response.read()
            connection.close()
            self.assertEqual("trace_authentication_failed", state.failure)
            self.assertEqual([row], state.trace_rows)
        finally:
            state.stop()
            provider.shutdown()
            provider.close_connections()
            provider.server_close()
            for worker in provider.workers:
                worker.join(timeout=2)
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())

    def test_probe_never_qualifies_incomplete_cases_or_changed_binary(self) -> None:
        with retained_test_directory() as raw:
            root = Path(raw)
            binary = root / "opencode"
            binary.write_bytes(b"synthetic-binary")
            dist = root / "plugin" / "gateway-core" / "dist"
            for relative in (
                "v2/provider-boundary.js",
                "hooks/shared/secret-redaction.js",
            ):
                path = dist / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("synthetic", encoding="utf-8")

            def success(_binary: str, _parent: Path, mode: str) -> dict:
                return {
                    "case": mode,
                    "measurement": "PASS",
                    "teardown_complete": True,
                    "provider_requests_by_kind": {kind: 1 for kind in probe.KINDS},
                }

            with (
                patch.object(probe, "ROOT", root),
                patch.object(probe, "preflight"),
                patch.object(
                    probe, "run_child", return_value=(0, b"opencode v2.2.5\n", b"")
                ),
                patch.object(probe, "run_case", side_effect=success),
            ):
                result = probe.probe(str(binary), root)
                self.assertEqual("PASS", result["measurement"])
                self.assertEqual("disabled-unqualified", result["authority"])
                self.assertTrue((root / result["version_fixture"]).is_dir())
                self.assertEqual(
                    list(probe.MODES), [case["case"] for case in result["cases"]]
                )

                with (
                    patch.object(
                        probe, "run_child", return_value=(0, b"other version\n", b"")
                    ),
                    patch.object(probe, "run_case") as skipped,
                ):
                    unsupported = probe.probe(str(binary), root)
                    self.assertEqual("FAIL", unsupported["measurement"])
                    self.assertEqual("unsupported_host_version", unsupported["reason"])
                    self.assertTrue((root / unsupported["version_fixture"]).is_dir())
                    skipped.assert_not_called()

                def fail_control(_binary: str, _parent: Path, mode: str) -> dict:
                    return {"case": mode, "measurement": "FAIL"}

                with patch.object(probe, "run_case", side_effect=fail_control):
                    failed = probe.probe(str(binary), root)
                    self.assertEqual("FAIL", failed["measurement"])
                    self.assertEqual(1, len(failed["cases"]))

                def unsettled(_binary: str, _parent: Path, mode: str) -> dict:
                    return {
                        **success(_binary, _parent, mode),
                        "teardown_complete": False,
                    }

                with patch.object(probe, "run_case", side_effect=unsettled):
                    self.assertEqual(
                        "FAIL", probe.probe(str(binary), root)["measurement"]
                    )

                def missing_kind(_binary: str, _parent: Path, mode: str) -> dict:
                    return {
                        **success(_binary, _parent, mode),
                        "provider_requests_by_kind": {"context": 1},
                    }

                with patch.object(probe, "run_case", side_effect=missing_kind):
                    self.assertEqual(
                        "FAIL", probe.probe(str(binary), root)["measurement"]
                    )

                def replace_binary(_binary: str, _parent: Path, mode: str) -> dict:
                    binary.write_bytes(b"changed-synthetic-binary")
                    return success(_binary, _parent, mode)

                with patch.object(probe, "run_case", side_effect=replace_binary):
                    changed = probe.probe(str(binary), root)
                    self.assertEqual("FAIL", changed["measurement"])
                    self.assertEqual("binary_identity_changed", changed["reason"])


if __name__ == "__main__":
    unittest.main()
