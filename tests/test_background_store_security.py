from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import background_task_manager as bg
import session_sidecar_security as sidecar


class BackgroundStoreSecurityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bg-store-security-")
        self.root = Path(self.temporary.name)
        self.store = self.root / "bg"
        self.store.mkdir(mode=0o700)
        (self.store / "runs").mkdir(mode=0o700)
        lock = self.store / "jobs.lock"
        lock.write_bytes(b"synthetic lock")
        lock.chmod(0o600)

    def tearDown(self) -> None:
        self.temporary.cleanup()

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

    def write_index(self, data: bytes = b'{"version": 1, "jobs": []}') -> Path:
        path = self.store / "jobs.json"
        path.write_bytes(data)
        path.chmod(0o600)
        return path

    def assert_index_refused(self, reason: str) -> None:
        with (
            self.patched_store(),
            self.assertRaises(bg.BackgroundStoreError) as caught,
            bg.locked_jobs(writeback=False),
        ):
            self.fail("unsafe index was accepted")
        self.assertEqual(reason, caught.exception.reason_code)
        self.assertNotIn("synthetic-private-canary", str(caught.exception))

    def test_parent_swap_cannot_redirect_initialization_or_read(self) -> None:
        victim = self.root / "victim"
        victim.mkdir(mode=0o700)
        victim_index = victim / "jobs.json"
        victim_index.symlink_to(victim / "synthetic-absent")
        original_store = self.root / "owned-original-store"
        real_ensure = bg.ensure_store

        def swap_before_initialization(*args, **kwargs):
            self.store.rename(original_store)
            self.store.symlink_to(victim, target_is_directory=True)
            return real_ensure(*args, **kwargs)

        with (
            self.patched_store(),
            patch.object(bg, "ensure_store", side_effect=swap_before_initialization),
            bg.locked_jobs(writeback=False) as data,
        ):
            self.assertEqual([], data["jobs"])
        self.assertTrue(victim_index.is_symlink())
        self.assertFalse((victim / "runs").exists())
        self.assertEqual([], json.loads((original_store / "jobs.json").read_bytes())["jobs"])

    def test_symlinked_index_is_not_followed_or_replaced(self) -> None:
        victim = self.root / "external"
        victim.write_bytes(b'{"version": 1, "jobs": [], "secret": "synthetic-private-canary"}')
        victim.chmod(0o600)
        index = self.store / "jobs.json"
        index.symlink_to(victim)
        before = (victim.read_bytes(), victim.stat().st_ino, stat.S_IMODE(victim.stat().st_mode))
        self.assert_index_refused("bg_store_index_unsafe")
        self.assertTrue(index.is_symlink())
        self.assertEqual(before, (victim.read_bytes(), victim.stat().st_ino, stat.S_IMODE(victim.stat().st_mode)))

    def test_dangling_index_symlink_is_not_replaced(self) -> None:
        index = self.store / "jobs.json"
        index.symlink_to(self.root / "synthetic-absent")
        self.assert_index_refused("bg_store_index_unsafe")
        self.assertTrue(index.is_symlink())
        self.assertFalse((self.root / "synthetic-absent").exists())

    def test_hardlinked_index_is_refused_without_changes(self) -> None:
        victim = self.root / "external"
        victim.write_bytes(b'{"version": 1, "jobs": []}')
        victim.chmod(0o600)
        os.link(victim, self.store / "jobs.json")
        before = (victim.read_bytes(), victim.stat().st_ino, stat.S_IMODE(victim.stat().st_mode))
        self.assert_index_refused("bg_store_index_unsafe")
        self.assertEqual(before, (victim.read_bytes(), victim.stat().st_ino, stat.S_IMODE(victim.stat().st_mode)))

    def test_fifo_index_is_refused_without_blocking(self) -> None:
        index = self.store / "jobs.json"
        os.mkfifo(index, 0o600)
        with patch.object(Path, "read_text", return_value='{"version": 1, "jobs": []}'):
            self.assert_index_refused("bg_store_index_unsafe")
        self.assertTrue(stat.S_ISFIFO(index.stat().st_mode))

    def test_nonprivate_index_is_not_repaired_or_replaced(self) -> None:
        index = self.write_index()
        index.chmod(0o644)
        before = (index.read_bytes(), index.stat().st_ino, stat.S_IMODE(index.stat().st_mode))
        self.assert_index_refused("bg_store_index_unsafe")
        self.assertEqual(before, (index.read_bytes(), index.stat().st_ino, stat.S_IMODE(index.stat().st_mode)))

    def test_oversized_index_is_refused_without_read_or_replacement(self) -> None:
        index = self.write_index(b'{"version":1,"jobs":[],"padding":"' + b"x" * (16 * 1024 * 1024) + b'"}')
        before = (index.stat().st_ino, index.stat().st_size, index.stat().st_mtime_ns)
        with patch.object(bg.os, "read", side_effect=AssertionError("oversized index must not be read")):
            self.assert_index_refused("bg_store_index_too_large")
        self.assertEqual(before, (index.stat().st_ino, index.stat().st_size, index.stat().st_mtime_ns))

    def test_index_swap_during_read_is_observed_without_following_replacement(self) -> None:
        index = self.write_index()
        victim = self.root / "external"
        victim.write_bytes(b"synthetic-private-canary")
        victim.chmod(0o600)
        original = self.root / "owned-original-index"
        real_read = os.read
        swapped = False

        def swap_during_read(descriptor, size):
            nonlocal swapped
            if not swapped:
                swapped = True
                index.rename(original)
                index.symlink_to(victim)
            return real_read(descriptor, size)

        with patch.object(bg.os, "read", side_effect=swap_during_read):
            self.assert_index_refused("bg_store_index_changed")
        self.assertTrue(swapped)
        self.assertTrue(index.is_symlink())
        self.assertEqual(b"synthetic-private-canary", victim.read_bytes())
        self.assertEqual(b'{"version": 1, "jobs": []}', original.read_bytes())

    def test_malformed_index_is_preserved_without_disclosure(self) -> None:
        index = self.write_index(b"{synthetic-private-canary")
        before = (index.read_bytes(), index.stat().st_ino)
        self.assert_index_refused("bg_store_index_invalid")
        self.assertEqual(before, (index.read_bytes(), index.stat().st_ino))

    def test_index_with_excessive_integer_is_refused_and_preserved(self) -> None:
        index = self.write_index(b'{"jobs": [], "large": ' + b"9" * 5000 + b"}")
        before = (index.read_bytes(), index.stat().st_ino)
        self.assert_index_refused("bg_store_index_invalid")
        self.assertEqual(before, (index.read_bytes(), index.stat().st_ino))

    def test_index_at_size_limit_is_readable(self) -> None:
        raw = b'{"version": 1, "jobs": []}'
        self.write_index(raw)
        with (
            self.patched_store(),
            patch.object(bg, "MAX_JOB_STORE_BYTES", len(raw)),
            bg.locked_jobs(writeback=False) as data,
        ):
            self.assertEqual([], data["jobs"])

    def test_oversized_writeback_is_refused_without_publishing(self) -> None:
        index = self.write_index()
        before = (index.read_bytes(), index.stat().st_ino, stat.S_IMODE(index.stat().st_mode))
        with (
            self.patched_store(),
            patch.object(bg, "MAX_JOB_STORE_BYTES", 128),
            patch.object(bg, "_atomic_write_json", side_effect=AssertionError("must not publish")) as publish,
            self.assertRaises(bg.BackgroundStoreError) as caught,
            bg.locked_jobs(writeback=True) as data,
        ):
            data["jobs"].append({"synthetic": "x" * 256})
        self.assertEqual("bg_store_index_too_large", caught.exception.reason_code)
        publish.assert_not_called()
        self.assertEqual(before, (index.read_bytes(), index.stat().st_ino, stat.S_IMODE(index.stat().st_mode)))

    def test_symlinked_runs_directory_is_refused_before_index_creation(self) -> None:
        runs = self.store / "runs"
        runs.rmdir()
        victim = self.root / "external-runs"
        victim.mkdir(mode=0o700)
        (victim / "marker").write_bytes(b"synthetic external data")
        runs.symlink_to(victim, target_is_directory=True)
        with (
            self.patched_store(),
            self.assertRaises(bg.BackgroundStoreError) as caught,
            bg.locked_jobs(writeback=False),
        ):
            self.fail("symlinked runs directory was accepted")
        self.assertEqual("bg_store_unsafe", caught.exception.reason_code)
        self.assertTrue(runs.is_symlink())
        self.assertFalse((self.store / "jobs.json").exists())
        self.assertEqual(b"synthetic external data", (victim / "marker").read_bytes())

    def test_index_read_error_is_sanitized_and_preserved(self) -> None:
        index = self.write_index()
        before = index.read_bytes()
        with patch.object(bg.os, "read", side_effect=OSError("synthetic-private-canary")):
            self.assert_index_refused("bg_store_read_error")
        self.assertEqual(before, index.read_bytes())

    def test_failed_initial_write_preserves_partial_new_index(self) -> None:
        with (
            self.patched_store(),
            patch.object(bg.os, "write", side_effect=OSError("synthetic-private-canary")),
            self.assertRaises(bg.BackgroundStoreError) as caught,
            bg.locked_jobs(writeback=False),
        ):
            self.fail("failed initialization was accepted")
        self.assertEqual("bg_store_init_indeterminate", caught.exception.reason_code)
        self.assertNotIn("synthetic-private-canary", str(caught.exception))
        self.assertTrue((self.store / "jobs.json").is_file())
        self.assertEqual(b"", (self.store / "jobs.json").read_bytes())

    def test_initial_directory_sync_failure_preserves_new_index(self) -> None:
        with (
            self.patched_store(),
            patch.object(bg.os, "fsync", side_effect=[None, OSError("synthetic-private-canary")]),
            self.assertRaises(bg.BackgroundStoreError) as caught,
            bg.locked_jobs(writeback=False),
        ):
            self.fail("indeterminate initialization was accepted")
        self.assertEqual("bg_store_init_indeterminate", caught.exception.reason_code)
        self.assertNotIn("synthetic-private-canary", str(caught.exception))
        self.assertEqual([], json.loads((self.store / "jobs.json").read_bytes())["jobs"])

    def test_initial_close_failure_reports_indeterminate_and_preserves_index(self) -> None:
        index = self.store / "jobs.json"
        real_close = os.close

        def close_then_fail(descriptor):
            opened = os.fstat(descriptor)
            is_index = index.exists() and (opened.st_dev, opened.st_ino) == (
                index.stat().st_dev,
                index.stat().st_ino,
            )
            real_close(descriptor)
            if is_index:
                raise OSError("synthetic-private-canary")

        with (
            self.patched_store(),
            patch.object(bg.os, "close", side_effect=close_then_fail),
            self.assertRaises(bg.BackgroundStoreError) as caught,
            bg.locked_jobs(writeback=False),
        ):
            self.fail("indeterminate initialization was accepted")
        self.assertEqual("bg_store_init_indeterminate", caught.exception.reason_code)
        self.assertNotIn("synthetic-private-canary", str(caught.exception))
        self.assertEqual([], json.loads(index.read_bytes())["jobs"])

    def test_borrowed_parent_descriptor_is_scoped_to_lock_context(self) -> None:
        lock = self.store / "jobs.lock"
        with sidecar.secure_sidecar_lock(lock) as default_value:
            self.assertIsNone(default_value)
        with sidecar.secure_sidecar_lock(lock, borrow_parent_fd=True) as parent_fd:
            self.assertIsInstance(parent_fd, int)
            opened = os.fstat(parent_fd)
            expected = self.store.stat()
            self.assertEqual((expected.st_dev, expected.st_ino), (opened.st_dev, opened.st_ino))
        with self.assertRaises(OSError):
            os.fstat(parent_fd)


if __name__ == "__main__":
    unittest.main()
