from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gateway_v2_claim_lifecycle_probe as probe


def evidence() -> tuple[list[dict], list[dict], probe.Evidence]:
    initial = {"claimed": False, "busy_recorded": False, "idle_recorded": False, "resume_attempts": 0}
    running = {"claimed": True, "busy_recorded": True, "idle_recorded": False, "resume_attempts": 0}
    terminal = {"claimed": False, "busy_recorded": True, "idle_recorded": True, "resume_attempts": 0}
    observations = {
        "initial": {"target": initial, "peer": initial},
        "active": {"target": running, "peer": initial},
        "peer_completed": {"target": running, "peer": terminal},
        "interrupted": {"target": terminal, "peer": terminal},
    }
    rows = [
        {"phase": "ready", "version": "2.2.5"},
        {"phase": "target_context", "sessionID": "synthetic-target"},
        {"phase": "peer_context", "sessionID": "synthetic-peer"},
        {"phase": "interrupt", "sessionID": "synthetic-target", "accepted": True},
        {"phase": "wait_return", "sessionID": "synthetic-target"},
    ]
    requests = [{
        "markers": [], "system_canary": False, "message_canary": False,
        "message_marker": True, "redacted": False,
    }]
    return rows, requests, probe.Evidence("synthetic-target", "synthetic-peer", copy.deepcopy(observations))


def retained_root() -> Path:
    return Path(tempfile.mkdtemp(prefix="v2-claim-unit-"))


def fixture(root: Path, *, schema: str = "table", value: object = None) -> Path:
    path = root / "runtime.sqlite"
    with sqlite3.connect(path) as db:
        if schema == "view":
            db.execute("CREATE TABLE backing (id, time_suspended, time_busy, time_idle, resume_attempts)")
            db.execute("CREATE VIEW session_v2 AS SELECT * FROM backing")
            table = "backing"
        else:
            db.execute("CREATE TABLE session_v2 (id TEXT, time_suspended, time_busy, time_idle, resume_attempts)")
            table = "session_v2"
        db.execute(f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?)", ("synthetic-target", value, None, None, 0))
        db.execute(f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?)", ("synthetic-peer", None, None, None, 0))
    path.chmod(0o600)
    return path


class ClaimEvidenceTests(unittest.TestCase):
    def test_complete_correlated_lifecycle_is_measured(self) -> None:
        rows, requests, observed = evidence()
        self.assertEqual({"peer_provider": 1}, probe.assess("native", rows, requests, observed))
        self.assertNotIn("synthetic-target", json.dumps(observed.observations))

    def test_trace_requires_owned_ids_real_acceptance_wait_and_order(self) -> None:
        rows, requests, observed = evidence()
        candidates = []
        for index, key, value in (
            (0, "version", "2.2.6"), (1, "sessionID", "other"),
            (2, "sessionID", "other"), (3, "accepted", False),
            (3, "accepted", 1), (4, "sessionID", "other"),
        ):
            changed = copy.deepcopy(rows)
            changed[index][key] = value
            candidates.append(changed)
        candidates.extend((rows[:-1], rows + [copy.deepcopy(rows[1])], [*rows, {"phase": "fixture_fault"}], [rows[0], rows[2], rows[1], *rows[3:]], [{"phase": []}]))
        for changed in candidates:
            with self.subTest(changed=changed), self.assertRaises(probe.ProbeFailure):
                probe.assess("native", changed, requests, observed)

    def test_every_stage_and_strict_types_are_required(self) -> None:
        rows, requests, observed = evidence()
        for stage, actor, key, value in (
            ("initial", "target", "claimed", True),
            ("active", "target", "claimed", False),
            ("active", "peer", "claimed", True),
            ("peer_completed", "peer", "idle_recorded", False),
            ("interrupted", "target", "claimed", True),
            ("interrupted", "target", "busy_recorded", 1),
            ("interrupted", "peer", "resume_attempts", True),
        ):
            changed = copy.deepcopy(observed)
            changed.observations[stage][actor][key] = value
            with self.subTest(stage=stage, actor=actor, key=key), self.assertRaises(probe.ProbeFailure):
                probe.assess("native", rows, requests, changed)
        changed = copy.deepcopy(observed)
        del changed.observations["initial"]
        with self.assertRaises(probe.ProbeFailure):
            probe.assess("native", rows, requests, changed)

    def test_provider_marker_and_bounded_safe_shape_are_required(self) -> None:
        rows, requests, observed = evidence()
        for changed in ([], [{**requests[0], "message_marker": False}], [{**requests[0], "message_marker": 1}], [{**requests[0], "markers": [[]]}], [{**requests[0], "secret": "x"}]):
            with self.subTest(changed=changed), self.assertRaises(probe.ProbeFailure):
                probe.assess("native", rows, changed, observed)

    def test_plugin_delegates_interruption_and_wait_and_correlates_ids(self) -> None:
        source = probe.fixture_plugin(12345, "synthetic-key")
        self.assertIn("ctx.session.interrupt({sessionID:target,resume:false})", source)
        self.assertIn("ctx.session.wait({sessionID:target})", source)
        self.assertIn('phase:"target_context",sessionID:event.sessionID', source)
        self.assertIn('phase:"peer_context",sessionID:event.sessionID', source)


