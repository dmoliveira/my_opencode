from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
session = importlib.import_module("session_command")


@unittest.skipUnless(os.name == "posix", "descriptor-bound backup requires POSIX")
class StaleRepairBackupSafetyTest(unittest.TestCase):
    def setUp(self) -> None:
        # Other suites reload the sidecar security module and its error types.
        # Refresh the consumer so failures use the current exception class.
        global session
        session = importlib.reload(importlib.import_module("session_command"))
        temporary = tempfile.TemporaryDirectory(prefix="stale-backup-safety-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.source = self.runtime / "synthetic.sqlite3"
        stale = int(time.time() * 1000) - 3_600_000
        with contextlib.closing(sqlite3.connect(self.source)) as connection:
            connection.executescript(
                "CREATE TABLE session (id TEXT PRIMARY KEY, parent_id TEXT, title TEXT NOT NULL, "
                "time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL);"
                "CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, "
                "time_created INTEGER NOT NULL, data TEXT NOT NULL);"
                "CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT NOT NULL, "
                "session_id TEXT NOT NULL, time_created INTEGER NOT NULL, data TEXT NOT NULL);"
            )
            connection.execute(
                "INSERT INTO session VALUES (?, ?, ?, ?, ?)",
                ("synthetic-session", None, "synthetic", stale, stale),
            )
            connection.execute(
                "INSERT INTO message VALUES (?, ?, ?, ?)",
                ("synthetic-message", "synthetic-session", stale, '{"role":"assistant","time":{}}'),
            )
            connection.commit()
        self.source.chmod(0o600)
        self.before = self.source.read_bytes()

    def collision_path(self, label: str = "collision") -> Path:
        return self.runtime / f"{self.source.name}.pre-repair-{label}.sqlite3"

    def test_private_backup_under_permissive_umask(self) -> None:
        program = (
            "import json, os, stat, sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "import session_command\n"
            "from pathlib import Path\n"
            "os.umask(0o022)\n"
            "path = session_command._backup_runtime_database(Path(sys.argv[2]))\n"
            "print(json.dumps({'path': str(path), 'mode': stat.S_IMODE(path.stat().st_mode)}))\n"
        )
        env = {
            "HOME": str(self.root),
            "PATH": "/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
            "OPENCODE_DB": str(self.source),
        }
        result = subprocess.run(
            [sys.executable, "-c", program, str(ROOT / "scripts"), str(self.source)],
            cwd=self.root,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["mode"], 0o600)
        backup = Path(payload["path"])
        with contextlib.closing(sqlite3.connect(backup)) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("SELECT id FROM session").fetchone()[0], "synthetic-session")
        self.assertEqual(self.before, self.source.read_bytes())

    def test_existing_destination_is_never_opened_or_removed(self) -> None:
        sentinel = self.collision_path()
        sentinel.write_bytes(b"synthetic pre-existing file")
        before = (sentinel.read_bytes(), sentinel.stat().st_ino, sentinel.stat().st_mtime_ns)
        real_connect = sqlite3.connect
        opened_existing = []

        def guarded_connect(path, *args, **kwargs):
            if str(path) == str(sentinel) or sentinel.name in str(path):
                opened_existing.append(True)
                raise AssertionError("existing destination was opened")
            return real_connect(path, *args, **kwargs)

        with (
            patch.object(session.uuid, "uuid4", return_value=SimpleNamespace(hex="collision")),
            patch.object(session.sqlite3, "connect", side_effect=guarded_connect),
            patch.object(Path, "unlink", side_effect=AssertionError("unexpected unlink")) as unlink,
            self.assertRaises(sqlite3.Error),
        ):
            session._backup_runtime_database(self.source)
        self.assertEqual(opened_existing, [])
        unlink.assert_not_called()
        self.assertEqual(before, (sentinel.read_bytes(), sentinel.stat().st_ino, sentinel.stat().st_mtime_ns))
        self.assertEqual(self.before, self.source.read_bytes())

    def test_missing_source_never_unlinks_a_colliding_destination(self) -> None:
        missing = self.runtime / "missing.sqlite3"
        sentinel = self.runtime / "missing.sqlite3.pre-repair-collision.sqlite3"
        sentinel.write_bytes(b"synthetic preserve")
        with (
            patch.object(session.uuid, "uuid4", return_value=SimpleNamespace(hex="collision")),
            patch.object(Path, "unlink", side_effect=AssertionError("unexpected unlink")) as unlink,
            self.assertRaises(sqlite3.Error),
        ):
            session._backup_runtime_database(missing)
        unlink.assert_not_called()
        self.assertEqual(sentinel.read_bytes(), b"synthetic preserve")
        self.assertEqual(self.before, self.source.read_bytes())

    def test_symlinked_destination_is_never_followed_or_removed(self) -> None:
        sentinel = self.runtime / "synthetic-sentinel"
        sentinel.write_bytes(b"preserve synthetic sentinel")
        link = self.collision_path("symlink")
        link.symlink_to(sentinel.name)
        with (
            patch.object(session.uuid, "uuid4", return_value=SimpleNamespace(hex="symlink")),
            patch.object(Path, "unlink", side_effect=AssertionError("unexpected unlink")) as unlink,
            self.assertRaises(sqlite3.Error),
        ):
            session._backup_runtime_database(self.source)
        unlink.assert_not_called()
        self.assertTrue(link.is_symlink())
        self.assertEqual(sentinel.read_bytes(), b"preserve synthetic sentinel")
        self.assertEqual(self.before, self.source.read_bytes())

    def test_hardlinked_destination_is_never_opened_or_removed(self) -> None:
        sentinel = self.runtime / "synthetic-sentinel"
        sentinel.write_bytes(b"preserve synthetic sentinel")
        link = self.collision_path("hardlink")
        os.link(sentinel, link)
        with (
            patch.object(session.uuid, "uuid4", return_value=SimpleNamespace(hex="hardlink")),
            patch.object(Path, "unlink", side_effect=AssertionError("unexpected unlink")) as unlink,
            self.assertRaises(sqlite3.Error),
        ):
            session._backup_runtime_database(self.source)
        unlink.assert_not_called()
        self.assertEqual(sentinel.read_bytes(), b"preserve synthetic sentinel")
        self.assertEqual(link.read_bytes(), b"preserve synthetic sentinel")
        self.assertEqual(self.before, self.source.read_bytes())

    def test_failed_destination_is_retained_private_and_reported(self) -> None:
        partial = self.collision_path("partial")
        source = MagicMock()
        with (
            patch.object(session.uuid, "uuid4", return_value=SimpleNamespace(hex="partial")),
            patch.object(session, "_connect_runtime_database_readonly", return_value=source),
            patch.object(session.sqlite3, "connect", side_effect=sqlite3.OperationalError("synthetic open failure")),
            patch.object(Path, "unlink", side_effect=AssertionError("unexpected unlink")) as unlink,
            self.assertRaises(sqlite3.Error) as caught,
        ):
            session._backup_runtime_database(self.source)
        unlink.assert_not_called()
        self.assertTrue(partial.is_file())
        self.assertEqual(stat.S_IMODE(partial.stat().st_mode), 0o600)
        self.assertIn("unverified", str(caught.exception).lower())
        self.assertIn(str(partial), str(caught.exception))
        source.close.assert_called_once_with()
        self.assertEqual(self.before, self.source.read_bytes())

    def test_sync_failure_preserves_unverified_private_artifact(self) -> None:
        partial = self.collision_path("sync")
        with (
            patch.object(session.uuid, "uuid4", return_value=SimpleNamespace(hex="sync")),
            patch.object(session.os, "fsync", side_effect=OSError("synthetic sync failure")),
            patch.object(Path, "unlink", side_effect=AssertionError("unexpected unlink")) as unlink,
            self.assertRaises(sqlite3.Error) as caught,
        ):
            session._backup_runtime_database(self.source)
        unlink.assert_not_called()
        self.assertTrue(partial.is_file())
        self.assertEqual(stat.S_IMODE(partial.stat().st_mode), 0o600)
        self.assertIn("unverified", str(caught.exception).lower())
        self.assertEqual(self.before, self.source.read_bytes())

    def test_integrity_failure_never_reports_a_valid_backup(self) -> None:
        partial = self.collision_path("integrity")
        real_connect = sqlite3.connect
        verifier = MagicMock()
        verifier.execute.return_value.fetchall.return_value = [("synthetic corruption",)]

        def fail_verification(path, *args, **kwargs):
            if str(path).endswith("?mode=ro&immutable=1"):
                return verifier
            return real_connect(path, *args, **kwargs)

        with (
            patch.object(session.uuid, "uuid4", return_value=SimpleNamespace(hex="integrity")),
            patch.object(session.sqlite3, "connect", side_effect=fail_verification),
            patch.object(Path, "unlink", side_effect=AssertionError("unexpected unlink")) as unlink,
            self.assertRaises(sqlite3.Error) as caught,
        ):
            session._backup_runtime_database(self.source)
        unlink.assert_not_called()
        verifier.close.assert_called_once_with()
        self.assertIn("consistency check", str(caught.exception))
        self.assertTrue(partial.is_file())
        self.assertEqual(stat.S_IMODE(partial.stat().st_mode), 0o600)
        self.assertEqual(self.before, self.source.read_bytes())

    def test_bounded_backup_and_check_failures_never_reach_writer(self) -> None:
        for helper, phase in (
            ("_run_online_backup", "backup"),
            ("_validate_snapshot_database", "integrity_check"),
        ):
            with self.subTest(phase=phase):
                partial = self.collision_path(phase)
                error = session.RuntimeSnapshotError(
                    "synthetic_timeout", f"synthetic {phase} timeout", phase=phase
                )
                with (
                    patch.object(session.uuid, "uuid4", return_value=SimpleNamespace(hex=phase)),
                    patch.object(session, helper, side_effect=error),
                    patch.object(
                        session,
                        "_connect_runtime_database_writable",
                        side_effect=AssertionError("unverified backup reached writer"),
                    ) as writer,
                    patch.object(Path, "unlink", side_effect=AssertionError("unexpected unlink")) as unlink,
                ):
                    result = session._repair_runtime_stuck_sessions(
                        self.source, 300, apply_changes=True, include_generic=True,
                        scope_session_id="synthetic-session",
                    )
                writer.assert_not_called()
                unlink.assert_not_called()
                self.assertEqual(result["repaired_count"], 0)
                self.assertIsNone(result["backup_path"])
                self.assertTrue(any("unverified" in problem for problem in result["problems"]))
                self.assertTrue(any(str(partial) in problem for problem in result["problems"]))
                self.assertTrue(partial.is_file())
                self.assertEqual(stat.S_IMODE(partial.stat().st_mode), 0o600)
                self.assertEqual(self.before, self.source.read_bytes())

    def test_replaced_backup_entry_is_not_deleted_or_reported_as_valid(self) -> None:
        expected = self.collision_path("swap")
        moved = self.runtime / "synthetic-moved-partial.sqlite3"
        real_connect = sqlite3.connect

        def swap_on_destination_open(path, *args, **kwargs):
            if str(path).startswith("file:///dev/fd/") and str(path).endswith("?mode=rw"):
                expected.rename(moved)
                expected.write_bytes(b"synthetic replacement")
            return real_connect(path, *args, **kwargs)

        with (
            patch.object(session.uuid, "uuid4", return_value=SimpleNamespace(hex="swap")),
            patch.object(session.sqlite3, "connect", side_effect=swap_on_destination_open),
            patch.object(Path, "unlink", side_effect=AssertionError("unexpected unlink")) as unlink,
            self.assertRaises(sqlite3.Error),
        ):
            session._backup_runtime_database(self.source)
        unlink.assert_not_called()
        self.assertEqual(expected.read_bytes(), b"synthetic replacement")
        self.assertTrue(moved.exists())
        self.assertEqual(stat.S_IMODE(moved.stat().st_mode), 0o600)
        self.assertEqual(self.before, self.source.read_bytes())

    def test_blocked_linked_database_never_reaches_backup(self) -> None:
        for kind in ("symlink", "hardlink"):
            with self.subTest(kind=kind):
                target = self.runtime / f"{kind}.sqlite3"
                if kind == "symlink":
                    target.symlink_to(self.source.name)
                else:
                    os.link(self.source, target)
                scan = session._scan_runtime_stuck_sessions(target, 300)
                self.assertEqual(scan["runtime_permission_status"], "blocked")
                with patch.object(
                    session,
                    "_backup_runtime_database",
                    side_effect=AssertionError("unsafe backup attempted"),
                ) as backup:
                    result = session._repair_runtime_stuck_sessions(
                        target, 300, apply_changes=True, include_generic=True,
                        scope_session_id="synthetic-session",
                    )
                backup.assert_not_called()
                self.assertEqual(result["repaired_count"], 0)
                self.assertTrue(result["problems"])
                self.assertEqual(self.before, self.source.read_bytes())

    def test_direct_backup_rejects_symlinked_source(self) -> None:
        linked = self.runtime / "source-link.sqlite3"
        linked.symlink_to(self.source.name)
        with self.assertRaises(sqlite3.Error):
            session._backup_runtime_database(linked)
        self.assertTrue(linked.is_symlink())
        self.assertEqual(self.before, self.source.read_bytes())
        self.assertEqual([], list(self.runtime.glob("*.pre-repair-*.sqlite3")))

    def test_direct_backup_rejects_hardlinked_source(self) -> None:
        linked = self.runtime / "source-hardlink.sqlite3"
        os.link(self.source, linked)
        with self.assertRaises(sqlite3.Error):
            session._backup_runtime_database(self.source)
        self.assertEqual(self.before, self.source.read_bytes())
        self.assertEqual(self.before, linked.read_bytes())
        self.assertEqual([], list(self.runtime.glob("*.pre-repair-*.sqlite3")))

    def test_writable_parent_refuses_backup_without_creating_artifact(self) -> None:
        self.runtime.chmod(0o777)
        try:
            with self.assertRaises(sqlite3.Error):
                session._backup_runtime_database(self.source)
            self.assertEqual([], list(self.runtime.glob("*.pre-repair-*.sqlite3")))
            self.assertEqual(self.before, self.source.read_bytes())
        finally:
            self.runtime.chmod(0o700)

    def test_source_replacement_after_backup_never_reaches_writer(self) -> None:
        replacement = self.runtime / "synthetic-replacement.sqlite3"
        replacement.write_bytes(self.before)
        replacement.chmod(0o600)
        preserved = self.runtime / "synthetic-original.sqlite3"
        real_backup = session._backup_runtime_database

        def backup_then_replace(path: Path) -> Path:
            result = real_backup(path)
            path.rename(preserved)
            replacement.rename(path)
            return result

        with (
            patch.object(session, "_backup_runtime_database", side_effect=backup_then_replace),
            patch.object(
                session,
                "_connect_runtime_database_writable",
                side_effect=AssertionError("replaced source opened for writing"),
            ) as writer,
        ):
            result = session._repair_runtime_stuck_sessions(
                self.source, 300, apply_changes=True, include_generic=True,
                scope_session_id="synthetic-session",
            )
        writer.assert_not_called()
        self.assertEqual(result["repaired_count"], 0)
        self.assertTrue(any("identity changed" in item for item in result["problems"]))
        self.assertIsNotNone(result["backup_path"])
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertEqual(preserved.read_bytes(), self.before)
        self.assertNotEqual(self.source.stat().st_ino, preserved.stat().st_ino)

    def test_source_replacement_after_scan_never_reaches_backup(self) -> None:
        replacement = self.runtime / "synthetic-replacement.sqlite3"
        replacement.write_bytes(self.before)
        replacement.chmod(0o600)
        preserved = self.runtime / "synthetic-original.sqlite3"
        real_scan = session._scan_runtime_stuck_sessions

        def scan_then_replace(path: Path, stale_seconds: int) -> dict:
            result = real_scan(path, stale_seconds)
            path.rename(preserved)
            replacement.rename(path)
            return result

        with (
            patch.object(session, "_scan_runtime_stuck_sessions", side_effect=scan_then_replace),
            patch.object(
                session,
                "_backup_runtime_database",
                side_effect=AssertionError("replaced source reached backup"),
            ) as backup,
        ):
            result = session._repair_runtime_stuck_sessions(
                self.source, 300, apply_changes=True, include_generic=True,
                scope_session_id="synthetic-session",
            )
        backup.assert_not_called()
        self.assertEqual(result["repaired_count"], 0)
        self.assertTrue(any("identity is unverified" in item for item in result["problems"]))
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertEqual(preserved.read_bytes(), self.before)
        self.assertNotEqual(self.source.stat().st_ino, preserved.stat().st_ino)

    def test_source_replacement_while_writer_opens_never_reaches_repair(self) -> None:
        replacement = self.runtime / "synthetic-replacement.sqlite3"
        replacement.write_bytes(self.before)
        replacement.chmod(0o600)
        preserved = self.runtime / "synthetic-original.sqlite3"
        real_connect = session._connect_runtime_database_writable

        def replace_then_open(path: Path) -> sqlite3.Connection:
            path.rename(preserved)
            replacement.rename(path)
            return real_connect(path)

        with patch.object(
            session, "_connect_runtime_database_writable", side_effect=replace_then_open
        ) as writer:
            result = session._repair_runtime_stuck_sessions(
                self.source, 300, apply_changes=True, include_generic=True,
                scope_session_id="synthetic-session",
            )
        writer.assert_called_once_with(self.source)
        self.assertEqual(result["repaired_count"], 0)
        self.assertTrue(any("identity changed while opening writer" in item for item in result["problems"]))
        self.assertIsNotNone(result["backup_path"])
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertEqual(preserved.read_bytes(), self.before)
        self.assertNotEqual(self.source.stat().st_ino, preserved.stat().st_ino)

    def test_permissions_changed_after_backup_never_reach_writer(self) -> None:
        real_backup = session._backup_runtime_database

        def backup_then_change_parent(path: Path) -> Path:
            result = real_backup(path)
            self.runtime.chmod(0o777)
            return result

        try:
            with (
                patch.object(session, "_backup_runtime_database", side_effect=backup_then_change_parent),
                patch.object(
                    session,
                    "_connect_runtime_database_writable",
                    side_effect=AssertionError("unsafe source opened for writing"),
                ) as writer,
            ):
                result = session._repair_runtime_stuck_sessions(
                    self.source, 300, apply_changes=True, include_generic=True,
                    scope_session_id="synthetic-session",
                )
            writer.assert_not_called()
            self.assertEqual(result["repaired_count"], 0)
            self.assertTrue(any("identity changed" in item for item in result["problems"]))
            self.assertIsNotNone(result["backup_path"])
            self.assertEqual(self.before, self.source.read_bytes())
        finally:
            self.runtime.chmod(0o700)

    def test_blocked_preview_does_not_suggest_apply(self) -> None:
        linked = self.runtime / "source-link.sqlite3"
        linked.symlink_to(self.source.name)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = session._command_repair_stale(
                ["--db-path", str(linked), "--include-generic", "--json"],
                self.root / "unused-index.json",
            )
        report = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertGreater(report["candidate_count"], 0)
        self.assertEqual(report["quick_fixes"], [])
        self.assertEqual(self.before, self.source.read_bytes())

    def test_unknown_permission_state_never_reaches_backup(self) -> None:
        scan = {
            "warnings": [], "problems": [], "runtime_db_scan_complete": True,
            "stuck_findings": [{"issue_type": "stale_running_tool", "session_id": "synthetic-session"}],
            "generic_stale_findings": [],
        }
        with (
            patch.object(session, "_scan_runtime_stuck_sessions", return_value=scan),
            patch.object(session, "_backup_runtime_database", side_effect=AssertionError("unverified backup")) as backup,
        ):
            result = session._repair_runtime_stuck_sessions(
                self.source, 300, apply_changes=True, include_generic=False
            )
        backup.assert_not_called()
        self.assertEqual(result["repaired_count"], 0)
        self.assertTrue(result["problems"])
        self.assertEqual(self.before, self.source.read_bytes())

    def test_unsafe_wal_or_shm_never_reaches_backup(self) -> None:
        scan = {
            "warnings": [], "problems": [], "runtime_db_scan_complete": True,
            "runtime_permission_status": "private",
            "stuck_findings": [{"issue_type": "stale_running_tool", "session_id": "synthetic-session"}],
            "generic_stale_findings": [],
        }
        for suffix in ("-wal", "-shm"):
            with self.subTest(sidecar=suffix):
                sidecar = Path(f"{self.source}{suffix}")
                sidecar.symlink_to(self.source.name)
                with (
                    patch.object(session, "_scan_runtime_stuck_sessions", return_value=scan),
                    patch.object(session, "_backup_runtime_database") as backup,
                ):
                    result = session._repair_runtime_stuck_sessions(
                        self.source, 300, apply_changes=True, include_generic=False
                    )
                backup.assert_not_called()
                self.assertEqual(result["repaired_count"], 0)
                self.assertTrue(result["problems"])
                self.assertEqual(self.before, self.source.read_bytes())
                # Remove only this synthetic link so each sidecar is tested independently.
                sidecar.unlink()


if __name__ == "__main__":
    unittest.main()
