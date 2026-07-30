from __future__ import annotations

import hashlib
import importlib
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


class _CommitFaultConnection:
    def __init__(self, connection: sqlite3.Connection, *, fail_on_commit: int) -> None:
        self.connection = connection
        self.fail_on_commit = fail_on_commit
        self.commit_count = 0

    @property
    def row_factory(self):
        return self.connection.row_factory

    @row_factory.setter
    def row_factory(self, value) -> None:
        self.connection.row_factory = value

    @property
    def in_transaction(self) -> bool:
        return self.connection.in_transaction

    def execute(self, *args, **kwargs):
        return self.connection.execute(*args, **kwargs)

    def commit(self) -> None:
        self.commit_count += 1
        if self.commit_count == self.fail_on_commit:
            raise sqlite3.OperationalError("injected commit failure")
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()

    def close(self) -> None:
        self.connection.close()


class RuntimeDatabaseConnectionTest(unittest.TestCase):
    def _module(self):
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        return importlib.reload(importlib.import_module("session_command"))

    def _canonical_rows(self, db_path: Path) -> dict[str, list[tuple]]:
        connection = sqlite3.connect(db_path)
        try:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            return {
                table: connection.execute(
                    f'SELECT * FROM "{table}" ORDER BY 1'
                ).fetchall()
                for table in ("session", "message", "part")
                if table in tables
            }
        finally:
            connection.close()

    def _schema_rows(self, db_path: Path) -> list[tuple]:
        connection = sqlite3.connect(db_path)
        try:
            return connection.execute(
                "SELECT type, name, tbl_name, sql "
                "FROM sqlite_master ORDER BY type, name"
            ).fetchall()
        finally:
            connection.close()

    def _quiescent_snapshot(
        self, db_path: Path
    ) -> tuple[str, list[tuple], dict[str, list[tuple]]]:
        return (
            hashlib.sha256(db_path.read_bytes()).hexdigest(),
            self._schema_rows(db_path),
            self._canonical_rows(db_path),
        )

    def _canonical_findings(self, items: list[dict]) -> list[dict]:
        return sorted(
            items,
            key=lambda item: (
                str(item.get("issue_type")),
                str(item.get("session_id")),
                str(item.get("parent_session_id")),
                str(item.get("child_session_id")),
            ),
        )

    def _scan_with_findings(self, scan: dict, findings: list[dict]) -> dict:
        return {
            **scan,
            "stuck_findings": findings,
            "generic_stale_findings": [],
            "generic_stale_count": 0,
        }

    def test_runtime_diagnostic_connection_uses_readonly_uri(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "opencode #?.db"
            sqlite3.connect(db_path).close()
            with patch.object(module.sqlite3, "connect", wraps=sqlite3.connect) as connect:
                connection = module._connect_runtime_database_readonly(db_path)
                self.assertTrue(connect.call_args.kwargs["uri"])
                self.assertTrue(connect.call_args.args[0].endswith("?mode=ro"))
                self.assertEqual(
                    module.RUNTIME_DB_BUSY_TIMEOUT_MS,
                    connection.execute("PRAGMA busy_timeout").fetchone()[0],
                )
                connection.close()

    def test_runtime_diagnostic_connection_does_not_create_missing_database(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.db"
            with self.assertRaises(sqlite3.OperationalError):
                module._connect_runtime_database_readonly(db_path)
            self.assertFalse(db_path.exists())


    def test_runtime_metadata_failure_closes_readonly_connection(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            db_path.touch()
            connection = MagicMock()
            connection.execute.side_effect = sqlite3.DatabaseError("broken metadata")
            with patch.object(
                module,
                "_connect_runtime_database_readonly",
                return_value=connection,
            ):
                result = module._scan_runtime_stuck_sessions(db_path, 300)
            connection.close.assert_called_once_with()
            self.assertTrue(
                any("broken metadata" in problem for problem in result["problems"]),
            )

    def test_pre_repair_backup_is_queryable_snapshot(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            source = sqlite3.connect(db_path)
            source.execute("CREATE TABLE marker (value TEXT)")
            source.execute("INSERT INTO marker VALUES ('before-repair')")
            source.commit()
            source.close()

            backup_path = module._backup_runtime_database(db_path)
            backup = sqlite3.connect(backup_path)
            try:
                self.assertEqual(
                    "ok", backup.execute("PRAGMA integrity_check").fetchone()[0]
                )
                self.assertEqual(
                    "before-repair",
                    backup.execute("SELECT value FROM marker").fetchone()[0],
                )
            finally:
                backup.close()

    def test_backup_includes_committed_row_still_resident_in_wal(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            writer = sqlite3.connect(db_path)
            try:
                self.assertEqual(
                    "wal", str(writer.execute("PRAGMA journal_mode=WAL").fetchone()[0])
                )
                writer.execute("PRAGMA wal_autocheckpoint=0")
                writer.execute("CREATE TABLE marker (value TEXT PRIMARY KEY)")
                writer.commit()
                writer.execute("INSERT INTO marker VALUES ('committed-in-wal')")
                writer.commit()

                wal_path = Path(f"{db_path}-wal")
                self.assertTrue(wal_path.exists())
                self.assertGreater(wal_path.stat().st_size, 0)

                backup_path = module._backup_runtime_database(db_path)
                backup = sqlite3.connect(backup_path)
                try:
                    self.assertEqual(
                        "ok", backup.execute("PRAGMA integrity_check").fetchone()[0]
                    )
                    self.assertEqual(
                        [("committed-in-wal",)],
                        backup.execute("SELECT value FROM marker").fetchall(),
                    )
                finally:
                    backup.close()
            finally:
                writer.close()

    def test_backup_destination_open_failure_closes_source_and_cleans_partial(
        self,
    ) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            db_path.touch()
            partial_path = Path(tmp) / "runtime.db.pre-repair-destination-open.sqlite3"
            sentinel = Path(tmp) / "runtime.db.pre-repair-unrelated.sqlite3"
            sentinel.write_bytes(b"preserve-me")
            source = MagicMock()

            def fail_destination_open(path: str):
                self.assertEqual(partial_path, Path(path))
                partial_path.write_bytes(b"partial")
                raise sqlite3.OperationalError("injected destination open failure")

            with (
                patch.object(
                    module.uuid,
                    "uuid4",
                    return_value=SimpleNamespace(hex="destination-open"),
                ),
                patch.object(
                    module,
                    "_connect_runtime_database_readonly",
                    return_value=source,
                ),
                patch.object(
                    module.sqlite3,
                    "connect",
                    side_effect=fail_destination_open,
                ),
            ):
                with self.assertRaisesRegex(
                    sqlite3.OperationalError, "destination open failure"
                ):
                    module._backup_runtime_database(db_path)

            source.close.assert_called_once_with()
            self.assertFalse(partial_path.exists())
            self.assertEqual(b"preserve-me", sentinel.read_bytes())

    def test_backup_interruption_closes_connections_and_cleans_partial(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            db_path.touch()
            partial_path = Path(tmp) / "runtime.db.pre-repair-mid-backup.sqlite3"
            sentinel = Path(tmp) / "runtime.db.pre-repair-unrelated.sqlite3"
            sentinel.write_bytes(b"preserve-me")
            source = MagicMock()
            destination = MagicMock()
            source.backup.side_effect = sqlite3.OperationalError(
                "injected backup interruption"
            )

            def open_destination(path: str):
                self.assertEqual(partial_path, Path(path))
                partial_path.write_bytes(b"partial")
                return destination

            with (
                patch.object(
                    module.uuid,
                    "uuid4",
                    return_value=SimpleNamespace(hex="mid-backup"),
                ),
                patch.object(
                    module,
                    "_connect_runtime_database_readonly",
                    return_value=source,
                ),
                patch.object(module.sqlite3, "connect", side_effect=open_destination),
            ):
                with self.assertRaisesRegex(
                    sqlite3.OperationalError, "backup interruption"
                ):
                    module._backup_runtime_database(db_path)

            source.backup.assert_called_once_with(destination)
            source.close.assert_called_once_with()
            destination.close.assert_called_once_with()
            self.assertFalse(partial_path.exists())
            self.assertEqual(b"preserve-me", sentinel.read_bytes())


    def _create_runtime_fixture(
        self, path: Path, *, indexes: bool = True, now_ms: int = 1_800_000_000_000
    ) -> None:
        stale = now_ms - 1_000_000
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE session (
              id TEXT PRIMARY KEY,
              parent_id TEXT,
              title TEXT NOT NULL,
              time_created INTEGER NOT NULL,
              time_updated INTEGER NOT NULL
            );
            CREATE TABLE message (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              time_created INTEGER NOT NULL,
              data TEXT NOT NULL
            );
            CREATE TABLE part (
              id TEXT PRIMARY KEY,
              message_id TEXT NOT NULL,
              session_id TEXT NOT NULL,
              time_created INTEGER NOT NULL,
              data TEXT NOT NULL
            );
            """
        )
        if indexes:
            conn.executescript(
                """
                CREATE INDEX arbitrary_parent_cover
                  ON session(parent_id, time_updated);
                CREATE INDEX arbitrary_message_cover
                  ON message(session_id, time_created, id, data);
                CREATE INDEX arbitrary_part_cover
                  ON part(message_id, id);
                """
            )

        def add_session(
            session_id: str,
            *,
            parent_id: str | None = None,
            updated: int = stale,
        ) -> None:
            conn.execute(
                "INSERT INTO session VALUES (?, ?, ?, ?, ?)",
                (session_id, parent_id, session_id, updated, updated),
            )

        def add_message(
            session_id: str,
            *,
            message_id: str | None = None,
            created: int | None = None,
            completed: bool = False,
            error: dict | None = None,
        ) -> str:
            resolved_id = message_id or f"m-{session_id}"
            payload: dict[str, object] = {"role": "assistant", "time": {}}
            if completed:
                payload["time"] = {"completed": (created or stale) + 1}
            if error is not None:
                payload["error"] = error
            conn.execute(
                "INSERT INTO message VALUES (?, ?, ?, ?)",
                (resolved_id, session_id, created or stale, json.dumps(payload)),
            )
            return resolved_id

        def add_part(
            session_id: str,
            message_id: str,
            *,
            part_id: str | None = None,
            created: int | None = None,
            part_type: str = "tool",
            tool: str = "task",
            status: str = "running",
        ) -> None:
            payload: dict[str, object] = {"type": part_type}
            if part_type == "tool":
                payload.update({"tool": tool, "state": {"status": status}})
            conn.execute(
                "INSERT INTO part VALUES (?, ?, ?, ?, ?)",
                (
                    part_id or f"p-{session_id}",
                    message_id,
                    session_id,
                    created or stale,
                    json.dumps(payload),
                ),
            )

        # Parent with a completed child while its task part remains running.
        add_session("parent-mismatch", updated=stale)
        parent_message = add_message("parent-mismatch", created=stale)
        add_part("parent-mismatch", parent_message, created=stale)
        add_session("child-complete", parent_id="parent-mismatch", updated=stale + 1000)
        add_message("child-complete", created=stale + 1000, completed=True)

        # Aborted parent with no text response after its child completed.
        add_session("parent-abort", updated=stale + 2000)
        abort_message = add_message(
            "parent-abort",
            created=stale + 2000,
            error={"name": "MessageAbortedError", "message": "The operation was aborted."},
        )
        add_part(
            "parent-abort",
            abort_message,
            created=stale + 2000,
            status="failed",
        )
        add_session("child-after-abort", parent_id="parent-abort", updated=stale + 3000)
        add_message("child-after-abort", created=stale + 3000, completed=True)

        # Both parent and delegated child remain incomplete.
        add_session("parent-stale-child", updated=stale + 4000)
        delegated_message = add_message("parent-stale-child", created=stale + 4000)
        add_part("parent-stale-child", delegated_message, created=stale + 4000)
        add_session(
            "child-still-incomplete",
            parent_id="parent-stale-child",
            updated=stale + 5000,
        )
        add_message("child-still-incomplete", created=stale + 5000)

        # Root session stuck on a recoverable running tool.
        add_session("stale-question", updated=stale + 6000)
        question_message = add_message("stale-question", created=stale + 6000)
        add_part(
            "stale-question",
            question_message,
            created=stale + 6000,
            tool="question",
        )

        # One generic stale root without children.
        add_session("generic-stale", updated=stale + 7000)
        add_message("generic-stale", created=stale + 7000)

        # A stale root with a fresh child must never be generic.
        add_session("stale-parent-fresh-child", updated=stale + 8000)
        add_message("stale-parent-fresh-child", created=stale + 8000)
        add_session(
            "fresh-child",
            parent_id="stale-parent-fresh-child",
            updated=now_ms - 1000,
        )
        add_message("fresh-child", created=now_ms - 1000)
        conn.commit()
        conn.close()

    def test_indexed_scan_matches_legacy_semantics_with_shared_clock(self) -> None:
        module = self._module()
        now_ms = 1_800_000_000_000
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            self._create_runtime_fixture(db_path, now_ms=now_ms)
            indexed = module._scan_runtime_stuck_sessions(
                db_path, 300, now_ms=now_ms
            )
            self.assertEqual("indexed_snapshot", indexed["runtime_db_scan_mode"])
            self.assertEqual(4, len(indexed["stuck_findings"]))
            self.assertEqual(1, indexed["generic_stale_count"])
            self.assertNotIn(
                "stale-parent-fresh-child",
                {
                    item.get("session_id")
                    for item in indexed["generic_stale_findings"]
                },
            )

            conn = module._connect_runtime_database_readonly(db_path)
            conn.row_factory = sqlite3.Row
            conn.create_function(
                "_runtime_scan_now_ms", 0, lambda: now_ms, deterministic=True
            )
            legacy_findings, legacy_generic, legacy_count = (
                module._scan_runtime_stuck_sessions_legacy_queries(conn, 300)
            )
            conn.close()
            legacy_findings = module._annotate_stale_findings(legacy_findings)
            legacy_generic = module._annotate_stale_findings(legacy_generic)

            def canonical(items: list[dict]) -> list[dict]:
                return sorted(
                    items,
                    key=lambda item: (
                        str(item.get("issue_type")),
                        str(item.get("session_id")),
                        str(item.get("parent_session_id")),
                        str(item.get("child_session_id")),
                    ),
                )

            self.assertEqual(canonical(legacy_findings), canonical(indexed["stuck_findings"]))
            self.assertEqual(canonical(legacy_generic), canonical(indexed["generic_stale_findings"]))
            self.assertEqual(legacy_count, indexed["generic_stale_count"])

    def test_missing_or_wrong_order_indexes_use_warned_legacy_fallback(self) -> None:
        module = self._module()
        now_ms = 1_800_000_000_000
        with tempfile.TemporaryDirectory() as tmp:
            indexed_path = Path(tmp) / "indexed.db"
            self._create_runtime_fixture(indexed_path, now_ms=now_ms)
            indexed = module._scan_runtime_stuck_sessions(
                indexed_path, 300, now_ms=now_ms
            )

            for variant in ("missing", "wrong-order"):
                with self.subTest(variant=variant):
                    db_path = Path(tmp) / f"{variant}.db"
                    self._create_runtime_fixture(
                        db_path, indexes=False, now_ms=now_ms
                    )
                    if variant == "wrong-order":
                        conn = sqlite3.connect(db_path)
                        try:
                            conn.executescript(
                                """
                                CREATE INDEX wrong_parent_order
                                  ON session(time_updated, parent_id);
                                CREATE INDEX wrong_message_order
                                  ON message(time_created, session_id, id);
                                CREATE INDEX wrong_part_order
                                  ON part(session_id, message_id);
                                """
                            )
                        finally:
                            conn.close()

                    before = self._quiescent_snapshot(db_path)
                    result = module._scan_runtime_stuck_sessions(
                        db_path, 300, now_ms=now_ms
                    )
                    after = self._quiescent_snapshot(db_path)

                    self.assertEqual(before, after)
                    self.assertEqual(
                        "legacy_fallback", result["runtime_db_scan_mode"]
                    )
                    self.assertTrue(
                        any(
                            "missing index prefixes" in warning
                            for warning in result["warnings"]
                        )
                    )
                    self.assertEqual(
                        self._canonical_findings(indexed["stuck_findings"]),
                        self._canonical_findings(result["stuck_findings"]),
                    )
                    self.assertEqual(
                        self._canonical_findings(indexed["generic_stale_findings"]),
                        self._canonical_findings(
                            result["generic_stale_findings"]
                        ),
                    )
                    self.assertEqual(
                        indexed["generic_stale_count"],
                        result["generic_stale_count"],
                    )

    def test_equal_timestamp_latest_records_use_descending_id_oracle(self) -> None:
        module = self._module()
        now_ms = 1_800_000_000_000
        stale = now_ms - 1_000_000
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            self._create_runtime_fixture(db_path, now_ms=now_ms)
            conn = sqlite3.connect(db_path)
            conn.execute(
                "INSERT INTO session VALUES (?, ?, ?, ?, ?)",
                ("tie-session", None, "tie", stale, stale),
            )
            conn.execute(
                "INSERT INTO message VALUES (?, ?, ?, ?)",
                (
                    "tie-a",
                    "tie-session",
                    stale,
                    json.dumps({"role": "assistant", "time": {}}),
                ),
            )
            conn.execute(
                "INSERT INTO part VALUES (?, ?, ?, ?, ?)",
                (
                    "tie-part",
                    "tie-a",
                    "tie-session",
                    stale,
                    json.dumps(
                        {
                            "type": "tool",
                            "tool": "question",
                            "state": {"status": "running"},
                        }
                    ),
                ),
            )
            conn.execute(
                "INSERT INTO message VALUES (?, ?, ?, ?)",
                (
                    "tie-z",
                    "tie-session",
                    stale,
                    json.dumps(
                        {
                            "role": "assistant",
                            "time": {"completed": stale + 1},
                        }
                    ),
                ),
            )
            conn.commit()
            conn.close()

            result = module._scan_runtime_stuck_sessions(db_path, 300, now_ms=now_ms)
            self.assertFalse(
                any(
                    item.get("session_id") == "tie-session"
                    for item in result["stuck_findings"]
                )
            )
            self.assertFalse(
                any(
                    item.get("session_id") == "tie-session"
                    for item in result["generic_stale_findings"]
                )
            )

    def test_scan_enforces_query_only_snapshot_and_budget(self) -> None:
        module = self._module()
        now_ms = 1_800_000_000_000
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            self._create_runtime_fixture(db_path, now_ms=now_ms)
            result = module._scan_runtime_stuck_sessions(db_path, 300, now_ms=now_ms)
        self.assertTrue(result["runtime_db_query_only"])
        self.assertTrue(result["runtime_db_snapshot_started"])
        self.assertTrue(result["runtime_db_scan_complete"])
        self.assertLessEqual(
            result["runtime_db_busy_timeout_ms"],
            result["runtime_db_scan_timeout_ms"],
        )
        self.assertNotIn("runtime_query_only_unavailable", result["remediation_codes"])

    def test_scan_budget_sets_timeout_flag_only_after_deadline(self) -> None:
        module = self._module()
        with patch.object(module.time, "monotonic", side_effect=[10.0, 10.0005, 10.002]):
            budget = module._RuntimeScanBudget(1)
            self.assertEqual(0, budget.progress())
            self.assertFalse(budget.timed_out)
            self.assertEqual(1, budget.progress())
            self.assertTrue(budget.timed_out)

    def test_rollback_journal_exclusive_lock_fails_closed_without_mutation(
        self,
    ) -> None:
        module = self._module()
        now_ms = 1_800_000_000_000
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            self._create_runtime_fixture(db_path, now_ms=now_ms)
            expected_rows = self._canonical_rows(db_path)

            for iteration in range(20):
                with self.subTest(iteration=iteration):
                    locker = sqlite3.connect(db_path)
                    try:
                        self.assertEqual(
                            "delete",
                            str(
                                locker.execute("PRAGMA journal_mode=DELETE").fetchone()[
                                    0
                                ]
                            ),
                        )
                        locker.execute("BEGIN EXCLUSIVE")
                        with patch.object(module, "RUNTIME_DB_BUSY_TIMEOUT_MS", 1):
                            result = module._scan_runtime_stuck_sessions(
                                db_path, 300, now_ms=now_ms
                            )
                    finally:
                        locker.rollback()
                        locker.close()

                    self.assertEqual(
                        "query_failed", result["runtime_db_scan_mode"]
                    )
                    self.assertIn(
                        "runtime_query_failed", result["remediation_codes"]
                    )
                    self.assertFalse(result["runtime_db_scan_complete"])
                    self.assertEqual([], result["stuck_findings"])
                    self.assertEqual([], result["generic_stale_findings"])
                    self.assertEqual(0, result["generic_stale_count"])
                    self.assertTrue(
                        any(
                            "locked" in problem.lower()
                            for problem in result["problems"]
                        )
                    )
                    self.assertEqual(expected_rows, self._canonical_rows(db_path))

    def test_malformed_queried_json_fails_closed_without_normalization(self) -> None:
        module = self._module()
        now_ms = 1_800_000_000_000
        cases = (
            ("message", "m-stale-question"),
            ("part", "p-stale-question"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            for table, row_id in cases:
                with self.subTest(table=table):
                    db_path = Path(tmp) / f"malformed-{table}.db"
                    self._create_runtime_fixture(db_path, now_ms=now_ms)
                    connection = sqlite3.connect(db_path)
                    try:
                        connection.execute(
                            f"UPDATE {table} SET data = ? WHERE id = ?",
                            ("{malformed-json", row_id),
                        )
                        connection.commit()
                    finally:
                        connection.close()

                    before = self._quiescent_snapshot(db_path)
                    result = module._scan_runtime_stuck_sessions(
                        db_path, 300, now_ms=now_ms
                    )
                    after = self._quiescent_snapshot(db_path)

                    self.assertEqual(before, after)
                    self.assertEqual(
                        "query_failed", result["runtime_db_scan_mode"]
                    )
                    self.assertIn(
                        "runtime_query_failed", result["remediation_codes"]
                    )
                    self.assertFalse(result["runtime_db_scan_complete"])
                    self.assertEqual([], result["stuck_findings"])
                    self.assertEqual([], result["generic_stale_findings"])
                    self.assertEqual(0, result["generic_stale_count"])
                    connection = sqlite3.connect(db_path)
                    try:
                        self.assertEqual(
                            "{malformed-json",
                            connection.execute(
                                f"SELECT data FROM {table} WHERE id = ?", (row_id,)
                            ).fetchone()[0],
                        )
                    finally:
                        connection.close()

    def test_open_failure_has_distinct_remediation_code(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            db_path.write_bytes(b"existing-store")
            before = db_path.read_bytes()
            with patch.object(
                module,
                "_connect_runtime_database_readonly",
                side_effect=sqlite3.OperationalError("open denied"),
            ):
                result = module._scan_runtime_stuck_sessions(db_path, 300)
            self.assertIn("runtime_db_open_failed", result["remediation_codes"])
            self.assertNotIn("runtime_query_failed", result["remediation_codes"])
            self.assertFalse(result["runtime_db_snapshot_started"])
            self.assertEqual([], result["stuck_findings"])
            self.assertEqual(before, db_path.read_bytes())
            self.assertEqual(
                [], list(Path(tmp).glob("runtime.db.pre-repair-*.sqlite3"))
            )

    @unittest.skipUnless(
        os.name == "posix"
        and hasattr(os, "geteuid")
        and os.geteuid() != 0,
        "requires a non-root POSIX host",
    )
    def test_runtime_open_respects_posix_read_denial(self) -> None:
        module = self._module()
        now_ms = 1_800_000_000_000
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            self._create_runtime_fixture(db_path, now_ms=now_ms)
            expected_rows = self._canonical_rows(db_path)
            original_mode = db_path.stat().st_mode & 0o777
            try:
                db_path.chmod(0)
                result = module._scan_runtime_stuck_sessions(
                    db_path, 300, now_ms=now_ms
                )
            finally:
                db_path.chmod(original_mode)

            if "runtime_db_open_failed" not in result["remediation_codes"]:
                self.skipTest("host filesystem does not enforce chmod read denial")
            self.assertFalse(result["runtime_db_snapshot_started"])
            self.assertEqual([], result["stuck_findings"])
            self.assertEqual(expected_rows, self._canonical_rows(db_path))
            self.assertEqual(
                [], list(Path(tmp).glob("runtime.db.pre-repair-*.sqlite3"))
            )

    def test_query_only_verification_failure_skips_scan(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            db_path.touch()
            connection = MagicMock()
            connection.in_transaction = False
            connection.execute.return_value.fetchone.return_value = (0,)
            with patch.object(
                module,
                "_connect_runtime_database_readonly",
                return_value=connection,
            ):
                result = module._scan_runtime_stuck_sessions(db_path, 300)
        self.assertIn("runtime_query_only_unavailable", result["remediation_codes"])
        self.assertFalse(result["runtime_db_snapshot_started"])
        self.assertFalse(result["runtime_db_scan_complete"])
        self.assertEqual([], result["stuck_findings"])
        connection.close.assert_called_once_with()
        self.assertFalse(
            any(call.args and call.args[0] == "BEGIN" for call in connection.execute.call_args_list)
        )

    def test_missing_schema_and_json1_are_distinct_from_open_failure(self) -> None:
        module = self._module()
        now_ms = 1_800_000_000_000
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = Path(tmp) / "schema.db"
            connection = sqlite3.connect(schema_path)
            try:
                connection.executescript(
                    """
                    CREATE TABLE session (
                      id TEXT PRIMARY KEY,
                      parent_id TEXT,
                      title TEXT NOT NULL,
                      time_created INTEGER NOT NULL,
                      time_updated INTEGER NOT NULL
                    );
                    CREATE TABLE message (
                      id TEXT PRIMARY KEY,
                      session_id TEXT NOT NULL,
                      time_created INTEGER NOT NULL,
                      data TEXT NOT NULL
                    );
                    """
                )
                connection.execute(
                    "INSERT INTO session VALUES (?, ?, ?, ?, ?)",
                    ("malformed", None, "malformed", 1, 1),
                )
                connection.execute(
                    "INSERT INTO message VALUES (?, ?, ?, ?)",
                    ("malformed-message", "malformed", 1, "{malformed-json"),
                )
                connection.commit()
            finally:
                connection.close()
            schema_before = self._quiescent_snapshot(schema_path)
            with (
                patch.object(
                    module, "_scan_runtime_stuck_sessions_indexed_queries"
                ) as indexed_scan,
                patch.object(
                    module, "_scan_runtime_stuck_sessions_legacy_queries"
                ) as legacy_scan,
            ):
                schema_result = module._scan_runtime_stuck_sessions(
                    schema_path, 300, now_ms=now_ms
                )
            self.assertEqual(schema_before, self._quiescent_snapshot(schema_path))
            self.assertIn("runtime_schema_incompatible", schema_result["remediation_codes"])
            self.assertNotIn("runtime_db_open_failed", schema_result["remediation_codes"])
            self.assertEqual("incompatible", schema_result["runtime_db_scan_mode"])
            self.assertEqual([], schema_result["stuck_findings"])
            indexed_scan.assert_not_called()
            legacy_scan.assert_not_called()

            json_path = Path(tmp) / "json.db"
            self._create_runtime_fixture(json_path, now_ms=now_ms)
            real_connection = module._connect_runtime_database_readonly(json_path)

            class Json1MissingProxy:
                def __init__(self, connection: sqlite3.Connection) -> None:
                    self.connection = connection

                @property
                def row_factory(self):
                    return self.connection.row_factory

                @row_factory.setter
                def row_factory(self, value) -> None:
                    self.connection.row_factory = value

                @property
                def in_transaction(self) -> bool:
                    return self.connection.in_transaction

                def execute(self, sql: str, *args):
                    if "json_valid" in sql:
                        raise sqlite3.OperationalError("no such function: json_valid")
                    return self.connection.execute(sql, *args)

                def create_function(self, *args, **kwargs):
                    return self.connection.create_function(*args, **kwargs)

                def set_progress_handler(self, *args, **kwargs):
                    return self.connection.set_progress_handler(*args, **kwargs)

                def rollback(self) -> None:
                    self.connection.rollback()

                def close(self) -> None:
                    self.connection.close()

            with patch.object(
                module,
                "_connect_runtime_database_readonly",
                return_value=Json1MissingProxy(real_connection),
            ):
                json_result = module._scan_runtime_stuck_sessions(json_path, 300, now_ms=now_ms)
            self.assertIn("runtime_json1_unavailable", json_result["remediation_codes"])
            self.assertNotIn("runtime_db_open_failed", json_result["remediation_codes"])
            self.assertNotIn("runtime_query_failed", json_result["remediation_codes"])
            self.assertEqual("incompatible", json_result["runtime_db_scan_mode"])
            self.assertFalse(json_result["runtime_db_scan_complete"])
            self.assertEqual([], json_result["stuck_findings"])

    def test_interrupted_query_is_timeout_only_when_budget_fired(self) -> None:
        module = self._module()
        now_ms = 1_800_000_000_000
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            self._create_runtime_fixture(db_path, now_ms=now_ms)

            timed_out_budget = MagicMock()
            timed_out_budget.timed_out = True
            timed_out_budget.progress.return_value = 1
            with (
                patch.object(module, "_RuntimeScanBudget", return_value=timed_out_budget),
                patch.object(
                    module,
                    "_scan_runtime_stuck_sessions_indexed_queries",
                    side_effect=sqlite3.OperationalError("interrupted"),
                ),
            ):
                timeout_result = module._scan_runtime_stuck_sessions(
                    db_path, 300, now_ms=now_ms
                )
            self.assertIn("runtime_scan_timeout", timeout_result["remediation_codes"])
            self.assertNotIn("runtime_query_failed", timeout_result["remediation_codes"])
            self.assertEqual("timeout", timeout_result["runtime_db_scan_mode"])
            self.assertEqual([], timeout_result["stuck_findings"])

            interrupted_budget = MagicMock()
            interrupted_budget.timed_out = False
            interrupted_budget.progress.return_value = 0
            with (
                patch.object(module, "_RuntimeScanBudget", return_value=interrupted_budget),
                patch.object(
                    module,
                    "_scan_runtime_stuck_sessions_indexed_queries",
                    side_effect=sqlite3.OperationalError("interrupted"),
                ),
            ):
                query_result = module._scan_runtime_stuck_sessions(
                    db_path, 300, now_ms=now_ms
                )
            self.assertIn("runtime_query_failed", query_result["remediation_codes"])
            self.assertNotIn("runtime_scan_timeout", query_result["remediation_codes"])
            self.assertEqual("query_failed", query_result["runtime_db_scan_mode"])

    def test_concurrent_wal_commit_does_not_mix_reader_snapshot(self) -> None:
        module = self._module()
        now_ms = 1_800_000_000_000
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            self._create_runtime_fixture(db_path, now_ms=now_ms)
            setup = sqlite3.connect(db_path)
            setup.execute("PRAGMA journal_mode=WAL")
            setup.close()

            original_scan = module._scan_runtime_stuck_sessions_indexed_queries

            for iteration in range(20):
                with self.subTest(iteration=iteration):
                    outside = sqlite3.connect(db_path)
                    try:
                        initial_count = int(
                            outside.execute("SELECT COUNT(*) FROM session").fetchone()[
                                0
                            ]
                        )
                    finally:
                        outside.close()

                    reader_ready = threading.Barrier(2, timeout=5)
                    writer_done = threading.Barrier(2, timeout=5)
                    observed_counts: list[int] = []
                    writer_errors: list[BaseException] = []

                    def wrapped_scan(
                        connection, *, stale_seconds: int, now_ms: int
                    ):
                        reader_ready.wait()
                        writer_done.wait()
                        observed_counts.append(
                            int(
                                connection.execute(
                                    "SELECT COUNT(*) FROM session"
                                ).fetchone()[0]
                            )
                        )
                        return original_scan(
                            connection,
                            stale_seconds=stale_seconds,
                            now_ms=now_ms,
                        )

                    def writer() -> None:
                        connection = sqlite3.connect(db_path)
                        try:
                            reader_ready.wait()
                            session_id = f"writer-after-snapshot-{iteration}"
                            connection.execute(
                                "INSERT INTO session VALUES (?, ?, ?, ?, ?)",
                                (session_id, None, "writer", now_ms, now_ms),
                            )
                            connection.commit()
                            writer_done.wait()
                        except BaseException as exc:
                            writer_errors.append(exc)
                            reader_ready.abort()
                            writer_done.abort()
                        finally:
                            connection.close()

                    writer_thread = threading.Thread(
                        target=writer, name=f"runtime-wal-writer-{iteration}"
                    )
                    writer_thread.start()
                    try:
                        with patch.object(
                            module,
                            "_scan_runtime_stuck_sessions_indexed_queries",
                            side_effect=wrapped_scan,
                        ):
                            result = module._scan_runtime_stuck_sessions(
                                db_path, 300, now_ms=now_ms
                            )
                    finally:
                        writer_thread.join(timeout=5)

                    self.assertFalse(writer_thread.is_alive())
                    self.assertEqual([], writer_errors)
                    self.assertEqual([initial_count], observed_counts)
                    self.assertTrue(result["runtime_db_scan_complete"])
                    outside = sqlite3.connect(db_path)
                    try:
                        self.assertEqual(
                            initial_count + 1,
                            int(
                                outside.execute(
                                    "SELECT COUNT(*) FROM session"
                                ).fetchone()[0]
                            ),
                        )
                    finally:
                        outside.close()

    def test_repair_preview_and_unconfirmed_generic_apply_do_not_mutate(self) -> None:
        module = self._module()
        now_ms = int(module.time.time() * 1000)
        cases = (
            {
                "name": "preview",
                "apply_changes": False,
                "include_generic": False,
                "scope_session_id": "stale-question",
                "expected_candidates": 1,
            },
            {
                "name": "generic-not-included",
                "apply_changes": True,
                "include_generic": False,
                "scope_session_id": "generic-stale",
                "expected_candidates": 0,
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            for case in cases:
                with self.subTest(case=case["name"]):
                    db_path = Path(tmp) / f"{case['name']}.db"
                    self._create_runtime_fixture(db_path, now_ms=now_ms)
                    before = self._quiescent_snapshot(db_path)
                    with patch.object(module, "_backup_runtime_database") as backup:
                        result = module._repair_runtime_stuck_sessions(
                            db_path,
                            stale_seconds=300,
                            apply_changes=bool(case["apply_changes"]),
                            include_generic=bool(case["include_generic"]),
                            scope_session_id=str(case["scope_session_id"]),
                        )
                    backup.assert_not_called()
                    self.assertEqual(before, self._quiescent_snapshot(db_path))
                    self.assertEqual(
                        case["expected_candidates"], result["candidate_count"]
                    )
                    self.assertEqual(0, result["repaired_count"])
                    self.assertEqual([], result["repairs"])
                    self.assertIsNone(result["backup_path"])

    def test_scoped_repair_backup_matches_prestate_and_preserves_unknown_fields(
        self,
    ) -> None:
        module = self._module()
        now_ms = int(module.time.time() * 1000)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            self._create_runtime_fixture(db_path, now_ms=now_ms)
            connection = sqlite3.connect(db_path)
            try:
                message_data = json.loads(
                    connection.execute(
                        "SELECT data FROM message WHERE id = ?",
                        ("m-stale-question",),
                    ).fetchone()[0]
                )
                message_data["unknown_message_field"] = {"keep": [1, 2, 3]}
                part_data = json.loads(
                    connection.execute(
                        "SELECT data FROM part WHERE id = ?",
                        ("p-stale-question",),
                    ).fetchone()[0]
                )
                part_data["unknown_part_field"] = {"keep": True}
                part_data["state"]["unknown_state_field"] = "opaque"
                connection.execute(
                    "UPDATE message SET data = ? WHERE id = ?",
                    (json.dumps(message_data), "m-stale-question"),
                )
                connection.execute(
                    "UPDATE part SET data = ? WHERE id = ?",
                    (json.dumps(part_data), "p-stale-question"),
                )
                connection.commit()
            finally:
                connection.close()

            before_rows = self._canonical_rows(db_path)
            result = module._repair_runtime_stuck_sessions(
                db_path,
                stale_seconds=300,
                apply_changes=True,
                include_generic=False,
                scope_session_id="stale-question",
            )

            self.assertEqual(1, result["candidate_count"])
            self.assertEqual(1, result["repaired_count"])
            backup_path = Path(str(result["backup_path"]))
            self.assertTrue(backup_path.exists())
            backup = sqlite3.connect(backup_path)
            try:
                self.assertEqual(
                    "ok", backup.execute("PRAGMA integrity_check").fetchone()[0]
                )
            finally:
                backup.close()
            self.assertEqual(before_rows, self._canonical_rows(backup_path))

            after_rows = self._canonical_rows(db_path)
            selected_ids = {
                "session": "stale-question",
                "message": "m-stale-question",
                "part": "p-stale-question",
            }
            for table, rows in before_rows.items():
                before_unrelated = [
                    row for row in rows if row[0] != selected_ids[table]
                ]
                after_unrelated = [
                    row for row in after_rows[table] if row[0] != selected_ids[table]
                ]
                self.assertEqual(before_unrelated, after_unrelated)

            connection = sqlite3.connect(db_path)
            try:
                repaired_message = json.loads(
                    connection.execute(
                        "SELECT data FROM message WHERE id = ?",
                        ("m-stale-question",),
                    ).fetchone()[0]
                )
                repaired_part = json.loads(
                    connection.execute(
                        "SELECT data FROM part WHERE id = ?",
                        ("p-stale-question",),
                    ).fetchone()[0]
                )
            finally:
                connection.close()
            self.assertIsNotNone(repaired_message["time"]["completed"])
            self.assertEqual(
                {"keep": [1, 2, 3]},
                repaired_message["unknown_message_field"],
            )
            self.assertEqual("failed", repaired_part["state"]["status"])
            self.assertEqual(
                "opaque", repaired_part["state"]["unknown_state_field"]
            )
            self.assertEqual(
                {"keep": True}, repaired_part["unknown_part_field"]
            )

    def test_repair_compare_and_swap_race_preserves_terminal_json_bytes(self) -> None:
        module = self._module()
        real_backup = module._backup_runtime_database
        now_ms = int(module.time.time() * 1000)
        with tempfile.TemporaryDirectory() as tmp:
            for iteration in range(20):
                race_field = "message" if iteration % 2 == 0 else "part"
                with self.subTest(iteration=iteration, race_field=race_field):
                    db_path = Path(tmp) / f"cas-{iteration}.db"
                    self._create_runtime_fixture(db_path, now_ms=now_ms)
                    raced_rows: dict[str, str] = {}

                    def backup_then_publish_terminal_state(path: Path) -> Path:
                        backup_path = real_backup(path)
                        connection = sqlite3.connect(path)
                        try:
                            if race_field == "message":
                                terminal_json = (
                                    '{"role":"assistant","time":{"completed":123},'
                                    '"terminal_marker":"exact-message-bytes"}'
                                )
                                connection.execute(
                                    "UPDATE message SET data = ? WHERE id = ?",
                                    (terminal_json, "m-stale-question"),
                                )
                            else:
                                terminal_json = (
                                    '{"type":"tool","tool":"question",'
                                    '"state":{"status":"failed"},'
                                    '"terminal_marker":"exact-part-bytes"}'
                                )
                                connection.execute(
                                    "UPDATE part SET data = ? WHERE id = ?",
                                    (terminal_json, "p-stale-question"),
                                )
                            connection.commit()
                            raced_rows["message"] = str(
                                connection.execute(
                                    "SELECT data FROM message WHERE id = ?",
                                    ("m-stale-question",),
                                ).fetchone()[0]
                            )
                            raced_rows["part"] = str(
                                connection.execute(
                                    "SELECT data FROM part WHERE id = ?",
                                    ("p-stale-question",),
                                ).fetchone()[0]
                            )
                        finally:
                            connection.close()
                        return backup_path

                    with patch.object(
                        module,
                        "_backup_runtime_database",
                        side_effect=backup_then_publish_terminal_state,
                    ):
                        result = module._repair_runtime_stuck_sessions(
                            db_path,
                            stale_seconds=300,
                            apply_changes=True,
                            include_generic=False,
                            scope_session_id="stale-question",
                        )

                    self.assertEqual(1, result["candidate_count"])
                    self.assertEqual(0, result["repaired_count"])
                    self.assertEqual([], result["repairs"])
                    connection = sqlite3.connect(db_path)
                    try:
                        self.assertEqual(
                            raced_rows["message"],
                            connection.execute(
                                "SELECT data FROM message WHERE id = ?",
                                ("m-stale-question",),
                            ).fetchone()[0],
                        )
                        self.assertEqual(
                            raced_rows["part"],
                            connection.execute(
                                "SELECT data FROM part WHERE id = ?",
                                ("p-stale-question",),
                            ).fetchone()[0],
                        )
                    finally:
                        connection.close()

    def test_first_round_commit_failure_rolls_back_and_reports_no_repairs(
        self,
    ) -> None:
        module = self._module()
        now_ms = int(module.time.time() * 1000)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            self._create_runtime_fixture(db_path, now_ms=now_ms)
            scan = module._scan_runtime_stuck_sessions(
                db_path, 300, now_ms=now_ms
            )
            candidate = next(
                finding
                for finding in scan["stuck_findings"]
                if finding["issue_type"] == "stale_running_tool"
            )
            before_rows = self._canonical_rows(db_path)
            backup_path = module._backup_runtime_database(db_path)
            repair_connection = _CommitFaultConnection(
                sqlite3.connect(db_path), fail_on_commit=1
            )

            with (
                patch.object(
                    module,
                    "_scan_runtime_stuck_sessions",
                    return_value=self._scan_with_findings(scan, [candidate]),
                ),
                patch.object(
                    module,
                    "_backup_runtime_database",
                    return_value=backup_path,
                ),
                patch.object(
                    module.sqlite3, "connect", return_value=repair_connection
                ),
            ):
                result = module._repair_runtime_stuck_sessions(
                    db_path,
                    stale_seconds=300,
                    apply_changes=True,
                    include_generic=False,
                )

            self.assertEqual(before_rows, self._canonical_rows(db_path))
            self.assertEqual(0, result["repaired_count"])
            self.assertEqual([], result["repairs"])
            self.assertTrue(
                any("injected commit failure" in item for item in result["problems"])
            )

    def test_later_commit_failure_preserves_only_prior_committed_reports(self) -> None:
        module = self._module()
        now_ms = int(module.time.time() * 1000)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            self._create_runtime_fixture(db_path, now_ms=now_ms)
            scan = module._scan_runtime_stuck_sessions(
                db_path, 300, now_ms=now_ms
            )
            first_candidate = next(
                finding
                for finding in scan["stuck_findings"]
                if finding["issue_type"] == "stale_running_tool"
            )
            second_candidate = next(
                finding
                for finding in scan["stuck_findings"]
                if finding["issue_type"] == "parent_child_mismatch"
            )
            before_rows = self._canonical_rows(db_path)
            backup_path = module._backup_runtime_database(db_path)
            repair_connection = _CommitFaultConnection(
                sqlite3.connect(db_path), fail_on_commit=2
            )
            scans = (
                self._scan_with_findings(scan, [first_candidate]),
                self._scan_with_findings(scan, [second_candidate]),
            )

            with (
                patch.object(
                    module, "_scan_runtime_stuck_sessions", side_effect=scans
                ),
                patch.object(
                    module,
                    "_backup_runtime_database",
                    return_value=backup_path,
                ),
                patch.object(
                    module.sqlite3, "connect", return_value=repair_connection
                ),
            ):
                result = module._repair_runtime_stuck_sessions(
                    db_path,
                    stale_seconds=300,
                    apply_changes=True,
                    include_generic=False,
                )

            self.assertEqual(1, result["repaired_count"])
            self.assertEqual(
                ["stale_running_tool"],
                [repair["issue_type"] for repair in result["repairs"]],
            )
            after_rows = self._canonical_rows(db_path)
            before_messages = {row[0]: row for row in before_rows["message"]}
            after_messages = {row[0]: row for row in after_rows["message"]}
            before_parts = {row[0]: row for row in before_rows["part"]}
            after_parts = {row[0]: row for row in after_rows["part"]}
            before_sessions = {row[0]: row for row in before_rows["session"]}
            after_sessions = {row[0]: row for row in after_rows["session"]}
            self.assertNotEqual(
                before_messages["m-stale-question"],
                after_messages["m-stale-question"],
            )
            self.assertEqual(
                before_messages["m-parent-mismatch"],
                after_messages["m-parent-mismatch"],
            )
            self.assertEqual(
                before_parts["p-parent-mismatch"],
                after_parts["p-parent-mismatch"],
            )
            self.assertEqual(
                before_sessions["parent-mismatch"],
                after_sessions["parent-mismatch"],
            )

    def test_quiescent_scan_leaves_database_bytes_schema_and_rows_unchanged(self) -> None:
        module = self._module()
        now_ms = 1_800_000_000_000
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            self._create_runtime_fixture(db_path, now_ms=now_ms)

            def snapshot() -> tuple[str, list[tuple], dict[str, int], str]:
                digest = hashlib.sha256(db_path.read_bytes()).hexdigest()
                connection = sqlite3.connect(db_path)
                try:
                    schema = connection.execute(
                        "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
                    ).fetchall()
                    counts = {
                        table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                        for table in ("session", "message", "part")
                    }
                    journal = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
                finally:
                    connection.close()
                return digest, schema, counts, journal

            before = snapshot()
            result = module._scan_runtime_stuck_sessions(db_path, 300, now_ms=now_ms)
            after = snapshot()
            self.assertEqual(before, after)
            self.assertTrue(result["runtime_db_query_only"])
            self.assertTrue(result["runtime_db_scan_complete"])
            self.assertFalse(Path(f"{db_path}-wal").exists())

    def test_index_prefix_detection_accepts_arbitrary_names_and_supersets(self) -> None:
        module = self._module()
        indexes = {
            "anything": ["session_id", "time_created", "id", "data"],
        }
        self.assertTrue(
            module._has_index_prefix(indexes, ("session_id", "time_created", "id"))
        )
        self.assertFalse(
            module._has_index_prefix(indexes, ("time_created", "session_id"))
        )

if __name__ == "__main__":
    unittest.main()
