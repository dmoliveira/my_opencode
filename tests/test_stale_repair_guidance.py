from __future__ import annotations

import contextlib
import importlib
import io
import json
import shlex
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
session = importlib.import_module("session_command")
gateway = importlib.import_module("gateway_command")


class StaleRepairGuidanceTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="stale-guidance-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db_path = self.root / "runtime # 'synthetic' data.sqlite3"
        self.db_path.write_bytes(b"synthetic database sentinel\n")
        self.index_path = self.root / "unused-index.json"
        self.before = self.sentinel_state()

    def sentinel_state(self) -> tuple[bytes, int, int, int]:
        metadata = self.db_path.stat()
        return (
            self.db_path.read_bytes(),
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_mtime_ns,
        )

    @staticmethod
    def scan(*, complete: bool | None) -> dict:
        return {
            "warnings": [],
            "problems": ["synthetic diagnostic finding"],
            "stuck_findings": [{"issue_type": "stale_running_tool"}],
            "generic_stale_findings": [
                {"session_id": "synthetic-session", "stale_seconds": 1000}
            ],
            "generic_stale_count": 1,
            "runtime_db_scan_complete": complete,
            "runtime_permission_quick_fixes": [
                "/session repair-runtime-permissions --json"
            ],
        }

    def session_doctor(self, scan: dict) -> dict:
        output = io.StringIO()
        with (
            patch.object(
                session,
                "_inspect_active_sidecars",
                return_value=([{"target": "index", "state": "safe"}], None),
            ),
            patch.object(session, "_load_index", return_value={}),
            patch.object(session, "_session_rows", return_value=[{}]),
            patch.object(session, "_scan_runtime_stuck_sessions", return_value=scan),
            patch.object(
                session,
                "_connect_runtime_database_readonly",
                side_effect=AssertionError("unexpected database access"),
            ),
            contextlib.redirect_stdout(output),
        ):
            code = session._command_doctor(
                ["--db-path", str(self.db_path), "--stale-seconds", "900", "--json"],
                self.index_path,
            )
        self.assertEqual(code, 1)
        return json.loads(output.getvalue())

    def gateway_doctor(self, scan: dict) -> dict:
        with patch.object(gateway, "_scan_runtime_stuck_sessions", return_value=scan):
            return gateway.runtime_session_health_summary(
                db_path=self.db_path, stale_seconds=900
            )

    def assert_preview_invocation(self, command: str, *, generic: bool) -> None:
        args = shlex.split(command)
        self.assertEqual(args[:2], ["/session", "repair-stale"])
        self.assertEqual(args[args.index("--db-path") + 1], str(self.db_path))
        self.assertNotIn("--apply", args)
        self.assertNotIn("--confirm-generic", args)
        self.assertEqual("--include-generic" in args, generic)
        fake_repair = {
            "problems": [],
            "warnings": [],
            "candidate_count": 1,
            "repaired_count": 0,
            "repairs": [],
            "preview": [{"session_id": "synthetic-session"}],
            "backup_path": None,
        }
        output = io.StringIO()
        with (
            patch.object(
                session, "_repair_runtime_stuck_sessions", return_value=fake_repair
            ) as repair,
            contextlib.redirect_stdout(output),
        ):
            code = session._command_repair_stale(args[2:], self.index_path)
        self.assertEqual(code, 1)  # A preview with candidates reports attention needed.
        repair.assert_called_once_with(self.db_path, 900, False, generic, None)
        report = json.loads(output.getvalue())
        self.assertFalse(report["apply"])
        self.assertEqual(report["repaired_count"], 0)
        follow_up = shlex.split(report["quick_fixes"][0])
        self.assertIn("--apply", follow_up)
        self.assertEqual("--confirm-generic" in follow_up, generic)

    def test_completed_scans_offer_only_parseable_previews(self) -> None:
        reports = (
            self.session_doctor(self.scan(complete=True))["quick_fixes"],
            self.gateway_doctor(self.scan(complete=True))["repair_commands"],
        )
        for commands in reports:
            previews = [item for item in commands if "repair-stale" in item]
            self.assertEqual(len(previews), 2)
            self.assertEqual(
                sum("--include-generic" in shlex.split(command) for command in previews),
                1,
            )
            for command in previews:
                with self.subTest(command=command):
                    self.assert_preview_invocation(
                        command, generic="--include-generic" in shlex.split(command)
                    )
            self.assertIn("/session repair-runtime-permissions --json", commands)
        self.assertEqual(self.before, self.sentinel_state())

    def test_incomplete_scans_offer_no_stale_repair_commands(self) -> None:
        for complete in (False, None):
            with self.subTest(complete=complete):
                reports = (
                    self.session_doctor(self.scan(complete=complete))["quick_fixes"],
                    self.gateway_doctor(self.scan(complete=complete))["repair_commands"],
                )
                for commands in reports:
                    self.assertFalse(any("repair-stale" in item for item in commands))
                    self.assertIn("/session repair-runtime-permissions --json", commands)
        self.assertEqual(self.before, self.sentinel_state())

    def test_generic_apply_still_requires_explicit_confirmation(self) -> None:
        output = io.StringIO()
        with (
            patch.object(
                session,
                "_repair_runtime_stuck_sessions",
                side_effect=AssertionError("unexpected repair call"),
            ) as repair,
            contextlib.redirect_stdout(output),
        ):
            code = session._command_repair_stale(
                ["--db-path", str(self.db_path), "--include-generic", "--apply", "--json"],
                self.index_path,
            )
        self.assertEqual(code, 1)
        self.assertIn("requires --confirm-generic", json.loads(output.getvalue())["problems"][0])
        repair.assert_not_called()
        self.assertEqual(self.before, self.sentinel_state())

    def test_synthetic_database_preview_does_not_apply_or_create_backup(self) -> None:
        db_path = self.root / "real synthetic runtime.sqlite3"
        index_path = self.root / "index.json"
        index_path.write_text('{"version": 1, "sessions": []}\n', encoding="utf-8")
        index_path.chmod(0o600)
        stale = int(time.time() * 1000) - 3_600_000
        with contextlib.closing(sqlite3.connect(db_path)) as connection:
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
        db_path.chmod(0o600)
        before_db = (db_path.read_bytes(), db_path.stat().st_ino, db_path.stat().st_mtime_ns)
        before_index = index_path.read_bytes()
        before_files = {path.name for path in self.root.iterdir()}
        output = io.StringIO()
        with (
            patch.object(session, "DEFAULT_DIGEST_PATH", self.root / "digest.json"),
            patch.object(
                session, "_backup_runtime_database", side_effect=AssertionError("unexpected backup")
            ),
            patch.object(
                session,
                "_connect_runtime_database_writable",
                side_effect=AssertionError("unexpected writable database"),
            ),
            contextlib.redirect_stdout(output),
        ):
            doctor_code = session._command_doctor(
                ["--db-path", str(db_path), "--generic-stale-problem-threshold", "1", "--json"],
                index_path,
            )
            doctor = json.loads(output.getvalue())
            summary = gateway.runtime_session_health_summary(
                db_path=db_path, generic_stale_problem_threshold=1
            )
            commands = (
                next(item for item in doctor["quick_fixes"] if "--include-generic" in item),
                next(item for item in summary["repair_commands"] if "--include-generic" in item),
            )
            previews = []
            for command in commands:
                output.seek(0)
                output.truncate()
                code = session._command_repair_stale(shlex.split(command)[2:], index_path)
                previews.append((code, json.loads(output.getvalue())))
        self.assertEqual(doctor_code, 1)
        self.assertTrue(doctor["runtime_db_scan_complete"])
        self.assertTrue(summary["runtime_db_scan_complete"])
        for code, preview in previews:
            self.assertEqual(code, 1)
            self.assertFalse(preview["apply"])
            self.assertEqual(preview["candidate_count"], 1)
            self.assertEqual(preview["repaired_count"], 0)
            self.assertIsNone(preview["backup_path"])
        self.assertEqual(before_db, (db_path.read_bytes(), db_path.stat().st_ino, db_path.stat().st_mtime_ns))
        self.assertEqual(before_index, index_path.read_bytes())
        self.assertEqual(before_files, {path.name for path in self.root.iterdir()})
        self.assertEqual(self.before, self.sentinel_state())


if __name__ == "__main__":
    unittest.main()