@unittest.skipUnless(os.name == "posix", "POSIX fixture ownership required")
class ClaimReadTests(unittest.TestCase):
    def test_reads_only_bound_fixture_rows_without_changing_quiescent_database(self) -> None:
        root = retained_root()
        path = fixture(root, value=23)
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        result = probe.read_claims(root, "synthetic-target", "synthetic-peer", time.monotonic() + 3)
        self.assertTrue(result["target"]["claimed"])
        self.assertFalse(result["peer"]["claimed"])
        self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertTrue(path.exists())

    def test_missing_duplicate_and_malformed_rows_fail_closed(self) -> None:
        for value in ("not-an-integer", -1, 1.5):
            root = retained_root()
            fixture(root, value=value)
            with self.subTest(value=value), self.assertRaises(probe.ProbeFailure):
                probe.read_claims(root, "synthetic-target", "synthetic-peer", time.monotonic() + 3)
        root = retained_root()
        path = fixture(root)
        with sqlite3.connect(path) as db:
            db.execute("INSERT INTO session_v2 VALUES (?, NULL, NULL, NULL, 0)", ("synthetic-target",))
        for target, peer in (("synthetic-target", "synthetic-peer"), ("missing", "synthetic-peer")):
            with self.subTest(target=target), self.assertRaises(probe.ProbeFailure):
                probe.read_claims(root, target, peer, time.monotonic() + 3)

    def test_views_invalid_ids_and_expired_deadlines_fail_closed(self) -> None:
        root = retained_root()
        fixture(root, schema="view")
        with self.assertRaisesRegex(probe.ProbeFailure, "native_schema_invalid"):
            probe.read_claims(root, "synthetic-target", "synthetic-peer", time.monotonic() + 3)
        with self.assertRaises(probe.ProbeFailure):
            probe.read_claims(root, "same", "same", time.monotonic() + 3)
        with self.assertRaises(probe.ProbeFailure):
            probe.read_claims(root, "../bad", "peer", time.monotonic() + 3)
        with self.assertRaisesRegex(probe.ProbeFailure, "claim_read_timeout"):
            probe.read_claims(root, "synthetic-target", "synthetic-peer", time.monotonic() - 1)

    def test_symlink_hardlink_and_permissive_database_are_refused(self) -> None:
        root = retained_root()
        other = retained_root()
        external = fixture(other)
        (root / "runtime.sqlite").symlink_to(external)
        with self.assertRaises(probe.ProbeFailure):
            probe.read_claims(root, "synthetic-target", "synthetic-peer", time.monotonic() + 3)
        root2 = retained_root()
        path = fixture(root2)
        os.link(path, root2 / "linked.sqlite")
        with self.assertRaises(probe.ProbeFailure):
            probe.read_claims(root2, "synthetic-target", "synthetic-peer", time.monotonic() + 3)
        root3 = retained_root()
        fixture(root3).chmod(0o644)
        with self.assertRaises(probe.ProbeFailure):
            probe.read_claims(root3, "synthetic-target", "synthetic-peer", time.monotonic() + 3)
        root4 = retained_root()
        (root4 / "root-link").symlink_to(other, target_is_directory=True)
        with self.assertRaises(probe.ProbeFailure):
            probe.read_claims(root4 / "root-link", "synthetic-target", "synthetic-peer", time.monotonic() + 3)

    def test_database_identity_change_cannot_be_reported_as_success(self) -> None:
        root = retained_root()
        fixture(root)
        with (
            patch.object(probe, "_owned_database", side_effect=[(1, 2), (1, 3)]),
            self.assertRaisesRegex(probe.ProbeFailure, "synthetic_database_identity_changed"),
        ):
            probe.read_claims(root, "synthetic-target", "synthetic-peer", time.monotonic() + 3)


