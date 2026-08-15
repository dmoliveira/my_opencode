from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import background_task_manager as bg
import task_lease_command as leases

SCOPE = "dmoliveira/my_opencode"
TASK = "task_129"
SESSION = "session_74"


class BackgroundTaskManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bg-manager-")
        self.root = Path(self.temporary.name)
        self.bg_root = self.root / "bg"
        self.env = {
            **os.environ,
            "MY_OPENCODE_BG_DIR": str(self.bg_root),
            "MY_OPENCODE_BG_NOTIFICATIONS_ENABLED": "0",
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @contextmanager
    def patched_store(self):
        with (
            patch.object(bg, "BG_ROOT", self.bg_root),
            patch.object(bg, "JOBS_PATH", self.bg_root / "jobs.json"),
            patch.object(bg, "LOCK_PATH", self.bg_root / "jobs.lock"),
            patch.object(bg, "RUNS_DIR", self.bg_root / "runs"),
            patch.dict(os.environ, self.env, clear=False),
        ):
            yield

    def lease_paths(self) -> tuple[Path, Path]:
        config_path = self.root / "config.sqlite.yaml"
        config_path.write_text("database:\n  backend: sqlite\n", encoding="utf-8")
        return self.root / "leases.json", config_path

    def source_runner(self, config_path: Path):
        def run(_arguments: list[str], operation: str) -> dict[str, object]:
            if operation == "task_lease_codememory_doctor":
                return {
                    "status": "ok",
                    "runtime_ready": True,
                    "config_path": str(config_path.resolve()),
                    "backend": "sqlite",
                    "database_path": str(self.root / "codememory.sqlite3"),
                    "database_url_scheme": None,
                }
            if operation == "task_lease_codememory_current":
                return {
                    "scope_key": SCOPE,
                    "worktree_path": str(ROOT.resolve()),
                    "session_id": SESSION,
                    "session_outcome": "active",
                    "session_stale": False,
                    "task_id": TASK,
                }
            if operation == "task_lease_codememory_get":
                return {
                    "id": TASK,
                    "type": "task",
                    "scope_key": SCOPE,
                    "status": "doing",
                }
            raise AssertionError(f"unexpected operation: {operation}")

        return run

    def enqueue_lease(
        self,
        command: list[str],
        *,
        max_attempts: int = 1,
        retry_safe: bool = False,
        max_log_bytes: int = bg.DEFAULT_MAX_LOG_BYTES,
        ttl_seconds: int = 3,
    ) -> tuple[dict, Path]:
        state_path, config_path = self.lease_paths()
        job = bg.enqueue_job(
            command,
            cwd_value=str(ROOT),
            labels=[],
            timeout_seconds=5,
            stale_after_seconds=10,
            lease_request={
                "task_id": TASK,
                "session_id": SESSION,
                "owner": "opencode",
                "scope": SCOPE,
                "codememory_config": str(config_path),
                "worktree_path": str(ROOT),
                "oc_bin": "oc",
                "state_path": str(state_path),
                "ttl_seconds": ttl_seconds,
            },
            retry_policy={
                "max_attempts": max_attempts,
                "retry_safe": retry_safe,
            },
            max_log_bytes=max_log_bytes,
        )
        assert job is not None
        return job, config_path

    def reserve_and_claim(
        self, job: dict, config_path: Path
    ) -> tuple[bg.LeaseIdentity, dict]:
        with patch.object(
            bg,
            "make_oc_runner",
            return_value=self.source_runner(config_path),
        ):
            _, leased, _ = bg._reserve_jobs(
                job_id=job["id"], max_jobs=1, lease_max_concurrency=1
            )
            identity, status = bg._claim_reserved_attempt(leased[0])
        self.assertEqual("starting", status)
        assert identity is not None
        current = bg._snapshot_job(job["id"])
        assert current is not None
        return identity, current

    def run_bg(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "background_task_manager.py"), *arguments],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )

    def enqueue(self, *command: str, timeout_seconds: int = 10) -> str:
        result = self.run_bg(
            "enqueue",
            "--timeout-seconds",
            str(timeout_seconds),
            "--",
            *command,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        for line in result.stdout.splitlines():
            if line.startswith("id: "):
                return line.removeprefix("id: ").strip()
        self.fail(f"enqueue did not return an id: {result.stdout}")

    def read_job(self, job_id: str) -> dict:
        result = self.run_bg("read", job_id, "--json")
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)["job"]

    def test_jobs_transaction_does_not_commit_failed_mutation(self) -> None:
        jobs_path = self.bg_root / "jobs.json"
        with self.patched_store():
            bg.ensure_store()
            before = jobs_path.read_bytes()
            with (
                self.assertRaisesRegex(RuntimeError, "stop"),
                bg.locked_jobs(writeback=True) as data,
            ):
                data["jobs"].append({"id": "must-not-commit"})
                raise RuntimeError("stop")
            self.assertEqual(before, jobs_path.read_bytes())

    def test_atomic_publish_reports_post_replace_commit_ambiguity(self) -> None:
        target = self.root / "state.json"
        with (
            patch.object(bg.os, "fsync", side_effect=[None, OSError("dir sync")]),
            self.assertRaises(bg.BackgroundStoreError) as raised,
        ):
            bg._atomic_write_json(target, {"version": 1})
        self.assertEqual("bg_store_commit_indeterminate", raised.exception.reason_code)
        self.assertEqual({"version": 1}, json.loads(target.read_text(encoding="utf-8")))

    def test_gate_marker_failure_never_executes_command(self) -> None:
        read_fd, write_fd = os.pipe()
        os.close(write_fd)
        with (
            patch.object(
                bg,
                "_write_gate_marker",
                side_effect=bg.BackgroundStoreError(
                    "bg_store_write_failed", "failed"
                ),
            ),
            self.assertRaises(bg.BackgroundStoreError),
        ):
                bg._run_lease_gate(
                    read_fd,
                    self.root / "gate.json",
                    "bg_test",
                    "attempt_test",
                    "raise AssertionError('must not execute')",
                )

    def test_concurrent_runners_execute_one_legacy_reservation(self) -> None:
        marker = self.root / "executions.txt"
        job_id = self.enqueue(
            sys.executable,
            "-c",
            (
                "import pathlib,time; "
                f"p=pathlib.Path({str(marker)!r}); "
                "time.sleep(0.4); "
                "p.write_text((p.read_text() if p.exists() else '')+'run\\n')"
            ),
        )
        command = [
            sys.executable,
            str(SCRIPTS / "background_task_manager.py"),
            "run",
            "--id",
            job_id,
        ]
        first = subprocess.Popen(
            command,
            cwd=ROOT,
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        second = subprocess.Popen(
            command,
            cwd=ROOT,
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        first.communicate(timeout=10)
        second.communicate(timeout=10)
        self.assertEqual("run\n", marker.read_text(encoding="utf-8"))
        self.assertEqual("completed", self.read_job(job_id)["status"])

    def test_legacy_natural_exit_contains_background_descendants(self) -> None:
        child_pid_path = self.root / "legacy-child.pid"
        child_code = "import time; time.sleep(30)"
        parent_code = (
            "import pathlib,subprocess,sys; "
            f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}]); "
            f"pathlib.Path({str(child_pid_path)!r}).write_text(str(p.pid))"
        )
        job_id = self.enqueue(sys.executable, "-c", parent_code)
        result = self.run_bg("run", "--id", job_id)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("completed", self.read_job(job_id)["status"])
        child_pid = int(child_pid_path.read_text(encoding="utf-8"))
        for _ in range(100):
            if not bg.is_pid_alive(child_pid):
                break
            time.sleep(0.03)
        self.assertFalse(bg.is_pid_alive(child_pid))

    def test_cancellation_cannot_be_overwritten_by_runner(self) -> None:
        marker = self.root / "completed.txt"
        child_pid_path = self.root / "cancel-child.pid"
        job_id = self.enqueue(
            sys.executable,
            "-c",
            (
                "import pathlib,subprocess,sys,time; "
                "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
                f"pathlib.Path({str(child_pid_path)!r}).write_text(str(child.pid)); "
                "time.sleep(30); "
                f"pathlib.Path({str(marker)!r}).write_text('completed')"
            ),
            timeout_seconds=60,
        )
        runner = subprocess.Popen(
            [
                sys.executable,
                str(SCRIPTS / "background_task_manager.py"),
                "run",
                "--id",
                job_id,
            ],
            cwd=ROOT,
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(100):
            job = self.read_job(job_id)
            if job.get("status") == "running" and job.get("pid"):
                break
            time.sleep(0.03)
        else:
            runner.kill()
            self.fail("runner did not publish a PID")
        for _ in range(100):
            if child_pid_path.exists():
                break
            time.sleep(0.03)
        else:
            runner.kill()
            self.fail("command did not publish its child PID")

        cancelled = self.run_bg("cancel", job_id)
        self.assertEqual(0, cancelled.returncode, cancelled.stderr)
        runner.communicate(timeout=10)
        self.assertEqual("cancelled", self.read_job(job_id)["status"])
        self.assertFalse(marker.exists())
        child_pid = int(child_pid_path.read_text(encoding="utf-8"))
        for _ in range(100):
            if not bg.is_pid_alive(child_pid):
                break
            time.sleep(0.03)
        self.assertFalse(bg.is_pid_alive(child_pid))

    def test_cancel_containment_failure_stays_reconciling(self) -> None:
        job_id = self.enqueue(sys.executable, "-c", "pass")
        jobs_path = self.bg_root / "jobs.json"
        with self.patched_store():
            with bg.locked_jobs(writeback=True) as data:
                job = bg.find_job(data, job_id)
                assert job is not None
                job.update(
                    {
                        "status": "running",
                        "pid": 12345,
                        "pgid": 12345,
                        "process_start_fingerprint": "reused-process",
                        "run_token": "reserved",
                    }
                )
            with (
                patch.object(bg, "terminate_process", return_value="identity-mismatch"),
                patch.object(bg, "is_process_group_alive", return_value=True),
            ):
                self.assertEqual(
                    1,
                    bg.command_cancel(argparse.Namespace(id=job_id)),
                )
            job = json.loads(jobs_path.read_text(encoding="utf-8"))["jobs"][0]
            self.assertEqual("reconciling", job["status"])
            self.assertEqual(12345, job["pgid"])

    def test_cancel_between_legacy_spawn_and_pid_publish_never_opens_gate(self) -> None:
        command_marker = self.root / "legacy-command-ran"
        spawned = threading.Event()
        proceed = threading.Event()
        with self.patched_store():
            job = bg.enqueue_job(
                [
                    sys.executable,
                    "-c",
                    f"import pathlib; pathlib.Path({str(command_marker)!r}).write_text('ran')",
                ],
                cwd_value=str(ROOT),
                labels=[],
                timeout_seconds=10,
                stale_after_seconds=30,
            )
            assert job is not None
            legacy, _, _ = bg._reserve_jobs(
                job_id=job["id"], max_jobs=1, lease_max_concurrency=1
            )
            real_publish = bg._publish_legacy_process

            def delayed_publish(*args, **kwargs):
                spawned.set()
                self.assertTrue(proceed.wait(timeout=5))
                return real_publish(*args, **kwargs)

            with (
                patch.object(bg, "_publish_legacy_process", side_effect=delayed_publish),
                ThreadPoolExecutor(max_workers=1) as executor,
            ):
                future = executor.submit(bg._run_single_job, legacy[0])
                self.assertTrue(spawned.wait(timeout=5))
                self.assertEqual(
                    1,
                    bg.command_cancel(argparse.Namespace(id=job["id"])),
                )
                during = bg._snapshot_job(job["id"])
                assert during is not None
                self.assertEqual("reconciling", during["status"])
                self.assertTrue(during["run_token"])
                proceed.set()
                self.assertEqual("cancelled", future.result(timeout=10)[0])
            self.assertFalse(command_marker.exists())
            final = bg._snapshot_job(job["id"])
            assert final is not None
            self.assertEqual("cancelled", final["status"])

    def test_stale_cleanup_during_legacy_pid_publish_never_opens_gate(self) -> None:
        command_marker = self.root / "stale-command-ran"
        spawned = threading.Event()
        proceed = threading.Event()
        with self.patched_store():
            job = bg.enqueue_job(
                [
                    sys.executable,
                    "-c",
                    f"import pathlib; pathlib.Path({str(command_marker)!r}).write_text('ran')",
                ],
                cwd_value=str(ROOT),
                labels=[],
                timeout_seconds=10,
                stale_after_seconds=1,
            )
            assert job is not None
            legacy, _, _ = bg._reserve_jobs(
                job_id=job["id"], max_jobs=1, lease_max_concurrency=1
            )
            with bg.locked_jobs(writeback=True) as data:
                stored = bg.find_job(data, job["id"])
                assert stored is not None
                stored["started_at"] = "2000-01-01T00:00:00Z"
            real_publish = bg._publish_legacy_process

            def delayed_publish(*args, **kwargs):
                spawned.set()
                self.assertTrue(proceed.wait(timeout=5))
                return real_publish(*args, **kwargs)

            with (
                patch.object(bg, "_publish_legacy_process", side_effect=delayed_publish),
                ThreadPoolExecutor(max_workers=1) as executor,
            ):
                future = executor.submit(bg._run_single_job, legacy[0])
                self.assertTrue(spawned.wait(timeout=5))
                with bg.locked_jobs(writeback=True) as data:
                    cleanup = bg.cleanup_jobs(data)
                self.assertEqual(1, cleanup["stale_reconciling"])
                during = bg._snapshot_job(job["id"])
                assert during is not None
                self.assertEqual("reconciling", during["status"])
                self.assertTrue(during["run_token"])
                proceed.set()
                self.assertEqual("cancelled", future.result(timeout=10)[0])
            self.assertFalse(command_marker.exists())

    def test_lease_capacity_is_separate_and_atomic(self) -> None:
        with self.patched_store(), patch.object(bg, "LEASE_EXECUTION_ENABLED", True):
            for value in ("one", "two", "three"):
                self.enqueue_lease([sys.executable, "-c", f"print({value!r})"])
            legacy, leased, _ = bg._reserve_jobs(
                job_id=None,
                max_jobs=None,
                lease_max_concurrency=2,
            )
            self.assertEqual([], legacy)
            self.assertEqual(2, len(leased))
            _, second, _ = bg._reserve_jobs(
                job_id=None,
                max_jobs=None,
                lease_max_concurrency=2,
            )
            self.assertEqual([], second)

    def test_lease_job_writes_gate_receipt_and_bounded_log(self) -> None:
        with (
            self.patched_store(),
            patch.object(bg, "LEASE_EXECUTION_ENABLED", True),
        ):
            job, config_path = self.enqueue_lease(
                [sys.executable, "-c", "print('x' * 4096)"],
                max_log_bytes=128,
            )
            with patch.object(
                bg,
                "make_oc_runner",
                return_value=self.source_runner(config_path),
            ):
                _, leased, _ = bg._reserve_jobs(
                    job_id=job["id"],
                    max_jobs=1,
                    lease_max_concurrency=2,
                )
                status, exit_code = bg._run_lease_job(leased[0])
            self.assertEqual(("completed", 0), (status, exit_code))
            completed = bg._snapshot_job(job["id"])
            assert completed is not None
            self.assertEqual("completed", completed["status"])
            self.assertEqual("succeeded", completed["attempts"][0]["status"])
            self.assertTrue(completed["attempts"][0]["log_truncated"])
            self.assertEqual(
                "effect_possible",
                json.loads(
                    Path(completed["attempts"][0]["gate_path"]).read_text(
                        encoding="utf-8"
                    )
                )["state"],
            )
            receipt = json.loads(
                Path(completed["attempts"][0]["receipt_path"]).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("terminal", receipt["status"])
            self.assertEqual("succeeded", receipt["attempt_status"])
            self.assertLessEqual(Path(completed["log_path"]).stat().st_size, 128)
            self.assertEqual(
                0,
                leases.lease_status(state_path=self.root / "leases.json")["count"],
            )

    def test_retry_keeps_failed_attempts_terminal(self) -> None:
        with (
            self.patched_store(),
            patch.object(bg, "LEASE_EXECUTION_ENABLED", True),
        ):
            job, config_path = self.enqueue_lease(
                [sys.executable, "-c", "raise SystemExit(7)"],
                max_attempts=2,
                retry_safe=True,
            )
            with patch.object(
                bg,
                "make_oc_runner",
                return_value=self.source_runner(config_path),
            ):
                _, first, _ = bg._reserve_jobs(
                    job_id=job["id"], max_jobs=1, lease_max_concurrency=1
                )
                self.assertEqual("queued", bg._run_lease_job(first[0])[0])
                after_first = bg._snapshot_job(job["id"])
                assert after_first is not None
                self.assertEqual("failed", after_first["attempts"][0]["status"])
                _, second, _ = bg._reserve_jobs(
                    job_id=job["id"], max_jobs=1, lease_max_concurrency=1
                )
                self.assertEqual("failed", bg._run_lease_job(second[0])[0])
            final = bg._snapshot_job(job["id"])
            assert final is not None
            self.assertEqual("failed", final["status"])
            self.assertEqual(["failed", "failed"], [a["status"] for a in final["attempts"]])

    def test_heartbeat_loss_quarantines_effect_possible_attempt(self) -> None:
        with (
            self.patched_store(),
            patch.object(bg, "LEASE_EXECUTION_ENABLED", True),
        ):
            job, config_path = self.enqueue_lease(
                [sys.executable, "-c", "import time; time.sleep(2)"],
            )
            with (
                patch.object(
                    bg,
                    "make_oc_runner",
                    return_value=self.source_runner(config_path),
                ),
                patch.object(
                    bg,
                    "heartbeat_lease",
                    side_effect=leases.TaskLeaseError(
                        "task_lease_holder_mismatch", "lost"
                    ),
                ),
            ):
                _, leased, _ = bg._reserve_jobs(
                    job_id=job["id"], max_jobs=1, lease_max_concurrency=1
                )
                status, _ = bg._run_lease_job(leased[0])
            self.assertEqual("reconciling", status)
            current = bg._snapshot_job(job["id"])
            assert current is not None
            self.assertEqual("reconciling", current["status"])
            self.assertEqual("unknown", current["attempts"][0]["status"])

    def test_reconcile_gate_aborted_proves_no_effect(self) -> None:
        with (
            self.patched_store(),
            patch.object(bg, "LEASE_EXECUTION_ENABLED", True),
        ):
            job, config_path = self.enqueue_lease(
                [sys.executable, "-c", "raise AssertionError('must not run')"],
            )
            with patch.object(
                bg,
                "make_oc_runner",
                return_value=self.source_runner(config_path),
            ):
                _, leased, _ = bg._reserve_jobs(
                    job_id=job["id"], max_jobs=1, lease_max_concurrency=1
                )
                identity, status = bg._claim_reserved_attempt(leased[0])
            self.assertEqual("starting", status)
            assert identity is not None
            current = bg._snapshot_job(job["id"])
            assert current is not None
            attempt = bg.current_attempt(current)
            assert attempt is not None
            with bg.locked_jobs(writeback=True) as data:
                stored = bg.find_job(data, job["id"])
                assert stored is not None
                stored_attempt = bg.current_attempt(stored)
                assert stored_attempt is not None
                stored_attempt["status"] = "running"
                stored_attempt["worker_pid"] = 2**30
                stored_attempt["pid"] = 2**30
                stored_attempt["pgid"] = 2**30
                stored_attempt["process_start_fingerprint"] = "dead-process"
            bg._write_gate_marker(
                Path(attempt["gate_path"]),
                "gate_aborted",
                job_id=job["id"],
                attempt_id=attempt["id"],
                pid=2**30,
                process_start_fingerprint="dead-process",
            )
            report = bg.reconcile_lease_jobs()
            self.assertEqual(1, report["failed"])
            reconciled = bg._snapshot_job(job["id"])
            assert reconciled is not None
            self.assertEqual("failed", reconciled["status"])
            self.assertEqual("known_no_effect", reconciled["attempts"][0]["outcome_confidence"])

    def test_reconcile_adopts_terminal_receipt_under_exact_lease(self) -> None:
        with (
            self.patched_store(),
            patch.object(bg, "LEASE_EXECUTION_ENABLED", True),
        ):
            job, config_path = self.enqueue_lease(
                [sys.executable, "-c", "print('already-finished')"],
            )
            with patch.object(
                bg,
                "make_oc_runner",
                return_value=self.source_runner(config_path),
            ):
                _, leased, _ = bg._reserve_jobs(
                    job_id=job["id"], max_jobs=1, lease_max_concurrency=1
                )
                identity, _ = bg._claim_reserved_attempt(leased[0])
            assert identity is not None
            current = bg._snapshot_job(job["id"])
            assert current is not None
            attempt = bg.current_attempt(current)
            assert attempt is not None
            with bg.locked_jobs(writeback=True) as data:
                stored = bg.find_job(data, job["id"])
                assert stored is not None
                stored_attempt = bg.current_attempt(stored)
                assert stored_attempt is not None
                stored_attempt["status"] = "running"
                stored_attempt["worker_pid"] = 2**30
                stored_attempt["pid"] = 2**30
                stored_attempt["pgid"] = 2**30
                stored_attempt["process_start_fingerprint"] = "dead-process"
            current = bg._snapshot_job(job["id"])
            assert current is not None
            attempt = bg.current_attempt(current)
            assert attempt is not None
            bg._write_gate_marker(
                Path(attempt["gate_path"]),
                "effect_possible",
                job_id=job["id"],
                attempt_id=attempt["id"],
                pid=2**30,
                process_start_fingerprint="dead-process",
            )
            Path(attempt["log_path"]).write_bytes(b"")
            receipt = bg._prepared_receipt(current, attempt, identity)
            receipt["receipt_path"] = attempt["receipt_path"]
            receipt["started_at"] = bg.to_iso(bg.now_utc())
            receipt["process_start_fingerprint"] = "dead-process"
            bg._write_terminal_receipt(
                receipt,
                attempt_status="succeeded",
                outcome_confidence="known_process_outcome",
                process=SimpleNamespace(pid=2**30),  # type: ignore[arg-type]
                exit_code=0,
                timed_out=False,
                cancelled=False,
                lease_lost=False,
                gate_state="effect_possible",
                log_result={"bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()},
            )
            report = bg.reconcile_lease_jobs()
            self.assertEqual(1, report["inspected"])
            reconciled = bg._snapshot_job(job["id"])
            assert reconciled is not None
            self.assertEqual("completed", reconciled["status"])
            self.assertEqual("succeeded", reconciled["attempts"][0]["status"])

    def test_reconcile_quarantines_receipt_with_stale_lease_identity(self) -> None:
        with (
            self.patched_store(),
            patch.object(bg, "LEASE_EXECUTION_ENABLED", True),
        ):
            job, config_path = self.enqueue_lease(
                [sys.executable, "-c", "print('forged')"],
            )
            identity, current = self.reserve_and_claim(job, config_path)
            attempt = bg.current_attempt(current)
            assert attempt is not None
            with bg.locked_jobs(writeback=True) as data:
                stored = bg.find_job(data, job["id"])
                assert stored is not None
                stored_attempt = bg.current_attempt(stored)
                assert stored_attempt is not None
                stored_attempt.update(
                    {
                        "status": "running",
                        "worker_pid": 2**30,
                        "pid": 2**30,
                        "pgid": 2**30,
                        "process_start_fingerprint": "dead-process",
                    }
                )
            current = bg._snapshot_job(job["id"])
            assert current is not None
            attempt = bg.current_attempt(current)
            assert attempt is not None
            bg._write_gate_marker(
                Path(attempt["gate_path"]),
                "effect_possible",
                job_id=job["id"],
                attempt_id=attempt["id"],
                pid=2**30,
                process_start_fingerprint="dead-process",
            )
            Path(attempt["log_path"]).write_bytes(b"")
            receipt = bg._prepared_receipt(current, attempt, identity)
            receipt["started_at"] = bg.to_iso(bg.now_utc())
            receipt["process_start_fingerprint"] = "dead-process"
            terminal, _ = bg._write_terminal_receipt(
                receipt,
                attempt_status="succeeded",
                outcome_confidence="known_process_outcome",
                process=SimpleNamespace(pid=2**30),  # type: ignore[arg-type]
                exit_code=0,
                timed_out=False,
                cancelled=False,
                lease_lost=False,
                gate_state="effect_possible",
                log_result={"bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()},
            )
            forged_log = dict(terminal)
            forged_log["log_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "log digest or byte count"):
                bg._validate_terminal_receipt(
                    current,
                    attempt,
                    identity,
                    forged_log,
                )
            terminal["lease"] = dict(terminal["lease"])
            terminal["lease"]["lease_id"] = "forged-lease"
            bg._atomic_write_json(Path(attempt["receipt_path"]), terminal)
            report = bg.reconcile_lease_jobs()
            self.assertEqual(1, report["reconciling"])
            quarantined = bg._snapshot_job(job["id"])
            assert quarantined is not None
            self.assertEqual("reconciling", quarantined["status"])
            bg._best_effort_release(identity, self.root / "leases.json")

    def test_lease_cancellation_wins_terminal_race(self) -> None:
        with (
            self.patched_store(),
            patch.object(bg, "LEASE_EXECUTION_ENABLED", True),
        ):
            job, config_path = self.enqueue_lease(
                [sys.executable, "-c", "import time; time.sleep(5)"],
            )
            with patch.object(
                bg,
                "make_oc_runner",
                return_value=self.source_runner(config_path),
            ):
                _, leased, _ = bg._reserve_jobs(
                    job_id=job["id"], max_jobs=1, lease_max_concurrency=1
                )
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(bg._run_lease_job, leased[0])
                    for _ in range(100):
                        current = bg._snapshot_job(job["id"])
                        if current is not None and current.get("pid"):
                            break
                        time.sleep(0.03)
                    else:
                        self.fail("lease worker did not publish a PID")
                    self.assertEqual(
                        0,
                        bg.command_cancel(argparse.Namespace(id=job["id"])),
                    )
                    self.assertIn(
                        future.result(timeout=10)[0],
                        {"cancelled", "reconciling"},
                    )
            cancelled = bg._snapshot_job(job["id"])
            assert cancelled is not None
            self.assertEqual("cancelled", cancelled["status"])
            self.assertIn(
                cancelled["attempts"][0]["status"],
                {"cancelled", "unknown"},
            )

    def test_natural_exit_contains_background_descendants(self) -> None:
        child_pid_path = self.root / "child.pid"
        child_code = "import time; time.sleep(30)"
        parent_code = (
            "import pathlib,subprocess,sys; "
            f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}]); "
            f"pathlib.Path({str(child_pid_path)!r}).write_text(str(p.pid))"
        )
        with (
            self.patched_store(),
            patch.object(bg, "LEASE_EXECUTION_ENABLED", True),
        ):
            job, config_path = self.enqueue_lease(
                [sys.executable, "-c", parent_code],
            )
            with patch.object(
                bg,
                "make_oc_runner",
                return_value=self.source_runner(config_path),
            ):
                _, leased, _ = bg._reserve_jobs(
                    job_id=job["id"], max_jobs=1, lease_max_concurrency=1
                )
                status, exit_code = bg._run_lease_job(leased[0])
            self.assertEqual(("completed", 0), (status, exit_code))
            child_pid = int(child_pid_path.read_text(encoding="utf-8"))
            for _ in range(100):
                if not bg.is_pid_alive(child_pid):
                    break
                time.sleep(0.03)
            self.assertFalse(bg.is_pid_alive(child_pid))

    def test_reconcile_contains_expired_attempt_despite_live_worker_pid(self) -> None:
        with (
            self.patched_store(),
            patch.object(bg, "LEASE_EXECUTION_ENABLED", True),
        ):
            job, config_path = self.enqueue_lease(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                ttl_seconds=1,
            )
            identity, current = self.reserve_and_claim(job, config_path)
            attempt = bg.current_attempt(current)
            assert attempt is not None
            child = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                start_new_session=True,
            )
            try:
                process_start = bg.process_start_fingerprint(child.pid)
                assert process_start is not None
                worker_start = bg.process_start_fingerprint(os.getpid())
                assert worker_start is not None
                with bg.locked_jobs(writeback=True) as data:
                    stored = bg.find_job(data, job["id"])
                    assert stored is not None
                    stored_attempt = bg.current_attempt(stored)
                    assert stored_attempt is not None
                    stored_attempt.update(
                        {
                            "status": "running",
                            "worker_pid": os.getpid(),
                            "worker_start_fingerprint": worker_start,
                            "heartbeat_at": "2000-01-01T00:00:00Z",
                            "pid": child.pid,
                            "pgid": child.pid,
                            "process_start_fingerprint": process_start,
                        }
                    )
                    stored["pid"] = child.pid
                    stored["pgid"] = child.pid
                bg._write_gate_marker(
                    Path(attempt["gate_path"]),
                    "effect_possible",
                    job_id=job["id"],
                    attempt_id=attempt["id"],
                    pid=child.pid,
                    process_start_fingerprint=process_start,
                )
                time.sleep(1.1)
                report = bg.reconcile_lease_jobs()
                self.assertEqual(1, report["reconciling"])
                child.wait(timeout=5)
                self.assertFalse(bg.is_process_group_alive(child.pid))
                reconciled = bg._snapshot_job(job["id"])
                assert reconciled is not None
                self.assertEqual("reconciling", reconciled["status"])
            finally:
                if child.poll() is None:
                    bg.terminate_process(child.pid, child.pid)
                    child.wait(timeout=5)
                bg._best_effort_release(identity, self.root / "leases.json")

    def test_log_drain_failure_cannot_publish_success(self) -> None:
        def fail_drain(stream, _path, _max_bytes, result) -> None:
            stream.read()
            stream.close()
            result["error"] = "forced drain failure"

        with (
            self.patched_store(),
            patch.object(bg, "LEASE_EXECUTION_ENABLED", True),
        ):
            job, config_path = self.enqueue_lease(
                [sys.executable, "-c", "pass"],
            )
            with (
                patch.object(
                    bg,
                    "make_oc_runner",
                    return_value=self.source_runner(config_path),
                ),
                patch.object(bg, "_drain_bounded_output", side_effect=fail_drain),
            ):
                _, leased, _ = bg._reserve_jobs(
                    job_id=job["id"], max_jobs=1, lease_max_concurrency=1
                )
                status, _ = bg._run_lease_job(leased[0])
            self.assertEqual("reconciling", status)
            current = bg._snapshot_job(job["id"])
            assert current is not None
            self.assertEqual("reconciling", current["status"])

    def test_stale_fence_cannot_requeue_prestart_attempt(self) -> None:
        with (
            self.patched_store(),
            patch.object(bg, "LEASE_EXECUTION_ENABLED", True),
        ):
            job, config_path = self.enqueue_lease(
                [sys.executable, "-c", "pass"],
                max_attempts=2,
                retry_safe=True,
            )
            identity, current = self.reserve_and_claim(job, config_path)
            attempt = bg.current_attempt(current)
            assert attempt is not None
            bg.release_lease(identity, state_path=self.root / "leases.json")
            status = bg._finish_prestart_attempt(
                job["id"],
                attempt["id"],
                failure_class="test_fence_loss",
                summary="must not retry",
                identity=identity,
                state_path=self.root / "leases.json",
            )
            self.assertEqual("reconciling", status)
            current = bg._snapshot_job(job["id"])
            assert current is not None
            self.assertEqual("reconciling", current["status"])
            self.assertNotEqual("queued", current["status"])


if __name__ == "__main__":
    unittest.main()
