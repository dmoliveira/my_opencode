from __future__ import annotations

import fcntl
import json
import os
import stat
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import background_task_manager as bg
import session_sidecar_security as sidecar


class BackgroundLockSecurityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bg-lock-security-")
        self.root = Path(self.temporary.name)
        self.store = self.root / "bg"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_store(self) -> None:
        self.store.mkdir(mode=0o700)
        (self.store / "runs").mkdir(mode=0o700)
        jobs = self.store / "jobs.json"
        jobs.write_text(json.dumps({"version": 1, "jobs": []}), encoding="utf-8")
        jobs.chmod(0o600)

    @contextmanager
    def patched_store(self):
        with patch.multiple(
            bg,
            BG_ROOT=self.store,
            JOBS_PATH=self.store / "jobs.json",
            LOCK_PATH=self.store / "jobs.lock",
            RUNS_DIR=self.store / "runs",
        ):
            yield

    def assert_lock_refused(self) -> None:
        with (
            self.patched_store(),
            self.assertRaises(bg.BackgroundStoreError) as caught,
            bg.locked_jobs(writeback=False),
        ):
            self.fail("unsafe lock was accepted")
        self.assertEqual("bg_store_lock_unsafe", caught.exception.reason_code)

    def test_symlinked_lock_never_changes_external_file(self) -> None:
        self.make_store()
        victim = self.root / "external"
        victim.write_bytes(b"synthetic external data")
        victim.chmod(0o644)
        lock = self.store / "jobs.lock"
        lock.symlink_to(victim)
        before = (victim.read_bytes(), victim.stat().st_ino, stat.S_IMODE(victim.stat().st_mode))
        self.assert_lock_refused()
        self.assertTrue(lock.is_symlink())
        self.assertEqual(before, (victim.read_bytes(), victim.stat().st_ino, stat.S_IMODE(victim.stat().st_mode)))

    def test_unsafe_lock_is_refused_before_store_initialization(self) -> None:
        self.store.mkdir(mode=0o700)
        victim = self.root / "external"
        victim.write_bytes(b"synthetic external data")
        victim.chmod(0o644)
        (self.store / "jobs.lock").symlink_to(victim)
        self.assert_lock_refused()
        self.assertFalse((self.store / "jobs.json").exists())
        self.assertFalse((self.store / "runs").exists())
        self.assertEqual(b"synthetic external data", victim.read_bytes())
        self.assertEqual(0o644, stat.S_IMODE(victim.stat().st_mode))

    def test_hardlinked_lock_never_changes_external_file(self) -> None:
        self.make_store()
        victim = self.root / "external"
        victim.write_bytes(b"synthetic external data")
        victim.chmod(0o644)
        os.link(victim, self.store / "jobs.lock")
        before = (victim.read_bytes(), victim.stat().st_ino, stat.S_IMODE(victim.stat().st_mode))
        self.assert_lock_refused()
        self.assertEqual(before, (victim.read_bytes(), victim.stat().st_ino, stat.S_IMODE(victim.stat().st_mode)))

    def test_existing_nonprivate_lock_is_not_repaired(self) -> None:
        self.make_store()
        lock = self.store / "jobs.lock"
        lock.write_bytes(b"synthetic existing lock")
        lock.chmod(0o644)
        before = (lock.read_bytes(), lock.stat().st_ino, stat.S_IMODE(lock.stat().st_mode))
        self.assert_lock_refused()
        self.assertEqual(before, (lock.read_bytes(), lock.stat().st_ino, stat.S_IMODE(lock.stat().st_mode)))

    def test_fifo_lock_is_rejected_without_chmod_or_flock(self) -> None:
        self.make_store()
        lock = self.store / "jobs.lock"
        os.mkfifo(lock, 0o644)
        before = stat.S_IMODE(lock.stat().st_mode)
        with patch.object(fcntl, "flock", side_effect=AssertionError("FIFO must not be locked")):
            self.assert_lock_refused()
        self.assertEqual(before, stat.S_IMODE(lock.stat().st_mode))
        self.assertTrue(stat.S_ISFIFO(lock.stat().st_mode))

    def test_symlinked_store_is_rejected_before_initialization(self) -> None:
        external = self.root / "external-store"
        external.mkdir(mode=0o700)
        marker = external / "marker"
        marker.write_bytes(b"synthetic external data")
        self.store.symlink_to(external, target_is_directory=True)
        before = sorted(path.name for path in external.iterdir())
        self.assert_lock_refused()
        self.assertEqual(before, sorted(path.name for path in external.iterdir()))
        self.assertEqual(b"synthetic external data", marker.read_bytes())

    def test_existing_private_lock_is_used_without_chmod(self) -> None:
        self.make_store()
        lock = self.store / "jobs.lock"
        lock.write_bytes(b"synthetic existing lock")
        lock.chmod(0o600)
        with (
            self.patched_store(),
            patch.object(sidecar.os, "fchmod", wraps=os.fchmod) as chmod,
            bg.locked_jobs(writeback=False) as data,
        ):
            self.assertEqual([], data["jobs"])
        chmod.assert_not_called()
        self.assertEqual(b"synthetic existing lock", lock.read_bytes())
        self.assertEqual(0o600, stat.S_IMODE(lock.stat().st_mode))

    def test_foreign_owned_lock_is_refused_without_changes(self) -> None:
        self.make_store()
        lock = self.store / "jobs.lock"
        lock.write_bytes(b"synthetic lock")
        lock.chmod(0o600)
        metadata = lock.stat()
        foreign = SimpleNamespace(
            st_mode=metadata.st_mode,
            st_uid=metadata.st_uid + 1,
            st_nlink=metadata.st_nlink,
        )
        with patch.object(sidecar, "_raw_target_stat", return_value=foreign):
            self.assert_lock_refused()
        self.assertEqual(b"synthetic lock", lock.read_bytes())
        self.assertEqual(0o600, stat.S_IMODE(lock.stat().st_mode))

    def test_concurrent_nonprivate_lock_is_refused_without_repair(self) -> None:
        self.make_store()
        lock = self.store / "jobs.lock"
        real_stat = sidecar._raw_target_stat
        appeared = False

        def appear_before_exclusive_open(authority):
            nonlocal appeared
            if not appeared:
                appeared = True
                lock.write_bytes(b"synthetic concurrent lock")
                lock.chmod(0o644)
                return None
            return real_stat(authority)

        with patch.object(sidecar, "_raw_target_stat", side_effect=appear_before_exclusive_open):
            self.assert_lock_refused()
        self.assertTrue(appeared)
        self.assertEqual(b"synthetic concurrent lock", lock.read_bytes())
        self.assertEqual(0o644, stat.S_IMODE(lock.stat().st_mode))

    def test_lock_timeout_has_a_distinct_reason_before_initialization(self) -> None:
        @contextmanager
        def timeout(*_args, **_kwargs):
            raise sidecar.SidecarSecurityError(
                "session_sidecar_lock_timeout", "synthetic timeout", phase="lock"
            )
            yield

        with (
            self.patched_store(),
            patch.object(sidecar, "secure_sidecar_lock", side_effect=timeout),
            self.assertRaises(bg.BackgroundStoreError) as caught,
            bg.locked_jobs(writeback=False),
        ):
            self.fail("timed-out lock was accepted")
        self.assertEqual("bg_store_lock_timeout", caught.exception.reason_code)
        self.assertFalse(self.store.exists())

    def test_contended_lock_times_out_without_changing_existing_files(self) -> None:
        self.make_store()
        lock = self.store / "jobs.lock"
        lock.write_bytes(b"synthetic lock")
        lock.chmod(0o600)
        jobs = self.store / "jobs.json"
        before = (lock.read_bytes(), jobs.read_bytes())
        real_lock = sidecar.secure_sidecar_lock

        def short_lock(path, **kwargs):
            return real_lock(path, timeout_seconds=0.01, **kwargs)

        with (
            real_lock(lock, repair_existing=False, reject_parent_symlink=True),
            self.patched_store(),
            patch.object(sidecar, "secure_sidecar_lock", side_effect=short_lock),
            self.assertRaises(bg.BackgroundStoreError) as caught,
            bg.locked_jobs(writeback=False),
        ):
            self.fail("contended lock was accepted")
        self.assertEqual("bg_store_lock_timeout", caught.exception.reason_code)
        self.assertEqual(before, (lock.read_bytes(), jobs.read_bytes()))

    def test_new_lock_is_private_even_with_restrictive_umask(self) -> None:
        self.make_store()
        previous = os.umask(0o777)
        try:
            with self.patched_store(), bg.locked_jobs(writeback=False) as data:
                self.assertEqual([], data["jobs"])
        finally:
            os.umask(previous)
        self.assertEqual(0o600, stat.S_IMODE((self.store / "jobs.lock").stat().st_mode))

    def test_lock_swap_to_symlink_before_open_is_refused(self) -> None:
        self.make_store()
        lock = self.store / "jobs.lock"
        lock.write_bytes(b"synthetic lock")
        lock.chmod(0o600)
        victim = self.root / "external"
        victim.write_bytes(b"synthetic external data")
        victim.chmod(0o644)
        original_validate = sidecar._validate_target
        swapped = False

        def swap_before_open(metadata, *, require_private):
            nonlocal swapped
            if not swapped:
                swapped = True
                lock.rename(self.store / "owned-original-lock")
                lock.symlink_to(victim)
            return original_validate(metadata, require_private=require_private)

        with patch.object(sidecar, "_validate_target", side_effect=swap_before_open):
            self.assert_lock_refused()
        self.assertTrue(swapped)
        self.assertEqual(b"synthetic external data", victim.read_bytes())
        self.assertEqual(0o644, stat.S_IMODE(victim.stat().st_mode))

    def test_sidecar_no_repair_mode_preserves_nonprivate_existing_lock(self) -> None:
        lock = self.root / "existing.lock"
        lock.write_bytes(b"synthetic lock")
        lock.chmod(0o644)
        with (
            self.assertRaises(sidecar.SidecarSecurityError) as caught,
            sidecar.secure_sidecar_lock(lock, repair_existing=False),
        ):
            self.fail("nonprivate existing lock was accepted")
        self.assertEqual("session_sidecar_insecure_permissions", caught.exception.reason_code)
        self.assertEqual(b"synthetic lock", lock.read_bytes())
        self.assertEqual(0o644, stat.S_IMODE(lock.stat().st_mode))


if __name__ == "__main__":
    unittest.main()
