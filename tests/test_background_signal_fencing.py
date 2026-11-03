from __future__ import annotations

import argparse
import contextlib
import io
import itertools
import signal
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import background_task_manager as bg

MALFORMED_FINGERPRINTS = (
    None, "", "   ", 123, "unrelated", "a" * 63, "g" * 64, "é" * 64,
    "A" * 64, " " + "a" * 64,
)


class BackgroundSignalFencingTest(unittest.TestCase):
    def test_stale_record_without_identity_is_not_signalled_or_discarded(self) -> None:
        for fingerprint in MALFORMED_FINGERPRINTS:
            with self.subTest(fingerprint=fingerprint):
                job = {
                    "id": "synthetic-stale",
                    "status": "running",
                    "created_at": "2000-01-01T00:00:00Z",
                    "started_at": "2000-01-01T00:00:00Z",
                    "stale_after_seconds": 1,
                    "pid": 987654,
                    "pgid": 987654,
                    "run_token": "synthetic-reservation",
                    "process_start_fingerprint": fingerprint,
                }
                data = {"jobs": [job]}
                with patch.object(bg, "terminate_process", return_value="terminated") as terminate:
                    result = bg.cleanup_jobs(data)
                terminate.assert_not_called()
                self.assertEqual(1, result["stale_reconciling"])
                self.assertEqual(0, result["stale_cancelled"])
                self.assertEqual("reconciling", job["status"])
                self.assertEqual(987654, job["pid"])
                self.assertEqual(987654, job["pgid"])
                self.assertEqual("synthetic-reservation", job["run_token"])
                self.assertIsNone(job["ended_at"])
                self.assertIn("identity-unverified", job["summary"])

    def test_cancel_without_identity_preserves_uncertain_process_evidence(self) -> None:
        modes = ((False, False), (True, False), (True, True))
        for (lease, worker_owns), fingerprint in itertools.product(modes, MALFORMED_FINGERPRINTS):
            with self.subTest(lease=lease, worker_owns=worker_owns, fingerprint=fingerprint):
                job = {
                    "id": "synthetic-cancel",
                    "status": "running",
                    "pid": 987654,
                    "pgid": 987654,
                    "run_token": "synthetic-reservation",
                    "process_start_fingerprint": "a" * 64 if lease else fingerprint,
                }
                attempt = {
                    "id": "attempt-1", "status": "running", "pid": 987654,
                    "pgid": 987654, "process_start_fingerprint": fingerprint,
                }
                if lease:
                    job.update({
                        "execution_mode": "task_lease",
                        "current_attempt_id": "attempt-1",
                        "attempts": [attempt],
                        "lease_request": {"state_path": "synthetic-lease-state"},
                    })
                data = {"jobs": [job]}

                @contextlib.contextmanager
                def locked_jobs(*, writeback: bool = True, _data=data):
                    yield _data

                with (
                    patch.object(bg, "locked_jobs", side_effect=locked_jobs),
                    patch.object(bg, "cleanup_jobs", return_value={}),
                    patch.object(bg, "_attempt_identity", return_value=object() if worker_owns else None),
                    patch.object(bg, "terminate_process", return_value="terminated") as terminate,
                    patch.object(bg, "_best_effort_release") as release,
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    result = bg.command_cancel(argparse.Namespace(id="synthetic-cancel"))
                terminate.assert_not_called()
                release.assert_not_called()
                self.assertEqual(1, result)
                self.assertEqual("reconciling", job["status"])
                self.assertEqual(987654, job["pid"])
                self.assertEqual(987654, job["pgid"])
                self.assertIn("identity-unverified", job["summary"])
                if lease:
                    self.assertEqual("unknown", attempt["status"])
                    self.assertEqual("unknown", attempt["outcome_confidence"])

    def test_lease_reconciliation_never_signals_a_missing_identity(self) -> None:
        for fingerprint in MALFORMED_FINGERPRINTS:
            with self.subTest(fingerprint=fingerprint):
                attempt = {
                    "pid": 987654,
                    "pgid": 987654,
                    "process_start_fingerprint": fingerprint,
                }
                with patch.object(bg, "terminate_process", return_value="terminated") as terminate:
                    self.assertFalse(bg._contain_attempt_process(attempt))
                terminate.assert_not_called()

    def test_worker_exception_never_signals_a_malformed_recorded_identity(self) -> None:
        for fingerprint in MALFORMED_FINGERPRINTS:
            with self.subTest(fingerprint=fingerprint):
                attempt = {
                    "id": "attempt-1",
                    "status": "running",
                    "pid": 987654,
                    "pgid": 987654,
                    "process_start_fingerprint": fingerprint,
                }
                job = {
                    "id": "synthetic-worker",
                    "status": "running",
                    "execution_mode": "task_lease",
                    "current_attempt_id": "attempt-1",
                    "attempts": [attempt],
                }

                @contextlib.contextmanager
                def locked_jobs(*, writeback: bool = True, _job=job):
                    yield {"jobs": [_job]}

                with (
                    patch.object(bg, "locked_jobs", side_effect=locked_jobs),
                    patch.object(bg, "_lease_state_path", return_value=Path("synthetic-lease")),
                    patch.object(bg, "_attempt_identity", return_value=object()),
                    patch.object(bg, "terminate_process", return_value="terminated") as terminate,
                    patch.object(bg, "_best_effort_release") as release,
                ):
                    status = bg._handle_lease_worker_exception(job, "attempt-1", RuntimeError())
                terminate.assert_not_called()
                release.assert_not_called()
                self.assertEqual("reconciling", status)
                self.assertEqual("unknown", attempt["status"])
                self.assertEqual(987654, attempt["pid"])
                self.assertIn("identity-unverified", job["summary"])

    def test_uncontained_aborted_gate_cannot_release_a_lease(self) -> None:
        attempt = {
            "id": "attempt-1",
            "status": "running",
            "pid": 987654,
            "pgid": 987654,
            "process_start_fingerprint": None,
        }
        job = {
            "id": "synthetic-lease",
            "status": "running",
            "execution_mode": "task_lease",
            "current_attempt_id": "attempt-1",
            "attempts": [attempt],
        }

        @contextlib.contextmanager
        def locked_jobs(*, writeback: bool = True):
            yield {"jobs": [job]}

        with (
            patch.object(bg, "locked_jobs", side_effect=locked_jobs),
            patch.object(bg, "_lease_state_path", return_value=Path("synthetic-lease")),
            patch.object(bg, "_attempt_identity", return_value=object()),
            patch.object(bg, "_worker_attempt_is_live", return_value=False),
            patch.object(bg, "_read_json_artifact", return_value=(None, None)),
            patch.object(bg, "_gate_state", return_value="gate_aborted"),
            patch.object(bg, "terminate_process", return_value="terminated") as terminate,
            patch.object(bg, "_finish_prestart_attempt") as finish,
            patch.object(bg, "_best_effort_release") as release,
            patch.object(bg, "_mark_attempt_reconciling", return_value="reconciling"),
        ):
            result = bg.reconcile_lease_jobs()
        terminate.assert_not_called()
        finish.assert_not_called()
        release.assert_not_called()
        self.assertEqual(1, result["reconciling"])

    def test_gate_admission_failure_cannot_release_uncontained_process(self) -> None:
        for stage in ("persist", "grant"):
            with self.subTest(stage=stage):
                attempt = {
                    "id": "attempt-1", "receipt_path": "synthetic-receipt",
                    "gate_path": "synthetic-gate", "log_path": "synthetic-log",
                }
                job = {
                    "id": "synthetic-job", "cwd": ".", "command": "synthetic",
                    "current_attempt_id": "attempt-1", "attempts": [attempt],
                }
                process = SimpleNamespace(pid=987654, stdout=object())
                thread = SimpleNamespace(start=Mock())
                with (
                    patch.object(bg, "_claim_reserved_attempt", return_value=(object(), "running")),
                    patch.object(bg, "_snapshot_job", return_value=job),
                    patch.object(bg, "_lease_state_path", return_value=Path("synthetic-lease")),
                    patch.object(bg, "_prepared_receipt", return_value={}),
                    patch.object(bg, "_atomic_write_json"),
                    patch.object(bg.os, "pipe", return_value=(101, 102)),
                    patch.object(bg.os, "close"),
                    patch.object(bg.subprocess, "Popen", return_value=process),
                    patch.object(bg.threading, "Thread", return_value=thread),
                    patch.object(bg, "process_start_fingerprint", return_value="a" * 64),
                    patch.object(bg, "_persist_running_attempt") as persist,
                    patch.object(bg, "_grant_lease_gate") as grant,
                    patch.object(bg, "_settle_unadmitted_lease_gate", return_value="reconciling"),
                    patch.object(bg, "_best_effort_release") as release,
                ):
                    if stage == "persist":
                        persist.side_effect = bg.AttemptSuperseded("synthetic")
                    else:
                        grant.side_effect = bg.GateAdmissionError("synthetic", grant_delivered=False)
                    self.assertEqual(("reconciling", None), bg._run_lease_job(job))
                release.assert_not_called()

    def test_gate_settlement_releases_only_after_containment_and_projection(self) -> None:
        for status in ("failed", "queued", "cancelled", "reconciling", "superseded"):
            with self.subTest(status=status):
                process = SimpleNamespace(pid=987654, returncode=1, wait=Mock())
                thread = SimpleNamespace(join=Mock(), is_alive=Mock(return_value=False))
                identity = object()
                state_path = Path("synthetic-lease")
                with (
                    patch.object(bg, "_write_gate_marker"),
                    patch.object(bg.os, "close"),
                    patch.object(bg, "_gate_state", return_value="gate_aborted"),
                    patch.object(bg, "_finish_prestart_attempt", return_value=status),
                    patch.object(bg, "_best_effort_release") as release,
                ):
                    result = bg._settle_unadmitted_lease_gate(
                        "synthetic-job", "attempt-1", identity, process, "a" * 64,
                        {"gate_path": "synthetic-gate"}, thread, 102,
                        state_path=state_path, failure_class="synthetic-failure",
                    )
                self.assertEqual(status, result)
                if status in {"failed", "queued", "cancelled"}:
                    release.assert_called_once_with(identity, state_path)
                else:
                    release.assert_not_called()

    def test_gate_settlement_keeps_lease_after_failed_group_containment(self) -> None:
        process = SimpleNamespace(
            pid=987654, returncode=1,
            wait=Mock(side_effect=[bg.subprocess.TimeoutExpired("synthetic", 5), None]),
        )
        thread = SimpleNamespace(join=Mock(), is_alive=Mock(return_value=False))
        with (
            patch.object(bg, "_write_gate_marker"),
            patch.object(bg.os, "close"),
            patch.object(bg, "terminate_process", return_value="signal-failed"),
            patch.object(bg, "_mark_attempt_reconciling", return_value="reconciling"),
            patch.object(bg, "_finish_prestart_attempt") as finish,
            patch.object(bg, "_best_effort_release") as release,
        ):
            result = bg._settle_unadmitted_lease_gate(
                "synthetic-job", "attempt-1", object(), process, "a" * 64,
                {"gate_path": "synthetic-gate"}, thread, 102,
                state_path=Path("synthetic-lease"), failure_class="synthetic-failure",
            )
        self.assertEqual("reconciling", result)
        finish.assert_not_called()
        release.assert_not_called()

    def test_escalation_rechecks_group_identity_before_sigkill(self) -> None:
        with (
            patch.object(bg, "is_process_group_alive", return_value=True),
            patch.object(bg, "process_group_identity_matches", side_effect=[True, False]) as identity,
            patch.object(bg.os, "killpg") as sent,
        ):
            result = bg.terminate_process(
                987654, 987654, grace_seconds=0, expected_start_fingerprint="synthetic-original"
            )
        self.assertEqual("identity-mismatch", result)
        self.assertEqual(2, identity.call_count)
        sent.assert_called_once_with(987654, signal.SIGTERM)

    def test_escalation_rechecks_single_process_identity_before_sigkill(self) -> None:
        with (
            patch.object(bg, "is_pid_alive", return_value=True),
            patch.object(bg, "process_identity_matches", side_effect=[True, False]) as identity,
            patch.object(bg.os, "kill") as sent,
        ):
            result = bg.terminate_process(
                987654, grace_seconds=0, expected_start_fingerprint="synthetic-original"
            )
        self.assertEqual("identity-mismatch", result)
        self.assertEqual(2, identity.call_count)
        sent.assert_called_once_with(987654, signal.SIGTERM)

    def test_escalation_with_matching_identity_can_confirm_containment(self) -> None:
        with (
            patch.object(bg, "is_process_group_alive", side_effect=[True, True, False]),
            patch.object(bg, "process_group_identity_matches", return_value=True) as identity,
            patch.object(bg.os, "killpg") as sent,
        ):
            result = bg.terminate_process(
                987654, 987654, grace_seconds=0, expected_start_fingerprint="synthetic-original"
            )
        self.assertEqual("killed", result)
        self.assertEqual(2, identity.call_count)
        self.assertEqual([signal.SIGTERM, signal.SIGKILL], [call.args[1] for call in sent.call_args_list])

    def test_target_stopped_before_escalation_does_not_receive_sigkill(self) -> None:
        with (
            patch.object(bg, "is_process_group_alive", side_effect=[True, False]),
            patch.object(bg, "process_group_identity_matches", return_value=True) as identity,
            patch.object(bg.os, "killpg") as sent,
        ):
            result = bg.terminate_process(
                987654, 987654, grace_seconds=0, expected_start_fingerprint="synthetic-original"
            )
        self.assertEqual("terminated", result)
        self.assertEqual(1, identity.call_count)
        sent.assert_called_once_with(987654, signal.SIGTERM)


if __name__ == "__main__":
    unittest.main()