class ClaimProbeSafetyTests(unittest.TestCase):
    def test_unexpected_plugin_inventory_cannot_create_sessions(self) -> None:
        root = Path("/synthetic")
        state = probe.native.NativeState("native", root, time.monotonic() + 5)
        config = {"plugins": [str(root / "project/owned")]}
        for inventory in (
            [{"source": "owned", "status": "active"}, {"source": "rogue", "status": "failed"}],
            [{"source": "owned", "status": "active"}, {"source": "owned", "status": "failed"}],
            [{"source": "owned", "status": "failed"}],
        ):
            runtime = Mock()
            with self.subTest(inventory=inventory), patch.object(probe, "activated_inventory", return_value=inventory), self.assertRaises(probe.ProbeFailure):
                probe.exercise(runtime, root, config, state, probe.Evidence())
            runtime.mutate.assert_not_called()

    def test_unowned_target_trace_stops_before_peer_prompt_or_interrupt(self) -> None:
        root = Path("/synthetic")
        state = probe.native.NativeState("native", root, time.monotonic() + 5)
        state.trace_rows.append({"phase": "target_context", "sessionID": "wrong-session"})
        state.gates["pre1"].arrived.set()
        runtime = Mock()
        runtime.mutate.side_effect = [
            {"data": {"id": "synthetic-target"}}, {"data": {"id": "synthetic-peer"}}, None,
        ]
        config = {"plugins": [str(root / "project/owned")]}
        with (
            patch.object(probe, "activated_inventory", return_value=[{"source": "owned", "status": "active"}]),
            patch.object(probe, "read_claims", return_value={}),
            self.assertRaisesRegex(probe.ProbeFailure, "trace_identity_mismatch"),
        ):
            probe.exercise(runtime, root, config, state, probe.Evidence())
        self.assertEqual(3, runtime.mutate.call_count)
        self.assertFalse(state.gates["trigger1"].released.is_set())

    @unittest.skipUnless(os.name == "posix", "POSIX fixture ownership required")
    def test_wrong_version_and_child_failure_retain_version_fixture(self) -> None:
        root = retained_root()
        binary = root / "binary"
        binary.write_bytes(b"synthetic-executable")
        for child, reason in (((0, b"opencode v9.9.9\n", b""), "unsupported_host_version"), (probe.ProbeFailure("child_timeout"), "child_timeout")):
            with (
                patch.object(probe, "preflight"),
                patch.object(probe, "run_child", side_effect=child if isinstance(child, Exception) else None, return_value=child if not isinstance(child, Exception) else None),
                patch.object(probe.auxiliary, "run_case") as case,
            ):
                result = probe.probe(str(binary), root)
            self.assertEqual(reason, result["reason"])
            self.assertTrue((root / result["version_fixture"]).is_dir())
            self.assertNotIn(str(root), json.dumps(result))
            case.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "POSIX fixture ownership required")
    def test_unsettled_and_unmeasured_cases_cannot_report_success(self) -> None:
        root = retained_root()
        binary = root / "binary"
        binary.write_bytes(b"synthetic-executable")
        for result, reason in (
            ({"measurement": "PASS", "teardown_complete": False, "provider_requests_by_kind": {"peer_provider": 1}}, "case_failed"),
            ({"measurement": "PASS", "teardown_complete": True, "provider_requests_by_kind": {"peer_provider": True}}, "case_failed"),
            ({"measurement": "PASS", "teardown_complete": True, "provider_requests_by_kind": {"peer_provider": 1}}, "claim_observation_invalid"),
        ):
            with (
                patch.object(probe, "preflight"),
                patch.object(probe, "run_child", return_value=(0, b"opencode v2.2.5\n", b"")),
                patch.object(probe.auxiliary, "run_case", return_value=result),
            ):
                report = probe.probe(str(binary), root)
            self.assertEqual(reason, report["reason"])
            self.assertEqual("FAIL", report["measurement"])
            self.assertTrue((root / report["version_fixture"]).is_dir())

    @unittest.skipUnless(os.name == "posix", "POSIX fixture ownership required")
    def test_success_and_binary_change_retain_fixture_and_hide_identifiers(self) -> None:
        for change_binary in (False, True):
            with self.subTest(change_binary=change_binary):
                root = retained_root()
                binary = root / "binary"
                binary.write_bytes(b"synthetic-executable")
                rows, requests, expected = evidence()

                def fake_exercise(_runtime: object, _root: object, _config: object, _state: object, observed: probe.Evidence, expected: probe.Evidence = expected) -> None:
                    observed.target, observed.peer = expected.target, expected.peer
                    observed.observations = copy.deepcopy(expected.observations)

                def fake_case(_binary: str, parent: Path, mode: str, *, hooks: object, rows: list = rows, requests: list = requests, change_binary: bool = change_binary, binary: Path = binary) -> dict:
                    case = Path(tempfile.mkdtemp(prefix="v2-claim-unit-case-", dir=parent))
                    hooks.exercise(None, case, {}, None)
                    counts = hooks.assess(mode, rows, requests)
                    if change_binary:
                        binary.write_bytes(b"changed-executable")
                    return {"measurement": "PASS", "teardown_complete": True, "provider_requests_by_kind": counts, "retained_fixture": case.name}

                with (
                    patch.object(probe, "preflight"), patch.object(probe, "exercise", side_effect=fake_exercise),
                    patch.object(probe, "run_child", return_value=(0, b"opencode v2.2.5\n", b"")),
                    patch.object(probe.auxiliary, "run_case", side_effect=fake_case),
                ):
                    result = probe.probe(str(binary), root)
                self.assertEqual("FAIL" if change_binary else "PASS", result["measurement"])
                if change_binary:
                    self.assertEqual("executable_changed", result["reason"])
                self.assertTrue((root / result["version_fixture"]).is_dir())
                self.assertTrue((root / result["case"]["retained_fixture"]).is_dir())
                self.assertNotIn("synthetic-target", json.dumps(result))
                self.assertNotIn(str(root), json.dumps(result))

    @unittest.skipUnless(os.name == "posix", "POSIX fixture ownership required")
    def test_changed_version_root_fails_and_skips_case(self) -> None:
        root = retained_root()
        binary = root / "binary"
        binary.write_bytes(b"synthetic-executable")
        with (
            patch.object(probe, "preflight"),
            patch.object(probe, "run_child", return_value=(0, b"opencode v2.2.5\n", b"")),
            patch.object(probe, "owned_fixture", return_value=False),
            patch.object(probe.auxiliary, "run_case") as case,
        ):
            result = probe.probe(str(binary), root)
        self.assertEqual("version_fixture_identity_changed", result["reason"])
        self.assertTrue((root / result["version_fixture"]).is_dir())
        case.assert_not_called()


if __name__ == "__main__":
    unittest.main()
