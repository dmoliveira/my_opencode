from __future__ import annotations

import json
import multiprocessing
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import task_lease_command as leases

SCOPE = "dmoliveira/my_opencode"
TASK = "task_128"
SESSION = "session_69"
BASE_TIME = 2_000_000_000_000


def source_runner(
    config_path: Path,
    cwd: Path,
    *,
    task_id: str = TASK,
    session_id: str = SESSION,
    scope: str = SCOPE,
    task_status: str = "doing",
    backend: str = "sqlite",
):
    def run(_arguments: list[str], operation: str) -> dict[str, object]:
        if operation == "task_lease_codememory_doctor":
            return {
                "status": "ok",
                "runtime_ready": True,
                "config_path": str(config_path.resolve()),
                "backend": backend,
                "database_path": str(config_path.with_name("codememory.sqlite3")),
                "database_url_scheme": None,
            }
        if operation == "task_lease_codememory_current":
            return {
                "scope_key": scope,
                "worktree_path": str(cwd.resolve()),
                "session_id": session_id,
                "session_outcome": "active",
                "session_stale": False,
                "task_id": task_id,
            }
        if operation == "task_lease_codememory_get":
            return {
                "id": task_id,
                "type": "task",
                "scope_key": scope,
                "status": task_status,
            }
        raise AssertionError(f"unexpected operation: {operation}")

    return run


def claim_for_test(
    state_path: Path,
    config_path: Path,
    cwd: Path,
    *,
    owner: str = "opencode",
    worker_id: str = "worker-a",
    task_id: str = TASK,
    session_id: str = SESSION,
    now_ms: int = BASE_TIME,
    ttl_seconds: int = 10,
) -> dict[str, object]:
    return leases.claim_lease(
        task_id=task_id,
        session_id=session_id,
        owner=owner,
        worker_id=worker_id,
        scope=SCOPE,
        ttl_seconds=ttl_seconds,
        runner=source_runner(
            config_path, cwd, task_id=task_id, session_id=session_id
        ),
        config_path=config_path,
        cwd=cwd,
        state_path=state_path,
        clock=lambda: now_ms,
    )


def identity_from_report(report: dict[str, object]) -> leases.LeaseIdentity:
    lease = report["lease"]
    assert isinstance(lease, dict)
    return leases.LeaseIdentity(
        task_id=str(lease["task_id"]),
        session_id=str(lease["session_id"]),
        owner=str(lease["owner"]),
        worker_id=str(lease["worker_id"]),
        lease_id=str(lease["lease_id"]),
        fencing_token=int(lease["fencing_token"]),
    )


def process_claim_worker(
    start,
    results,
    state_path: str,
    config_path: str,
    cwd: str,
    owner: str,
) -> None:
    try:
        if not start.wait(timeout=10):
            results.put(("worker_timeout", None))
            return
        report = claim_for_test(
            Path(state_path),
            Path(config_path),
            Path(cwd),
            owner=owner,
            worker_id=f"worker-{owner}",
        )
        results.put((str(report["reason_code"]), report["lease"]))
    except leases.TaskLeaseError as exc:
        results.put((exc.reason_code, None))


def process_delayed_claim_worker(
    source_started,
    release_source,
    results,
    state_path: str,
    config_path: str,
    cwd: str,
) -> None:
    task_id = "task_129"
    session_id = "session_74"
    base_runner = source_runner(
        Path(config_path), Path(cwd), task_id=task_id, session_id=session_id
    )

    def delayed_runner(
        arguments: list[str], operation: str
    ) -> dict[str, object]:
        if operation == "task_lease_codememory_doctor":
            source_started.set()
            if not release_source.wait(timeout=10):
                raise RuntimeError("source probe was not released")
        return base_runner(arguments, operation)

    try:
        report = leases.claim_lease(
            task_id=task_id,
            session_id=session_id,
            owner="opencode",
            worker_id="worker-delayed",
            scope=SCOPE,
            ttl_seconds=10,
            runner=delayed_runner,
            config_path=Path(config_path),
            cwd=Path(cwd),
            state_path=Path(state_path),
            clock=lambda: BASE_TIME + 1500,
        )
        results.put((str(report["reason_code"]), None))
    except leases.TaskLeaseError as exc:
        results.put((exc.reason_code, None))
    except RuntimeError as exc:
        results.put(("worker_error", str(exc)))


def process_heartbeat_worker(
    results,
    state_path: str,
    identity_values: tuple[str, str, str, str, str, int],
) -> None:
    try:
        report = leases.heartbeat_lease(
            leases.LeaseIdentity(*identity_values),
            ttl_seconds=2,
            state_path=Path(state_path),
            clock=lambda: BASE_TIME + 1000,
        )
        results.put((str(report["reason_code"]), None))
    except leases.TaskLeaseError as exc:
        results.put((exc.reason_code, None))


def process_hold_store_lock(acquired, release, released, state_path: str) -> None:
    try:
        with leases._locked_store(Path(state_path)):
            acquired.set()
            if not release.wait(timeout=10):
                raise RuntimeError("store lock was not released")
    finally:
        released.set()


def crash_after_replace_worker(
    state_path: str,
    identity_values: tuple[str, str, str, str, str, int],
    target_kind: str,
) -> None:
    state = Path(state_path).resolve(strict=False)
    target_path = (
        state if target_kind == "state" else state.with_name(f"{state.name}.journal")
    )
    real_replace = os.replace

    def replace_then_exit(source, target) -> None:
        real_replace(source, target)
        if Path(target) == target_path:
            os._exit(23 if target_kind == "state" else 24)

    leases.os.replace = replace_then_exit
    identity = leases.LeaseIdentity(*identity_values)
    leases.heartbeat_lease(
        identity,
        ttl_seconds=20,
        state_path=state,
        clock=lambda: BASE_TIME + 100,
    )


class TaskLeaseCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        leases._FAULTED_PATHS.clear()

    def paths(self, root: Path) -> tuple[Path, Path]:
        config_path = root / "config.sqlite.yaml"
        config_path.write_text("database:\n  backend: sqlite\n", encoding="utf-8")
        return root / "leases.json", config_path

    def test_claim_heartbeat_check_release_and_epoch_high_water(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-lifecycle-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            claimed = claim_for_test(state_path, config_path, root)
            identity = identity_from_report(claimed)
            self.assertEqual(1, identity.fencing_token)

            checked = leases.check_lease(
                identity, state_path=state_path, clock=lambda: BASE_TIME + 100
            )
            self.assertEqual("task_lease_valid", checked["reason_code"])
            heartbeat = leases.heartbeat_lease(
                identity,
                ttl_seconds=20,
                state_path=state_path,
                clock=lambda: BASE_TIME + 500,
            )
            self.assertEqual(
                "task_lease_heartbeat_recorded", heartbeat["reason_code"]
            )
            released = leases.release_lease(
                identity, state_path=state_path, clock=lambda: BASE_TIME + 600
            )
            self.assertEqual("task_lease_released", released["reason_code"])

            reclaimed = claim_for_test(
                state_path,
                config_path,
                root,
                worker_id="worker-b",
                now_ms=BASE_TIME + 700,
            )
            self.assertEqual(2, identity_from_report(reclaimed).fencing_token)
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(2, persisted["epochs"][TASK])
            self.assertEqual(0o600, stat.S_IMODE(state_path.stat().st_mode))
            self.assertEqual(
                0o600,
                stat.S_IMODE(state_path.with_name("leases.json.lock").stat().st_mode),
            )
            self.assertEqual(
                0o600,
                stat.S_IMODE(
                    state_path.with_name("leases.json.journal").stat().st_mode
                ),
            )

    def test_expiry_equality_reclaims_and_rejects_stale_worker(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-expiry-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            first = claim_for_test(
                state_path, config_path, root, ttl_seconds=1
            )
            first_identity = identity_from_report(first)
            with self.assertRaises(leases.TaskLeaseError) as expired:
                leases.check_lease(
                    first_identity,
                    state_path=state_path,
                    clock=lambda: BASE_TIME + 1000,
                )
            self.assertEqual("task_lease_expired", expired.exception.reason_code)

            second = claim_for_test(
                state_path,
                config_path,
                root,
                owner="other",
                worker_id="worker-b",
                now_ms=BASE_TIME + 1000,
            )
            self.assertTrue(second["reclaimed"])
            self.assertEqual(2, identity_from_report(second).fencing_token)
            with self.assertRaises(leases.TaskLeaseError) as stale:
                leases.check_lease(
                    first_identity,
                    state_path=state_path,
                    clock=lambda: BASE_TIME + 1001,
                )
            self.assertEqual("task_lease_holder_mismatch", stale.exception.reason_code)
            stale_calls = (
                lambda now: leases.heartbeat_lease(
                    first_identity,
                    ttl_seconds=10,
                    state_path=state_path,
                    clock=lambda: now,
                ),
                lambda now: leases.release_lease(
                    first_identity, state_path=state_path, clock=lambda: now
                ),
                lambda now: leases.guarded_local_commit(
                    first_identity,
                    lambda: None,
                    state_path=state_path,
                    clock=lambda: now,
                ),
            )
            for offset, stale_call in enumerate(stale_calls, start=2):
                with self.subTest(stale_call=stale_call):
                    with self.assertRaises(leases.TaskLeaseError) as rejected:
                        stale_call(BASE_TIME + 1000 + offset)
                    self.assertEqual(
                        "task_lease_holder_mismatch", rejected.exception.reason_code
                    )

    def test_same_worker_claim_retry_is_idempotent_and_advances_clock_floor(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-idempotent-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            first = claim_for_test(state_path, config_path, root)
            before = state_path.read_bytes()
            second = claim_for_test(
                state_path, config_path, root, now_ms=BASE_TIME + 10
            )
            self.assertTrue(second["idempotent"])
            self.assertEqual(first["lease"], second["lease"])
            self.assertNotEqual(before, state_path.read_bytes())
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(BASE_TIME + 10, persisted["clock_floor_ms"])

    def test_concurrent_claim_has_one_winner(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-race-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            context = multiprocessing.get_context("spawn")
            start = context.Event()
            results = context.Queue()
            workers = [
                context.Process(
                    target=process_claim_worker,
                    args=(
                        start,
                        results,
                        str(state_path),
                        str(config_path),
                        str(root),
                        owner,
                    ),
                )
                for owner in ("one", "two")
            ]
            for worker in workers:
                worker.start()
            start.set()
            rows = [results.get(timeout=30) for _ in workers]
            for worker in workers:
                worker.join(timeout=30)
                self.assertFalse(worker.is_alive())
                self.assertEqual(0, worker.exitcode)
            self.assertEqual(
                ["task_lease_already_claimed", "task_lease_claimed"],
                sorted(row[0] for row in rows),
            )
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(1, persisted["epochs"][TASK])

    def test_delayed_source_probe_does_not_block_another_heartbeat(self) -> None:
        if "spawn" not in multiprocessing.get_all_start_methods():
            self.skipTest("spawn process context unavailable")
        with tempfile.TemporaryDirectory(prefix="task-lease-source-contention-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            initial = claim_for_test(
                state_path, config_path, root, ttl_seconds=2
            )
            identity = identity_from_report(initial)
            context = multiprocessing.get_context("spawn")
            source_started = context.Event()
            release_source = context.Event()
            claim_results = context.Queue()
            heartbeat_results = context.Queue()
            delayed_claim = context.Process(
                target=process_delayed_claim_worker,
                args=(
                    source_started,
                    release_source,
                    claim_results,
                    str(state_path),
                    str(config_path),
                    str(root),
                ),
            )
            heartbeat = context.Process(
                target=process_heartbeat_worker,
                args=(
                    heartbeat_results,
                    str(state_path),
                    (
                        identity.task_id,
                        identity.session_id,
                        identity.owner,
                        identity.worker_id,
                        identity.lease_id,
                        identity.fencing_token,
                    ),
                ),
            )
            delayed_claim.start()
            try:
                self.assertTrue(source_started.wait(timeout=10))
                heartbeat.start()
                heartbeat_result = heartbeat_results.get(timeout=3)
                self.assertEqual(
                    "task_lease_heartbeat_recorded", heartbeat_result[0]
                )
            finally:
                release_source.set()
                delayed_claim.join(timeout=10)
                heartbeat.join(timeout=10)
                if delayed_claim.is_alive():
                    delayed_claim.terminate()
                    delayed_claim.join(timeout=10)
                if heartbeat.is_alive():
                    heartbeat.terminate()
                    heartbeat.join(timeout=10)
            self.assertFalse(delayed_claim.is_alive())
            self.assertFalse(heartbeat.is_alive())
            self.assertEqual(0, delayed_claim.exitcode)
            self.assertEqual(0, heartbeat.exitcode)
            self.assertEqual(
                "task_lease_claimed", claim_results.get(timeout=10)[0]
            )

    def test_claim_revalidates_after_lock_contention(self) -> None:
        if "spawn" not in multiprocessing.get_all_start_methods():
            self.skipTest("spawn process context unavailable")
        with tempfile.TemporaryDirectory(prefix="task-lease-lock-retry-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            claim_for_test(state_path, config_path, root)
            context = multiprocessing.get_context("spawn")
            acquired = context.Event()
            release = context.Event()
            released = context.Event()
            holder = context.Process(
                target=process_hold_store_lock,
                args=(acquired, release, released, str(state_path)),
            )
            holder.start()
            self.assertTrue(acquired.wait(timeout=10))
            source_checks = 0
            task_id = "task_129"
            session_id = "session_74"
            base_runner = source_runner(
                config_path, root, task_id=task_id, session_id=session_id
            )

            def retrying_runner(
                arguments: list[str], operation: str
            ) -> dict[str, object]:
                nonlocal source_checks
                if operation == "task_lease_codememory_doctor":
                    source_checks += 1
                    if source_checks == 2:
                        release.set()
                        if not released.wait(timeout=10):
                            raise RuntimeError("store lock holder did not release")
                return base_runner(arguments, operation)

            try:
                with patch.object(leases, "CLAIM_LOCK_WAIT_SECONDS", 0.05):
                    report = leases.claim_lease(
                        task_id=task_id,
                        session_id=session_id,
                        owner="opencode",
                        worker_id="worker-retry",
                        scope=SCOPE,
                        ttl_seconds=10,
                        runner=retrying_runner,
                        config_path=config_path,
                        cwd=root,
                        state_path=state_path,
                        clock=lambda: BASE_TIME + 10,
                    )
            finally:
                release.set()
                holder.join(timeout=10)
                if holder.is_alive():
                    holder.terminate()
                    holder.join(timeout=10)
            self.assertFalse(holder.is_alive())
            self.assertEqual(0, holder.exitcode)
            self.assertEqual(2, source_checks)
            self.assertEqual("task_lease_claimed", report["reason_code"])

    def test_retry_rejects_changed_source_without_committing(self) -> None:
        if "spawn" not in multiprocessing.get_all_start_methods():
            self.skipTest("spawn process context unavailable")
        with tempfile.TemporaryDirectory(prefix="task-lease-retry-source-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            claim_for_test(state_path, config_path, root)
            before = state_path.read_bytes()
            context = multiprocessing.get_context("spawn")
            acquired = context.Event()
            release = context.Event()
            released = context.Event()
            holder = context.Process(
                target=process_hold_store_lock,
                args=(acquired, release, released, str(state_path)),
            )
            holder.start()
            self.assertTrue(acquired.wait(timeout=10))
            source_checks = 0
            task_id = "task_129"
            session_id = "session_74"
            base_runner = source_runner(
                config_path, root, task_id=task_id, session_id=session_id
            )

            def changing_runner(
                arguments: list[str], operation: str
            ) -> dict[str, object]:
                nonlocal source_checks
                if operation == "task_lease_codememory_doctor":
                    source_checks += 1
                    if source_checks == 2:
                        release.set()
                        if not released.wait(timeout=10):
                            raise RuntimeError("store lock holder did not release")
                payload = base_runner(arguments, operation)
                if source_checks == 2 and operation == "task_lease_codememory_current":
                    payload["session_id"] = "session_changed"
                return payload

            try:
                with (
                    patch.object(leases, "CLAIM_LOCK_WAIT_SECONDS", 0.05),
                    self.assertRaises(leases.TaskLeaseError) as raised,
                ):
                    leases.claim_lease(
                        task_id=task_id,
                        session_id=session_id,
                        owner="opencode",
                        worker_id="worker-retry",
                        scope=SCOPE,
                        ttl_seconds=10,
                        runner=changing_runner,
                        config_path=config_path,
                        cwd=root,
                        state_path=state_path,
                        clock=lambda: BASE_TIME + 10,
                    )
            finally:
                release.set()
                holder.join(timeout=10)
                if holder.is_alive():
                    holder.terminate()
                    holder.join(timeout=10)
            self.assertFalse(holder.is_alive())
            self.assertEqual(0, holder.exitcode)
            self.assertEqual(2, source_checks)
            self.assertEqual("task_lease_source_invalid", raised.exception.reason_code)
            self.assertEqual(before, state_path.read_bytes())

    def test_stale_authority_sample_revalidates_before_commit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-stale-authority-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            claim_for_test(state_path, config_path, root)
            before = state_path.read_bytes()
            source_checks = 0
            task_id = "task_129"
            session_id = "session_74"
            base_runner = source_runner(
                config_path, root, task_id=task_id, session_id=session_id
            )

            def changing_runner(
                arguments: list[str], operation: str
            ) -> dict[str, object]:
                nonlocal source_checks
                if operation == "task_lease_codememory_doctor":
                    source_checks += 1
                payload = base_runner(arguments, operation)
                if source_checks == 2 and operation == "task_lease_codememory_current":
                    payload["session_id"] = "session_changed"
                return payload

            monotonic_samples = [
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                2.0,
                2.0,
                2.0,
                2.0,
                2.0,
                2.0,
                2.0,
                2.0,
                2.0,
            ]
            with (
                patch.object(
                    leases.time, "monotonic", side_effect=monotonic_samples
                ),
                self.assertRaises(leases.TaskLeaseError) as raised,
            ):
                leases.claim_lease(
                    task_id=task_id,
                    session_id=session_id,
                    owner="opencode",
                    worker_id="worker-stale",
                    scope=SCOPE,
                    ttl_seconds=10,
                    runner=changing_runner,
                    config_path=config_path,
                    cwd=root,
                    state_path=state_path,
                    clock=lambda: BASE_TIME + 10,
                )
            self.assertEqual(2, source_checks)
            self.assertEqual("task_lease_source_invalid", raised.exception.reason_code)
            self.assertEqual(before, state_path.read_bytes())

    def test_contention_retry_exhaustion_preserves_store(self) -> None:
        if "spawn" not in multiprocessing.get_all_start_methods():
            self.skipTest("spawn process context unavailable")
        with tempfile.TemporaryDirectory(prefix="task-lease-retry-exhaustion-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            claim_for_test(state_path, config_path, root)
            before = state_path.read_bytes()
            context = multiprocessing.get_context("spawn")
            acquired = context.Event()
            release = context.Event()
            released = context.Event()
            holder = context.Process(
                target=process_hold_store_lock,
                args=(acquired, release, released, str(state_path)),
            )
            holder.start()
            self.assertTrue(acquired.wait(timeout=10))
            source_checks = 0
            task_id = "task_129"
            session_id = "session_74"
            base_runner = source_runner(
                config_path, root, task_id=task_id, session_id=session_id
            )

            def counting_runner(
                arguments: list[str], operation: str
            ) -> dict[str, object]:
                nonlocal source_checks
                if operation == "task_lease_codememory_doctor":
                    source_checks += 1
                return base_runner(arguments, operation)

            try:
                with (
                    patch.object(leases, "CLAIM_LOCK_WAIT_SECONDS", 0.05),
                    patch.object(leases, "CLAIM_MAX_ATTEMPTS", 2),
                    self.assertRaises(leases.TaskLeaseError) as raised,
                ):
                    leases.claim_lease(
                        task_id=task_id,
                        session_id=session_id,
                        owner="opencode",
                        worker_id="worker-retry",
                        scope=SCOPE,
                        ttl_seconds=10,
                        runner=counting_runner,
                        config_path=config_path,
                        cwd=root,
                        state_path=state_path,
                        clock=lambda: BASE_TIME + 10,
                    )
            finally:
                release.set()
                holder.join(timeout=10)
                if holder.is_alive():
                    holder.terminate()
                    holder.join(timeout=10)
            self.assertFalse(holder.is_alive())
            self.assertEqual(0, holder.exitcode)
            self.assertEqual(2, source_checks)
            self.assertEqual(
                "task_lease_admission_contended", raised.exception.reason_code
            )
            self.assertEqual(
                {"attempts": 2, "retryable": True}, raised.exception.context
            )
            self.assertEqual(before, state_path.read_bytes())

    def test_source_must_match_active_current_context_and_doing_task(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-source-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            with self.assertRaises(leases.TaskLeaseError) as raised:
                leases.claim_lease(
                    task_id=TASK,
                    session_id=SESSION,
                    owner="opencode",
                    worker_id="worker-a",
                    scope=SCOPE,
                    ttl_seconds=10,
                    runner=source_runner(
                        config_path, root, task_status="not-started"
                    ),
                    config_path=config_path,
                    cwd=root,
                    state_path=state_path,
                    clock=lambda: BASE_TIME,
                )
            self.assertEqual("task_lease_source_invalid", raised.exception.reason_code)
            self.assertFalse(state_path.exists())

    def test_empty_store_initializes_before_unlocked_source_preflight(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-empty-preflight-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            base_runner = source_runner(config_path, root)
            lock_path = state_path.with_name(f"{state_path.name}.lock")
            journal_path = state_path.with_name(f"{state_path.name}.journal")

            def inspecting_runner(
                arguments: list[str], operation: str
            ) -> dict[str, object]:
                if operation == "task_lease_codememory_doctor":
                    self.assertTrue(lock_path.is_file())
                    self.assertTrue(journal_path.is_file())
                    with leases._locked_store(state_path) as store:
                        self.assertIsNone(store.state)
                return base_runner(arguments, operation)

            report = leases.claim_lease(
                task_id=TASK,
                session_id=SESSION,
                owner="opencode",
                worker_id="worker-a",
                scope=SCOPE,
                ttl_seconds=10,
                runner=inspecting_runner,
                config_path=config_path,
                cwd=root,
                state_path=state_path,
                clock=lambda: BASE_TIME,
            )
            self.assertEqual("task_lease_claimed", report["reason_code"])

    def test_source_context_switch_during_sample_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-source-switch-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            stable_runner = source_runner(config_path, root)
            current_calls = 0

            def switching_runner(
                arguments: list[str], operation: str
            ) -> dict[str, object]:
                nonlocal current_calls
                payload = stable_runner(arguments, operation)
                if operation == "task_lease_codememory_current":
                    current_calls += 1
                    if current_calls == 2:
                        payload["task_id"] = "task_other"
                return payload

            with self.assertRaises(leases.TaskLeaseError) as raised:
                leases.claim_lease(
                    task_id=TASK,
                    session_id=SESSION,
                    owner="opencode",
                    worker_id="worker-a",
                    scope=SCOPE,
                    ttl_seconds=10,
                    runner=switching_runner,
                    config_path=config_path,
                    cwd=root,
                    state_path=state_path,
                    clock=lambda: BASE_TIME,
                )
            self.assertEqual("task_lease_source_changed", raised.exception.reason_code)
            self.assertFalse(state_path.exists())

    def test_source_rejects_postgres_placeholders_and_sqlite_override(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-source-binding-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            with self.assertRaises(leases.TaskLeaseError) as postgres:
                leases.claim_lease(
                    task_id=TASK,
                    session_id=SESSION,
                    owner="opencode",
                    worker_id="worker-a",
                    scope=SCOPE,
                    ttl_seconds=10,
                    runner=source_runner(config_path, root, backend="postgres"),
                    config_path=config_path,
                    cwd=root,
                    state_path=state_path,
                    clock=lambda: BASE_TIME,
                )
            self.assertEqual(
                "task_lease_backend_unsupported", postgres.exception.reason_code
            )

            config_path.write_text(
                "database:\n  backend: sqlite\n  path: ${LEASE_DB_PATH}\n",
                encoding="utf-8",
            )
            with self.assertRaises(leases.TaskLeaseError) as placeholder:
                claim_for_test(state_path, config_path, root)
            self.assertEqual(
                "task_lease_source_unsupported", placeholder.exception.reason_code
            )

            config_path.write_text("database:\n  backend: sqlite\n", encoding="utf-8")
            with (
                patch.dict(
                    os.environ, {"CODEMEMORY_SQLITE_PATH": str(root / "other.db")}
                ),
                self.assertRaises(leases.TaskLeaseError) as override,
            ):
                claim_for_test(state_path, config_path, root)
            self.assertEqual(
                "task_lease_source_unsupported", override.exception.reason_code
            )

    def test_config_change_during_source_sample_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-config-race-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            stable_runner = source_runner(config_path, root)

            def changing_runner(
                arguments: list[str], operation: str
            ) -> dict[str, object]:
                payload = stable_runner(arguments, operation)
                if operation == "task_lease_codememory_get":
                    config_path.write_text(
                        "database:\n  backend: sqlite\n  path: replaced.db\n",
                        encoding="utf-8",
                    )
                return payload

            with self.assertRaises(leases.TaskLeaseError) as raised:
                leases.claim_lease(
                    task_id=TASK,
                    session_id=SESSION,
                    owner="opencode",
                    worker_id="worker-a",
                    scope=SCOPE,
                    ttl_seconds=10,
                    runner=changing_runner,
                    config_path=config_path,
                    cwd=root,
                    state_path=state_path,
                    clock=lambda: BASE_TIME,
                )
            self.assertEqual("task_lease_source_changed", raised.exception.reason_code)

    def test_backend_fingerprint_rejects_config_drift(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-backend-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            claim_for_test(state_path, config_path, root, ttl_seconds=1)
            before = state_path.read_bytes()
            config_path.write_text(
                "database:\n  backend: sqlite\n  path: other.sqlite3\n",
                encoding="utf-8",
            )
            with self.assertRaises(leases.TaskLeaseError) as raised:
                claim_for_test(
                    state_path,
                    config_path,
                    root,
                    owner="other",
                    worker_id="worker-b",
                    now_ms=BASE_TIME + 1000,
                )
            self.assertEqual("task_lease_backend_mismatch", raised.exception.reason_code)
            self.assertEqual(before, state_path.read_bytes())

    def test_clock_rollback_fails_closed_and_recovery_invalidates_leases(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-clock-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            claimed = claim_for_test(state_path, config_path, root)
            with self.assertRaises(leases.TaskLeaseError) as raised:
                leases.check_lease(
                    identity_from_report(claimed),
                    state_path=state_path,
                    clock=lambda: BASE_TIME - 1,
                )
            self.assertEqual("task_lease_clock_rollback", raised.exception.reason_code)
            recovered = leases.recover_clock_rollback(
                state_path=state_path, clock=lambda: BASE_TIME - 100
            )
            self.assertEqual(1, recovered["invalidated_lease_count"])
            status = leases.lease_status(
                state_path=state_path, clock=lambda: BASE_TIME - 100
            )
            self.assertEqual(0, status["count"])

    def test_observed_time_past_expiry_cannot_roll_back_into_validity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-observed-clock-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            identity = identity_from_report(
                claim_for_test(state_path, config_path, root, ttl_seconds=1)
            )
            status = leases.lease_status(
                state_path=state_path, clock=lambda: BASE_TIME + 2000
            )
            self.assertTrue(status["leases"][0]["expired"])
            with self.assertRaises(leases.TaskLeaseError) as raised:
                leases.check_lease(
                    identity,
                    state_path=state_path,
                    clock=lambda: BASE_TIME + 1500,
                )
            self.assertEqual("task_lease_clock_rollback", raised.exception.reason_code)

    def test_guarded_commit_rejects_reentry_and_preserves_lease_on_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-guard-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            identity = identity_from_report(claim_for_test(state_path, config_path, root))

            def reenter() -> None:
                leases.guarded_local_commit(
                    identity,
                    lambda: None,
                    state_path=state_path,
                    clock=lambda: BASE_TIME + 1,
                )

            with self.assertRaises(leases.TaskLeaseError) as nested:
                leases.guarded_local_commit(
                    identity,
                    reenter,
                    state_path=state_path,
                    clock=lambda: BASE_TIME + 1,
                )
            self.assertEqual("task_lease_reentry", nested.exception.reason_code)

            reentrant_calls = (
                lambda: leases.check_lease(
                    identity, state_path=state_path, clock=lambda: BASE_TIME + 2
                ),
                lambda: leases.heartbeat_lease(
                    identity,
                    ttl_seconds=10,
                    state_path=state_path,
                    clock=lambda: BASE_TIME + 2,
                ),
                lambda: leases.release_lease(
                    identity, state_path=state_path, clock=lambda: BASE_TIME + 2
                ),
                lambda: leases.lease_status(
                    state_path=state_path, clock=lambda: BASE_TIME + 2
                ),
            )
            for reentrant_call in reentrant_calls:
                with self.subTest(reentrant_call=reentrant_call):
                    with self.assertRaises(leases.TaskLeaseError) as rejected:
                        leases.guarded_local_commit(
                            identity,
                            reentrant_call,
                            state_path=state_path,
                            clock=lambda: BASE_TIME + 2,
                        )
                    self.assertEqual(
                        "task_lease_reentry", rejected.exception.reason_code
                    )
            nested = root / "nested"
            nested.mkdir()
            alias_path = nested / ".." / state_path.name
            with self.assertRaises(leases.TaskLeaseError) as alias_reentry:
                leases.guarded_local_commit(
                    identity,
                    lambda: leases.lease_status(
                        state_path=alias_path, clock=lambda: BASE_TIME + 2
                    ),
                    state_path=state_path,
                    clock=lambda: BASE_TIME + 2,
                )
            self.assertEqual(
                "task_lease_reentry", alias_reentry.exception.reason_code
            )

            def fail() -> None:
                raise RuntimeError("local commit failed")

            with self.assertRaisesRegex(RuntimeError, "local commit failed"):
                leases.guarded_local_commit(
                    identity,
                    fail,
                    state_path=state_path,
                    clock=lambda: BASE_TIME + 2,
                )
            checked = leases.check_lease(
                identity, state_path=state_path, clock=lambda: BASE_TIME + 3
            )
            self.assertEqual("task_lease_valid", checked["reason_code"])

    def test_unlock_failure_does_not_leave_reentry_marker(self) -> None:
        import fcntl

        with tempfile.TemporaryDirectory(prefix="task-lease-unlock-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            claim_for_test(state_path, config_path, root)
            real_flock = fcntl.flock

            def fail_unlock(descriptor: int, operation: int) -> None:
                if operation == fcntl.LOCK_UN:
                    raise OSError("unlock failed")
                real_flock(descriptor, operation)

            with (
                patch("fcntl.flock", side_effect=fail_unlock),
                self.assertRaises(OSError),
            ):
                leases.lease_status(state_path=state_path, clock=lambda: BASE_TIME)

            status = leases.lease_status(state_path=state_path, clock=lambda: BASE_TIME)
            self.assertEqual("task_lease_status", status["reason_code"])

    def test_directory_fsync_failure_faults_store_until_explicit_recovery(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-fsync-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            identity = identity_from_report(claim_for_test(state_path, config_path, root))
            with (
                patch.object(
                    leases, "_fsync_directory", side_effect=OSError("fsync failed")
                ),
                self.assertRaises(leases.TaskLeaseError) as raised,
            ):
                leases.heartbeat_lease(
                    identity,
                    ttl_seconds=20,
                    state_path=state_path,
                    clock=lambda: BASE_TIME + 100,
                )
            self.assertEqual(
                "task_lease_commit_indeterminate", raised.exception.reason_code
            )
            with self.assertRaises(leases.TaskLeaseError) as blocked:
                leases.check_lease(
                    identity,
                    state_path=state_path,
                    clock=lambda: BASE_TIME + 101,
                )
            self.assertEqual(
                "task_lease_commit_indeterminate", blocked.exception.reason_code
            )
            recovered = leases.recover_indeterminate_store(state_path=state_path)
            self.assertEqual(
                "task_lease_indeterminate_recovered", recovered["reason_code"]
            )
            self.assertEqual(1, recovered["invalidated_lease_count"])
            with self.assertRaises(leases.TaskLeaseError) as invalidated:
                leases.check_lease(
                    identity,
                    state_path=state_path,
                    clock=lambda: BASE_TIME + 102,
                )
            self.assertEqual("task_lease_not_found", invalidated.exception.reason_code)

    def test_new_nested_state_directory_is_private_and_synced(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-nested-state-") as raw:
            root = Path(raw)
            _unused_state_path, config_path = self.paths(root)
            state_directory = root / "private" / "nested"
            state_path = state_directory / "leases.json"
            canonical_root = root.resolve()
            canonical_state_directory = state_directory.resolve()
            fsynced: list[Path] = []
            real_fsync_directory = leases._fsync_directory

            def record_fsync(path: Path) -> None:
                fsynced.append(path)
                real_fsync_directory(path)

            with patch.object(
                leases, "_fsync_directory", side_effect=record_fsync
            ):
                claim_for_test(state_path, config_path, root)

            self.assertEqual(0o700, stat.S_IMODE((root / "private").stat().st_mode))
            self.assertEqual(0o700, stat.S_IMODE(state_directory.stat().st_mode))
            self.assertIn(canonical_root, fsynced)
            self.assertIn(canonical_root / "private", fsynced)
            self.assertIn(canonical_state_directory, fsynced)

    def test_nested_directory_sync_failure_retries_before_any_claim(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-nested-fsync-") as raw:
            root = Path(raw)
            _unused_state_path, config_path = self.paths(root)
            state_path = root / "private" / "nested" / "leases.json"
            canonical_root = root.resolve()
            real_fsync_directory = leases._fsync_directory

            def fail_root_sync(path: Path) -> None:
                if path == canonical_root:
                    raise OSError("root directory sync failed")
                real_fsync_directory(path)

            with (
                patch.object(
                    leases, "_fsync_directory", side_effect=fail_root_sync
                ),
                self.assertRaises(leases.TaskLeaseError) as raised,
            ):
                claim_for_test(state_path, config_path, root)
            self.assertEqual("task_lease_state_path_unsafe", raised.exception.reason_code)
            self.assertFalse(state_path.exists())

            claimed = claim_for_test(state_path, config_path, root)
            self.assertEqual("task_lease_claimed", claimed["reason_code"])

    def test_existing_shared_state_directory_is_rejected_without_chmod(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-shared-state-") as raw:
            root = Path(raw)
            state_directory = root / "shared"
            state_directory.mkdir(mode=0o700)
            state_directory.chmod(0o755)
            state_path = state_directory / "leases.json"

            with self.assertRaises(leases.TaskLeaseError) as raised:
                leases.lease_status(state_path=state_path, clock=lambda: BASE_TIME)
            self.assertEqual("task_lease_state_path_unsafe", raised.exception.reason_code)
            self.assertEqual(0o755, stat.S_IMODE(state_directory.stat().st_mode))

    def test_symlinked_state_parent_uses_one_canonical_store(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-parent-symlink-") as raw:
            root = Path(raw)
            _unused_state_path, config_path = self.paths(root)
            state_directory = root / "canonical"
            state_directory.mkdir(mode=0o700)
            state_directory.chmod(0o700)
            alias = root / "alias"
            alias.symlink_to(state_directory, target_is_directory=True)
            alias_state_path = alias / "leases.json"
            canonical_state_path = state_directory / "leases.json"

            claimed = claim_for_test(alias_state_path, config_path, root)
            checked = leases.check_lease(
                identity_from_report(claimed),
                state_path=canonical_state_path,
                clock=lambda: BASE_TIME + 1,
            )
            self.assertEqual("task_lease_valid", checked["reason_code"])
            self.assertTrue(canonical_state_path.is_file())

    def test_cli_rejects_relative_default_state_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-relative-state-") as raw:
            root = Path(raw)
            environment = {
                **os.environ,
                "MY_OPENCODE_TASK_LEASE_PATH": "relative/leases.json",
            }
            completed = subprocess.run(
                [sys.executable, str(SCRIPTS / "task_lease_command.py"), "doctor", "--json"],
                cwd=root,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(1, completed.returncode)
            payload = json.loads(completed.stdout)
            self.assertEqual("FAIL", payload["result"])
            self.assertEqual("task_lease_state_path_unsafe", payload["reason_code"])
            self.assertFalse((root / "relative").exists())

    def test_clean_journal_fsync_failure_persists_cross_process_fault(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-clean-fsync-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            claim_for_test(state_path, config_path, root)
            real_fsync_directory = leases._fsync_directory
            calls = 0

            def fail_clean_journal_fsync(path: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 4:
                    raise OSError("clean journal fsync failed")
                real_fsync_directory(path)

            with (
                patch.object(
                    leases,
                    "_fsync_directory",
                    side_effect=fail_clean_journal_fsync,
                ),
                self.assertRaises(leases.TaskLeaseError) as raised,
            ):
                leases.lease_status(
                    state_path=state_path, clock=lambda: BASE_TIME + 100
                )
            self.assertEqual(
                "task_lease_commit_indeterminate", raised.exception.reason_code
            )
            leases._FAULTED_PATHS.clear()
            with self.assertRaises(leases.TaskLeaseError) as persisted:
                leases.lease_status(
                    state_path=state_path, clock=lambda: BASE_TIME + 100
                )
            self.assertEqual(
                "task_lease_commit_indeterminate", persisted.exception.reason_code
            )
            self.assertTrue(state_path.with_name("leases.json.fault").is_file())
            leases.recover_indeterminate_store(state_path=state_path)

    def test_process_death_after_state_replace_leaves_indeterminate_journal(self) -> None:
        if "spawn" not in multiprocessing.get_all_start_methods():
            self.skipTest("spawn process context unavailable")
        with tempfile.TemporaryDirectory(prefix="task-lease-crash-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            identity = identity_from_report(claim_for_test(state_path, config_path, root))
            context = multiprocessing.get_context("spawn")
            worker = context.Process(
                target=crash_after_replace_worker,
                args=(
                    str(state_path),
                    (
                        identity.task_id,
                        identity.session_id,
                        identity.owner,
                        identity.worker_id,
                        identity.lease_id,
                        identity.fencing_token,
                    ),
                    "state",
                ),
            )
            worker.start()
            worker.join(timeout=30)
            self.assertFalse(worker.is_alive())
            self.assertEqual(23, worker.exitcode)
            with self.assertRaises(leases.TaskLeaseError) as raised:
                leases.lease_status(state_path=state_path, clock=lambda: BASE_TIME)
            self.assertEqual(
                "task_lease_commit_indeterminate", raised.exception.reason_code
            )

    def test_process_death_after_journal_replace_is_recoverable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-journal-crash-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            identity = identity_from_report(claim_for_test(state_path, config_path, root))
            context = multiprocessing.get_context("spawn")
            worker = context.Process(
                target=crash_after_replace_worker,
                args=(
                    str(state_path),
                    (
                        identity.task_id,
                        identity.session_id,
                        identity.owner,
                        identity.worker_id,
                        identity.lease_id,
                        identity.fencing_token,
                    ),
                    "journal",
                ),
            )
            worker.start()
            worker.join(timeout=30)
            self.assertFalse(worker.is_alive())
            self.assertEqual(24, worker.exitcode)
            with self.assertRaises(leases.TaskLeaseError) as raised:
                leases.lease_status(state_path=state_path, clock=lambda: BASE_TIME + 101)
            self.assertEqual(
                "task_lease_commit_indeterminate", raised.exception.reason_code
            )
            recovered = leases.recover_indeterminate_store(state_path=state_path)
            self.assertEqual(1, recovered["invalidated_lease_count"])

    def test_malformed_journal_requires_and_allows_explicit_recovery(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-journal-recovery-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            claim_for_test(state_path, config_path, root)
            journal_path = state_path.with_name("leases.json.journal")
            journal_path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(leases.TaskLeaseError) as raised:
                leases.lease_status(state_path=state_path, clock=lambda: BASE_TIME + 1)
            self.assertEqual("task_lease_journal_invalid", raised.exception.reason_code)
            recovered = leases.recover_indeterminate_store(state_path=state_path)
            self.assertEqual(1, recovered["invalidated_lease_count"])
            self.assertEqual(
                0,
                leases.lease_status(
                    state_path=state_path, clock=lambda: BASE_TIME + 1
                )["count"],
            )

    def test_state_tampering_and_symlink_paths_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-tamper-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            claim_for_test(state_path, config_path, root)
            original = state_path.read_bytes()
            state_path.write_bytes(original + b" ")
            with self.assertRaises(leases.TaskLeaseError) as mismatch:
                leases.lease_status(state_path=state_path, clock=lambda: BASE_TIME)
            self.assertEqual(
                "task_lease_state_journal_mismatch", mismatch.exception.reason_code
            )
            self.assertEqual(original + b" ", state_path.read_bytes())

            symlink_path = root / "symlink.json"
            target = root / "target.json"
            target.write_text("{}\n", encoding="utf-8")
            target.chmod(0o600)
            symlink_path.symlink_to(target)
            with self.assertRaises(leases.TaskLeaseError) as unsafe:
                leases.lease_status(state_path=symlink_path, clock=lambda: BASE_TIME)
            self.assertEqual("task_lease_state_path_unsafe", unsafe.exception.reason_code)

    def test_live_runner_uses_only_bounded_read_only_source_commands(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-lease-live-source-") as raw:
            root = Path(raw)
            state_path, config_path = self.paths(root)
            log_path = root / "calls.jsonl"
            fake_oc = root / "oc"
            fake_oc.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, pathlib, sys\n"
                "args = sys.argv[1:]\n"
                "config = args[args.index('--config') + 1]\n"
                "command = next(x for x in args if x in {'config', 'current', 'get'})\n"
                "with pathlib.Path(os.environ['FAKE_OC_LOG']).open('a', encoding='utf-8') as h: h.write(json.dumps(args) + '\\n')\n"
                "if command == 'config': payload = {'status':'ok','runtime_ready':True,'config_path':config,'backend':'sqlite','database_path':str(pathlib.Path(config).with_name('codememory.sqlite3')),'database_url_scheme':None}\n"
                f"elif command == 'current': payload = {{'scope_key':'{SCOPE}','worktree_path':os.getcwd(),'session_id':'{SESSION}','session_outcome':'active','session_stale':False,'task_id':'{TASK}'}}\n"
                f"else: payload = {{'id':'{TASK}','type':'task','scope_key':'{SCOPE}','status':'doing'}}\n"
                "print(json.dumps(payload))\n",
                encoding="utf-8",
            )
            fake_oc.chmod(0o755)
            runner = leases.make_oc_runner(
                oc_bin=str(fake_oc), config_path=config_path, cwd=root
            )
            with patch.dict(os.environ, {"FAKE_OC_LOG": str(log_path)}):
                report = leases.claim_lease(
                    task_id=TASK,
                    session_id=SESSION,
                    owner="opencode",
                    worker_id="worker-a",
                    scope=SCOPE,
                    ttl_seconds=10,
                    runner=runner,
                    config_path=config_path,
                    cwd=root,
                    state_path=state_path,
                    clock=lambda: BASE_TIME,
                )
            self.assertEqual("task_lease_claimed", report["reason_code"])
            calls = [json.loads(line) for line in log_path.read_text().splitlines()]
            self.assertEqual(4, len(calls))
            flattened = [item for call in calls for item in call]
            self.assertNotIn("resume", flattened)
            self.assertIn("current", flattened)
            self.assertIn("get", flattened)
            self.assertIn("--doctor", flattened)


if __name__ == "__main__":
    unittest.main()
