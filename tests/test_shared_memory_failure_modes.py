from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

OWNED_INDEXES = {
    "idx_memories_scope_namespace_updated",
    "idx_memories_session_id",
    "idx_memories_source_ref_unique",
}


class _TrackingConnection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.close_calls = 0

    def __getattr__(self, name: str):
        return getattr(self.connection, name)

    def close(self) -> None:
        self.close_calls += 1
        self.connection.close()


class _CommitFailureConnection(_TrackingConnection):
    def __init__(self, connection: sqlite3.Connection, *, after: bool) -> None:
        super().__init__(connection)
        self.after = after

    def commit(self) -> None:
        if self.after:
            self.connection.commit()
        raise sqlite3.OperationalError(
            "injected post-commit failure"
            if self.after
            else "injected pre-commit failure"
        )


class SharedMemoryFailureModeTest(unittest.TestCase):
    def _runtime_module(self):
        return importlib.reload(importlib.import_module("shared_memory_runtime"))

    @contextmanager
    def _bound_lifecycle_modules(self, root: Path, name: str):
        db_path = root / name
        with patch.dict(
            os.environ,
            {"MY_OPENCODE_SHARED_MEMORY_PATH": str(db_path)},
            clear=False,
        ):
            runtime = importlib.reload(
                importlib.import_module("shared_memory_runtime")
            )
            lifecycle = importlib.reload(
                importlib.import_module("memory_lifecycle_command")
            )
            effective_path = lifecycle.runtime_path().resolve()
            self.assertEqual(db_path.resolve(), effective_path)
            self.assertTrue(effective_path.is_relative_to(root.resolve()))
            yield runtime, lifecycle, db_path

        importlib.reload(importlib.import_module("shared_memory_runtime"))
        importlib.reload(importlib.import_module("memory_lifecycle_command"))

    def _insert_memory(
        self,
        connection: sqlite3.Connection,
        memory_id: str,
        *,
        tags_json: str = '["sqlite", "test"]',
        links_json: str = '["memory-ref:source"]',
        source_type: str | None = None,
        source_ref: str | None = None,
        pinned: bool = False,
        archived: bool = False,
    ) -> None:
        connection.execute(
            """
            INSERT INTO memories(
                id, kind, scope, namespace, title, content, summary,
                tags_json, tags_text, links_json, source_type, source_ref,
                session_id, cwd, pinned, archived, confidence, created_at,
                updated_at
            ) VALUES (?, 'note', 'repo', 'repo', ?, ?, ?, ?, 'sqlite test', ?,
                      ?, ?, NULL, ?, ?, ?, 60, ?, ?)
            """,
            (
                memory_id,
                f"title-{memory_id}",
                f"content-{memory_id}",
                f"summary-{memory_id}",
                tags_json,
                links_json,
                source_type,
                source_ref,
                str(REPO_ROOT),
                1 if pinned else 0,
                1 if archived else 0,
                "2026-07-30T00:00:00Z",
                "2026-07-30T00:00:00Z",
            ),
        )

    def _canonical_memories(self, db_path: Path) -> list[tuple]:
        connection = sqlite3.connect(db_path)
        try:
            return connection.execute(
                "SELECT * FROM memories ORDER BY id"
            ).fetchall()
        finally:
            connection.close()

    def _canonical_store(self, db_path: Path) -> dict[str, list[tuple] | None]:
        connection = sqlite3.connect(db_path)
        try:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                )
            }
            fts_rows = (
                connection.execute(
                    "SELECT rowid, id, title, summary, content, tags "
                    "FROM memory_fts ORDER BY rowid"
                ).fetchall()
                if "memory_fts" in tables
                else None
            )
            return {
                "memories": connection.execute(
                    "SELECT * FROM memories ORDER BY id"
                ).fetchall(),
                "meta": connection.execute(
                    "SELECT key, value FROM meta ORDER BY key"
                ).fetchall(),
                "memory_fts": fts_rows,
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

    def _with_checksum(self, payload: dict) -> dict:
        unsigned = dict(payload)
        unsigned.pop("sha256", None)
        canonical = json.dumps(
            unsigned, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return {**unsigned, "sha256": hashlib.sha256(canonical).hexdigest()}

    def _assert_checksum_valid(self, payload: dict) -> None:
        expected = payload.get("sha256")
        self.assertIsInstance(expected, str)
        unsigned = dict(payload)
        unsigned.pop("sha256", None)
        canonical = json.dumps(
            unsigned, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        self.assertEqual(expected, hashlib.sha256(canonical).hexdigest())

    def _capture_import(
        self,
        lifecycle,
        source: Path,
        *,
        conflict: str | None = None,
        dry_run: bool = False,
    ) -> tuple[int, dict]:
        output = io.StringIO()
        args = ["--path", str(source), "--json"]
        if conflict is not None:
            args[2:2] = ["--conflict", conflict]
        if dry_run:
            args.append("--dry-run")
        with redirect_stdout(output):
            status = lifecycle.cmd_import(args)
        return status, json.loads(output.getvalue())

    def _write_import(self, source: Path, payload: dict) -> None:
        source.write_text(
            json.dumps(self._with_checksum(payload), indent=2) + "\n",
            encoding="utf-8",
        )

    def test_real_wal_writer_contention_is_busy_and_commits_no_row(self) -> None:
        runtime = self._runtime_module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "shared-memory.db"
            holder = runtime.connect(db_path)
            contender = runtime.connect(db_path)
            try:
                self._insert_memory(holder, "baseline")
                holder.commit()
                expected_rows = self._canonical_memories(db_path)
                self.assertEqual(
                    "wal", str(holder.execute("PRAGMA journal_mode").fetchone()[0])
                )
                self.assertEqual(
                    "wal",
                    str(contender.execute("PRAGMA journal_mode").fetchone()[0]),
                )
                contender.execute("PRAGMA busy_timeout=1")

                for iteration in range(20):
                    with self.subTest(iteration=iteration):
                        try:
                            holder.execute("BEGIN IMMEDIATE")
                            self._insert_memory(holder, f"uncommitted-{iteration}")
                            with self.assertRaises(sqlite3.OperationalError) as raised:
                                contender.execute("BEGIN IMMEDIATE")
                            error_code = getattr(
                                raised.exception, "sqlite_errorcode", None
                            )
                            self.assertIsNotNone(error_code)
                            self.assertEqual(
                                sqlite3.SQLITE_BUSY,
                                int(error_code) & 0xFF,
                            )
                            self.assertFalse(contender.in_transaction)
                        finally:
                            contender.rollback()
                            holder.rollback()
                        self.assertEqual(
                            expected_rows, self._canonical_memories(db_path)
                        )
            finally:
                contender.close()
                holder.close()

    def test_malformed_persisted_json_raises_without_changing_rows(self) -> None:
        runtime = self._runtime_module()
        with tempfile.TemporaryDirectory() as tmp:
            for column in ("tags_json", "links_json"):
                with self.subTest(column=column):
                    db_path = Path(tmp) / f"malformed-{column}.db"
                    connection = runtime.connect(db_path)
                    try:
                        self._insert_memory(connection, "malformed")
                        connection.execute(
                            f"UPDATE memories SET {column} = ? WHERE id = ?",
                            ("{malformed-json", "malformed"),
                        )
                        connection.commit()
                        before = connection.execute(
                            "SELECT * FROM memories ORDER BY id"
                        ).fetchall()
                        with self.assertRaises(json.JSONDecodeError):
                            runtime.active_memory_records(connection)
                        after = connection.execute(
                            "SELECT * FROM memories ORDER BY id"
                        ).fetchall()
                        self.assertEqual(before, after)
                        self.assertEqual(
                            "{malformed-json",
                            connection.execute(
                                f"SELECT {column} FROM memories WHERE id = ?",
                                ("malformed",),
                            ).fetchone()[0],
                        )
                    finally:
                        connection.close()

    def test_absent_store_initializes_schema_version_and_owned_indexes(self) -> None:
        runtime = self._runtime_module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "new" / "shared-memory.db"
            self.assertFalse(db_path.exists())
            connection = runtime.connect(db_path)
            try:
                self.assertEqual(
                    str(runtime.SCHEMA_VERSION),
                    str(
                        connection.execute(
                            "SELECT value FROM meta WHERE key = 'schema_version'"
                        ).fetchone()[0]
                    ),
                )
                indexes = {
                    str(row[1])
                    for row in connection.execute("PRAGMA index_list(memories)")
                }
                self.assertTrue(OWNED_INDEXES.issubset(indexes))
                self.assertEqual(
                    "wal", str(connection.execute("PRAGMA journal_mode").fetchone()[0])
                )
            finally:
                connection.close()

    def test_schema_migration_supports_only_versionless_legacy_store(self) -> None:
        runtime = self._runtime_module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "shared-memory.db"
            connection = runtime.connect(db_path)
            self._insert_memory(connection, "legacy")
            connection.execute("DELETE FROM meta WHERE key = 'schema_version'")
            connection.commit()
            connection.close()

            before_rows = self._canonical_memories(db_path)
            preview = runtime.migrate_schema(db_path, dry_run=True)
            self.assertEqual("PASS", preview["result"])
            self.assertTrue(preview["would_change"])
            self.assertFalse(preview["changed"])
            probe = sqlite3.connect(db_path)
            try:
                self.assertIsNone(
                    probe.execute(
                        "SELECT value FROM meta WHERE key = 'schema_version'"
                    ).fetchone()
                )
            finally:
                probe.close()
            applied = runtime.migrate_schema(db_path, dry_run=False)
            self.assertEqual("PASS", applied["result"])
            self.assertTrue(applied["changed"])
            self.assertEqual("committed", applied["transaction_outcome"])
            self.assertEqual(before_rows, self._canonical_memories(db_path))
            probe = sqlite3.connect(db_path)
            try:
                self.assertEqual(
                    str(runtime.SCHEMA_VERSION),
                    str(
                        probe.execute(
                            "SELECT value FROM meta WHERE key = 'schema_version'"
                        ).fetchone()[0]
                    ),
                )
            finally:
                probe.close()

    def test_schema_migration_never_creates_absent_store(self) -> None:
        runtime = self._runtime_module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing" / "shared-memory.db"
            report = runtime.migrate_schema(db_path, dry_run=False)
            self.assertEqual("FAIL", report["result"])
            self.assertEqual("shared_memory_database_missing", report["reason_code"])
            self.assertFalse(db_path.exists())
            self.assertFalse(db_path.parent.exists())

    def test_schema_migration_rejects_noncanonical_indexes(self) -> None:
        runtime = self._runtime_module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "shared-memory.db"
            connection = runtime.connect(db_path)
            connection.execute("DROP INDEX idx_memories_session_id")
            connection.execute(
                "UPDATE meta SET value = '0' WHERE key = 'schema_version'"
            )
            connection.commit()
            connection.close()

            report = runtime.migrate_schema(db_path, dry_run=False)
            self.assertEqual("FAIL", report["result"])
            self.assertEqual(
                "shared_memory_schema_migration_unsupported", report["reason_code"]
            )
            probe = sqlite3.connect(db_path)
            try:
                self.assertEqual(
                    "0",
                    probe.execute(
                        "SELECT value FROM meta WHERE key = 'schema_version'"
                    ).fetchone()[0],
                )
            finally:
                probe.close()

    def test_schema_migration_rejects_duplicate_source_keys(self) -> None:
        runtime = self._runtime_module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "shared-memory.db"
            connection = runtime.connect(db_path)
            self._insert_memory(connection, "first")
            self._insert_memory(connection, "second")
            connection.execute("DROP INDEX idx_memories_source_ref_unique")
            connection.execute(
                "UPDATE memories SET source_type = 'task', source_ref = 'dup'"
            )
            connection.execute(
                "UPDATE meta SET value = '0' WHERE key = 'schema_version'"
            )
            connection.commit()
            connection.close()

            report = runtime.migrate_schema(db_path, dry_run=True)
            self.assertEqual("FAIL", report["result"])
            self.assertEqual(
                "shared_memory_schema_migration_unsupported", report["reason_code"]
            )

    def test_schema_migration_rejects_expression_index_fingerprint(self) -> None:
        runtime = self._runtime_module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "shared-memory.db"
            connection = runtime.connect(db_path)
            connection.execute("DROP INDEX idx_memories_source_ref_unique")
            connection.execute(
                """
                CREATE UNIQUE INDEX idx_memories_source_ref_unique
                ON memories(source_type, source_ref, lower(title))
                """
            )
            connection.execute(
                "UPDATE meta SET value = '0' WHERE key = 'schema_version'"
            )
            connection.commit()
            connection.close()

            report = runtime.migrate_schema(db_path, dry_run=True)
            self.assertEqual("FAIL", report["result"])
            self.assertIn(
                "idx_memories_source_ref_unique", report["incompatible_indexes"]
            )

    def test_schema_migration_rejects_incompatible_fts_object(self) -> None:
        runtime = self._runtime_module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "shared-memory.db"
            connection = runtime.connect(db_path)
            connection.execute("DROP TABLE memory_fts")
            connection.execute(
                "CREATE TABLE memory_fts(id TEXT, title TEXT, summary TEXT)"
            )
            connection.execute(
                "UPDATE meta SET value = '0' WHERE key = 'schema_version'"
            )
            connection.commit()
            connection.close()

            report = runtime.migrate_schema(db_path, dry_run=True)
            self.assertEqual("FAIL", report["result"])
            self.assertFalse(report["fts_structure_ok"])

    def test_current_schema_rejects_owned_table_triggers(self) -> None:
        runtime = self._runtime_module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "shared-memory.db"
            connection = runtime.connect(db_path)
            connection.execute(
                """
                CREATE TRIGGER test_memory_guard AFTER INSERT ON memories
                BEGIN
                    SELECT 1;
                END
                """
            )
            connection.commit()
            connection.close()

            report = runtime.inspect_schema(db_path)
            self.assertEqual("FAIL", report["result"])
            self.assertIn("test_memory_guard", report["owned_triggers"])
            with self.assertRaisesRegex(RuntimeError, "owned-table triggers"):
                runtime.connect_readonly(db_path)

    def test_reopen_recreates_owned_index_without_changing_rows_or_version(
        self,
    ) -> None:
        runtime = self._runtime_module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "shared-memory.db"
            connection = runtime.connect(db_path)
            try:
                self._insert_memory(connection, "preserved")
                connection.commit()
                connection.execute("DROP INDEX idx_memories_session_id")
                connection.commit()
            finally:
                connection.close()

            before_rows = self._canonical_memories(db_path)
            before_version = sqlite3.connect(db_path)
            try:
                version = before_version.execute(
                    "SELECT value FROM meta WHERE key = 'schema_version'"
                ).fetchone()[0]
            finally:
                before_version.close()

            reopened = runtime.connect(db_path)
            try:
                indexes = {
                    str(row[1])
                    for row in reopened.execute("PRAGMA index_list(memories)")
                }
                self.assertIn("idx_memories_session_id", indexes)
                self.assertEqual(
                    version,
                    reopened.execute(
                        "SELECT value FROM meta WHERE key = 'schema_version'"
                    ).fetchone()[0],
                )
            finally:
                reopened.close()
            self.assertEqual(before_rows, self._canonical_memories(db_path))

    def test_incompatible_version_raises_with_rows_and_version_unchanged(self) -> None:
        runtime = self._runtime_module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "shared-memory.db"
            connection = runtime.connect(db_path)
            try:
                self._insert_memory(connection, "preserved")
                connection.commit()
            finally:
                connection.close()

            fixture = sqlite3.connect(db_path)
            try:
                self.assertEqual(
                    "wal", str(fixture.execute("PRAGMA journal_mode").fetchone()[0])
                )
                fixture.execute(
                    "UPDATE meta SET value = '999' WHERE key = 'schema_version'"
                )
                fixture.commit()
            finally:
                fixture.close()
            before_rows = self._canonical_memories(db_path)
            before_schema = self._schema_rows(db_path)
            before_meta = self._canonical_store(db_path)["meta"]

            real_connect = sqlite3.connect
            opened: list[sqlite3.Connection] = []

            def tracking_connect(*args, **kwargs):
                tracked = real_connect(*args, **kwargs)
                opened.append(tracked)
                return tracked

            try:
                with patch.object(
                    runtime.sqlite3, "connect", side_effect=tracking_connect
                ), self.assertRaisesRegex(
                    RuntimeError, "schema version 999 is incompatible"
                ):
                    runtime.connect(db_path)
            finally:
                for tracked in opened:
                    tracked.close()

            self.assertEqual(before_rows, self._canonical_memories(db_path))
            self.assertEqual(before_schema, self._schema_rows(db_path))
            self.assertEqual(before_meta, self._canonical_store(db_path)["meta"])

    def test_injected_open_denial_preserves_existing_store(self) -> None:
        runtime = self._runtime_module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "shared-memory.db"
            connection = runtime.connect(db_path)
            try:
                self._insert_memory(connection, "preserved")
                connection.commit()
            finally:
                connection.close()
            before = self._canonical_store(db_path)

            with patch.object(
                runtime.sqlite3,
                "connect",
                side_effect=PermissionError("injected open denial"),
            ), self.assertRaisesRegex(PermissionError, "open denial"):
                runtime.connect(db_path)

            self.assertEqual(before, self._canonical_store(db_path))
            self.assertEqual([], list(Path(tmp).glob("*.pre-import-*.json")))

    @unittest.skipUnless(
        os.name == "posix"
        and hasattr(os, "geteuid")
        and os.geteuid() != 0,
        "requires a non-root POSIX host",
    )
    def test_store_open_respects_posix_read_denial(self) -> None:
        runtime = self._runtime_module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "shared-memory.db"
            connection = runtime.connect(db_path)
            try:
                self._insert_memory(connection, "preserved")
                connection.commit()
            finally:
                connection.close()
            before = self._canonical_store(db_path)
            original_mode = db_path.stat().st_mode & 0o777
            opened: sqlite3.Connection | None = None
            error: BaseException | None = None
            try:
                db_path.chmod(0)
                try:
                    opened = runtime.connect(db_path)
                except (PermissionError, sqlite3.OperationalError) as exc:
                    error = exc
            finally:
                if opened is not None:
                    opened.close()
                db_path.chmod(original_mode)

            if error is None:
                self.skipTest("host filesystem does not enforce chmod read denial")
            self.assertEqual(before, self._canonical_store(db_path))

    def test_invalid_imports_fail_before_connection_or_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self._bound_lifecycle_modules(
                root, "target.db"
            ) as (runtime, lifecycle, db_path):
                connection = runtime.connect(db_path)
                try:
                    self._insert_memory(connection, "preserved")
                    connection.commit()
                finally:
                    connection.close()
                before = self._canonical_store(db_path)

                cases = [
                    ("malformed", "{not-json", None),
                    (
                        "checksum",
                        json.dumps(
                            {
                                "schema_version": runtime.SCHEMA_VERSION,
                                "entries": [],
                                "archive": [],
                                "sha256": "wrong",
                            }
                        ),
                        "shared-memory export checksum mismatch",
                    ),
                    (
                        "schema",
                        json.dumps(
                            {"schema_version": 999, "entries": [], "archive": []}
                        ),
                        "incompatible shared-memory export schema",
                    ),
                    (
                        "containers",
                        json.dumps(
                            {
                                "schema_version": runtime.SCHEMA_VERSION,
                                "entries": {},
                                "archive": [],
                            }
                        ),
                        "entries and archive must be lists",
                    ),
                    (
                        "entry",
                        json.dumps(
                            {
                                "schema_version": runtime.SCHEMA_VERSION,
                                "entries": ["not-an-object"],
                                "archive": [],
                            }
                        ),
                        "every imported entry must be an object",
                    ),
                    (
                        "nested-confidence",
                        json.dumps(
                            {
                                "schema_version": runtime.SCHEMA_VERSION,
                                "entries": [{"confidence": "60"}],
                                "archive": [],
                            }
                        ),
                        "entries[0].confidence must be an integer from 0 to 100 or null",
                    ),
                    (
                        "nested-tags",
                        json.dumps(
                            {
                                "schema_version": runtime.SCHEMA_VERSION,
                                "entries": [
                                    {"title": "valid first row"},
                                    {"tags": ["valid", 7]},
                                ],
                                "archive": [],
                            }
                        ),
                        "entries[1].tags must be a list of strings or null",
                    ),
                    (
                        "archive-boolean",
                        json.dumps(
                            {
                                "schema_version": runtime.SCHEMA_VERSION,
                                "entries": [],
                                "archive": [{"archived": "yes"}],
                            }
                        ),
                        "archive[0].archived must be a boolean or null",
                    ),
                    (
                        "archive-active",
                        json.dumps(
                            {
                                "schema_version": runtime.SCHEMA_VERSION,
                                "entries": [],
                                "archive": [{"archived": False}],
                            }
                        ),
                        "archive[0].archived must be true for archive entries",
                    ),
                    (
                        "source-pair",
                        json.dumps(
                            {
                                "schema_version": runtime.SCHEMA_VERSION,
                                "entries": [{"source_type": "git"}],
                                "archive": [],
                            }
                        ),
                        "entries[0].source_type and entries[0].source_ref "
                        "must be provided together",
                    ),
                ]
                with patch.object(
                    lifecycle,
                    "connect",
                    side_effect=AssertionError("validation must precede connect"),
                ) as connect_spy:
                    for name, body, expected_error in cases:
                        with self.subTest(case=name):
                            source = root / f"{name}.json"
                            source.write_text(body, encoding="utf-8")
                            if expected_error is None:
                                with self.assertRaises(json.JSONDecodeError):
                                    lifecycle.cmd_import(
                                        ["--path", str(source), "--json"]
                                    )
                            else:
                                status, payload = self._capture_import(
                                    lifecycle, source
                                )
                                self.assertEqual(1, status)
                                self.assertEqual("FAIL", payload["result"])
                                self.assertEqual(expected_error, payload["error"])

                connect_spy.assert_not_called()
                self.assertEqual(before, self._canonical_store(db_path))
                self.assertEqual([], list(root.glob("*.pre-import-*.json")))

    def test_import_dry_run_reports_not_started_without_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self._bound_lifecycle_modules(
                root, "target.db"
            ) as (runtime, lifecycle, db_path):
                source = root / "incoming.json"
                self._write_import(
                    source,
                    {
                        "version": 2,
                        "schema_version": runtime.SCHEMA_VERSION,
                        "entries": [{"id": "preview-only", "title": "preview"}],
                        "archive": [],
                    },
                )
                with patch.object(
                    lifecycle,
                    "connect",
                    side_effect=AssertionError("dry-run must not connect"),
                ):
                    status, payload = self._capture_import(
                        lifecycle, source, dry_run=True
                    )

                self.assertEqual(0, status)
                self.assertEqual("PASS", payload["result"])
                self.assertEqual("not_started", payload["transaction_outcome"])
                self.assertFalse(payload["commit_attempted"])
                self.assertIsNone(payload["backup_path"])
                self.assertEqual([], list(root.glob("*.pre-import-*.json")))

    def test_valid_import_validates_before_backup_and_closes_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self._bound_lifecycle_modules(
                root, "target.db"
            ) as (runtime, lifecycle, db_path):
                existing = runtime.connect(db_path)
                try:
                    self._insert_memory(
                        existing,
                        "existing-source",
                        source_type="git",
                        source_ref="commit:one",
                        pinned=True,
                    )
                    existing.commit()
                finally:
                    existing.close()
                source = root / "incoming.json"
                self._write_import(
                    source,
                    {
                        "version": 2,
                        "schema_version": runtime.SCHEMA_VERSION,
                        "path": str(db_path),
                        "entries": [
                            {
                                "id": "source-id-is-not-used",
                                "kind": "decision",
                                "scope": "shared",
                                "namespace": "imports",
                                "title": "source-backed",
                                "content": "source content",
                                "summary": "source summary",
                                "tags": ["import"],
                                "links": [],
                                "source_type": "git",
                                "source_ref": "commit:one",
                                "session_id": "session-one",
                                "cwd": str(root),
                                "pinned": False,
                                "archived": True,
                                "confidence": 80,
                                "created_at": "2026-07-30T01:00:00Z",
                                "updated_at": "2026-07-30T02:00:00Z",
                            },
                            {
                                "id": "legacy-defaults",
                                "title": "legacy",
                                "content": "legacy content",
                                "tags": None,
                                "links": None,
                                "pinned": None,
                                "archived": None,
                            },
                        ],
                        "archive": [{"id": "archive-container-only", "title": "archive"}],
                    },
                )

                real_connect = lifecycle.connect
                opened: list[_TrackingConnection] = []

                def capture_connection() -> _TrackingConnection:
                    connection = _TrackingConnection(real_connect())
                    opened.append(connection)
                    return connection

                backup_saw_transaction: list[bool] = []
                real_export = lifecycle._export_payload

                def capture_backup(connection: sqlite3.Connection) -> dict:
                    backup_saw_transaction.append(connection.in_transaction)
                    return real_export(connection)

                with (
                    patch.object(
                        lifecycle, "connect", side_effect=capture_connection
                    ),
                    patch.object(
                        lifecycle, "_export_payload", side_effect=capture_backup
                    ),
                ):
                    status, payload = self._capture_import(lifecycle, source)

                self.assertEqual(0, status)
                self.assertEqual("PASS", payload["result"])
                self.assertEqual("committed", payload["transaction_outcome"])
                self.assertTrue(payload["commit_attempted"])
                self.assertTrue(Path(payload["backup_path"]).is_file())
                self.assertEqual([True], backup_saw_transaction)
                self.assertEqual(1, len(opened))
                self.assertEqual(1, opened[0].close_calls)
                connection = sqlite3.connect(db_path)
                try:
                    self.assertEqual(
                        1,
                        connection.execute(
                            "SELECT COUNT(*) FROM memories WHERE source_ref = ?",
                            ("commit:one",),
                        ).fetchone()[0],
                    )
                    source_row = connection.execute(
                        "SELECT kind, scope, pinned, archived, created_at, updated_at "
                        "FROM memories WHERE source_ref = ?",
                        ("commit:one",),
                    ).fetchone()
                    self.assertEqual(
                        (
                            "decision",
                            "shared",
                            0,
                            1,
                            "2026-07-30T00:00:00Z",
                            "2026-07-30T02:00:00Z",
                        ),
                        tuple(source_row),
                    )
                    defaults = connection.execute(
                        "SELECT kind, scope, tags_json, links_json, pinned, archived "
                        "FROM memories WHERE id = ?",
                        ("legacy-defaults",),
                    ).fetchone()
                    self.assertEqual(
                        ("note", "repo", "[]", "[]", 0, 0), tuple(defaults)
                    )
                    archive_container_only = connection.execute(
                        "SELECT archived FROM memories WHERE id = ?",
                        ("archive-container-only",),
                    ).fetchone()
                    self.assertEqual((1,), tuple(archive_container_only))
                finally:
                    connection.close()

    def test_conflict_skip_preserves_source_and_id_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self._bound_lifecycle_modules(
                root, "target.db"
            ) as (runtime, lifecycle, db_path):
                connection = runtime.connect(db_path)
                try:
                    self._insert_memory(
                        connection,
                        "source-existing",
                        source_type="git",
                        source_ref="commit:existing",
                    )
                    self._insert_memory(connection, "id-existing")
                    connection.commit()
                finally:
                    connection.close()

                source = root / "incoming.json"
                self._write_import(
                    source,
                    {
                        "version": 2,
                        "schema_version": runtime.SCHEMA_VERSION,
                        "entries": [
                            {
                                "id": "source-replacement-id",
                                "title": "source replacement",
                                "content": "must be skipped",
                                "source_type": "git",
                                "source_ref": "commit:existing",
                            },
                            {
                                "id": "id-existing",
                                "title": "id replacement",
                                "content": "must be skipped",
                            },
                            {
                                "id": "new-memory",
                                "title": "new memory",
                                "content": "must be imported",
                            },
                        ],
                        "archive": [],
                    },
                )

                status, payload = self._capture_import(
                    lifecycle, source, conflict="skip"
                )

                self.assertEqual(0, status)
                self.assertEqual("PASS", payload["result"])
                self.assertEqual(2, payload["skipped"])
                connection = sqlite3.connect(db_path)
                try:
                    self.assertEqual(
                        "title-source-existing",
                        connection.execute(
                            "SELECT title FROM memories WHERE id = ?",
                            ("source-existing",),
                        ).fetchone()[0],
                    )
                    self.assertEqual(
                        "title-id-existing",
                        connection.execute(
                            "SELECT title FROM memories WHERE id = ?",
                            ("id-existing",),
                        ).fetchone()[0],
                    )
                    self.assertEqual(
                        1,
                        connection.execute(
                            "SELECT COUNT(*) FROM memories WHERE id = ?",
                            ("new-memory",),
                        ).fetchone()[0],
                    )
                finally:
                    connection.close()

    def test_backup_publication_failure_rolls_back_without_partial_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self._bound_lifecycle_modules(
                root, "target.db"
            ) as (runtime, lifecycle, db_path):
                connection = runtime.connect(db_path)
                try:
                    self._insert_memory(connection, "baseline")
                    runtime._rebuild_fts(connection)
                    connection.commit()
                finally:
                    connection.close()
                before = self._canonical_store(db_path)

                source = root / "incoming.json"
                self._write_import(
                    source,
                    {
                        "version": 2,
                        "schema_version": runtime.SCHEMA_VERSION,
                        "entries": [{"id": "incoming", "title": "incoming"}],
                        "archive": [],
                    },
                )

                with patch.object(
                    lifecycle.os,
                    "replace",
                    side_effect=OSError("injected backup publish failure"),
                ):
                    status, payload = self._capture_import(lifecycle, source)

                self.assertEqual(1, status)
                self.assertEqual("FAIL", payload["result"])
                self.assertEqual("rolled_back", payload["transaction_outcome"])
                self.assertEqual("backup", payload["failure_phase"])
                self.assertFalse(payload["commit_attempted"])
                self.assertIn("injected backup publish failure", payload["error"])
                self.assertIsNone(payload["backup_path"])
                self.assertEqual(before, self._canonical_store(db_path))
                self.assertEqual([], list(root.glob("*.pre-import-*.json")))
                self.assertEqual([], list(root.glob(".*.tmp")))

    def test_interrupted_import_rolls_back_and_backup_restores_identically(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self._bound_lifecycle_modules(
                root, "target.db"
            ) as (runtime, lifecycle, db_path):
                with patch.object(runtime, "_ensure_fts", return_value=False):
                    connection = runtime.connect(db_path)
                    try:
                        self._insert_memory(connection, "baseline")
                        connection.commit()
                        pre_import_export = lifecycle._export_payload(connection)
                    finally:
                        connection.close()
                    self._assert_checksum_valid(pre_import_export)
                    before = self._canonical_store(db_path)
                    self.assertIsNone(before["memory_fts"])

                    incoming = self._with_checksum(
                        {
                            "version": 2,
                            "schema_version": runtime.SCHEMA_VERSION,
                            "path": str(db_path),
                            "entries": [
                                {
                                    "id": "incoming-one",
                                    "title": "incoming one",
                                    "content": "first write",
                                    "summary": "first write",
                                    "tags": ["import"],
                                    "links": [],
                                    "created_at": "2026-07-30T01:00:00Z",
                                    "updated_at": "2026-07-30T01:00:00Z",
                                },
                                {
                                    "id": "incoming-two",
                                    "title": "incoming two",
                                    "content": "second write",
                                    "summary": "second write",
                                    "tags": ["import"],
                                    "links": [],
                                    "created_at": "2026-07-30T02:00:00Z",
                                    "updated_at": "2026-07-30T02:00:00Z",
                                },
                            ],
                            "archive": [],
                        }
                    )
                    source = root / "incoming.json"
                    source.write_text(
                        json.dumps(incoming, indent=2) + "\n", encoding="utf-8"
                    )

                    real_import_row = lifecycle._import_row
                    import_calls = 0

                    def fail_after_second_row(conn, entry):
                        nonlocal import_calls
                        import_calls += 1
                        real_import_row(conn, entry)
                        if import_calls == 2:
                            raise RuntimeError("injected second-row interruption")

                    real_lifecycle_connect = lifecycle.connect
                    opened: list[_TrackingConnection] = []

                    def capture_connection() -> _TrackingConnection:
                        captured = _TrackingConnection(real_lifecycle_connect())
                        opened.append(captured)
                        return captured

                    try:
                        with (
                            patch.object(
                                lifecycle,
                                "_import_row",
                                side_effect=fail_after_second_row,
                            ),
                            patch.object(
                                lifecycle,
                                "connect",
                                side_effect=capture_connection,
                            ),
                        ):
                            status, payload = self._capture_import(
                                lifecycle, source
                            )
                    finally:
                        for captured in opened:
                            if captured.close_calls == 0:
                                captured.close()

                    self.assertEqual(2, import_calls)
                    self.assertEqual(1, opened[0].close_calls)
                    self.assertEqual(1, status)
                    self.assertEqual("FAIL", payload["result"])
                    self.assertIn(
                        "injected second-row interruption", payload["error"]
                    )
                    self.assertEqual(before, self._canonical_store(db_path))
                    backup_paths = list(root.glob("incoming.pre-import-*.json"))
                    self.assertEqual(1, len(backup_paths))
                    self.assertEqual(str(backup_paths[0]), payload["backup_path"])
                    backup_payload = json.loads(
                        backup_paths[0].read_text(encoding="utf-8")
                    )
                    self._assert_checksum_valid(backup_payload)
                    self.assertEqual(pre_import_export, backup_payload)
                    expected_memories = self._canonical_memories(db_path)

            with self._bound_lifecycle_modules(
                root, "restored.db"
            ) as (restored_runtime, restored_lifecycle, restored_path), patch.object(
                restored_runtime, "_ensure_fts", return_value=False
            ):
                real_restore_connect = restored_lifecycle.connect
                restored_connections: list[sqlite3.Connection] = []

                def capture_restore_connection():
                    captured = real_restore_connect()
                    restored_connections.append(captured)
                    return captured

                try:
                    with patch.object(
                        restored_lifecycle,
                        "connect",
                        side_effect=capture_restore_connection,
                    ):
                        status, payload = self._capture_import(
                            restored_lifecycle, backup_paths[0]
                        )
                finally:
                    for captured in restored_connections:
                        captured.close()

                self.assertEqual(0, status)
                self.assertEqual("PASS", payload["result"])
                self.assertEqual(
                    expected_memories,
                    self._canonical_memories(restored_path),
                )
                self.assertIsNone(
                    self._canonical_store(restored_path)["memory_fts"]
                )

    def test_import_commit_outcomes_are_explicit(self) -> None:
        for after, expected_outcome in ((False, "rolled_back"), (True, "unknown")):
            with self.subTest(after=after), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                with self._bound_lifecycle_modules(
                    root, f"commit-{after}/target.db"
                ) as (runtime, lifecycle, db_path):
                    connection = runtime.connect(db_path)
                    try:
                        self._insert_memory(connection, "baseline")
                        connection.commit()
                    finally:
                        connection.close()

                    source = root / f"commit-{after}.json"
                    self._write_import(
                        source,
                        {
                            "version": 2,
                            "schema_version": runtime.SCHEMA_VERSION,
                            "entries": [{"id": "imported", "title": "imported"}],
                            "archive": [],
                        },
                    )
                    real_connect = lifecycle.connect
                    opened: list[_CommitFailureConnection] = []

                    def failing_connect() -> _CommitFailureConnection:
                        failing = _CommitFailureConnection(real_connect(), after=after)
                        opened.append(failing)
                        return failing

                    with patch.object(
                        lifecycle, "connect", side_effect=failing_connect
                    ):
                        status, payload = self._capture_import(lifecycle, source)

                    self.assertEqual(1, status)
                    self.assertEqual("FAIL", payload["result"])
                    self.assertEqual(expected_outcome, payload["transaction_outcome"])
                    self.assertEqual("commit", payload["failure_phase"])
                    self.assertTrue(payload["commit_attempted"])
                    self.assertIsNotNone(payload["backup_path"])
                    self.assertTrue(Path(payload["backup_path"]).is_file())
                    self.assertEqual(1, opened[0].close_calls)
                    self.assertIn(
                        "import transaction outcome unknown"
                        if after
                        else "import rolled back",
                        payload["error"],
                    )
                    rows = self._canonical_memories(db_path)
                    self.assertEqual(after, any(row[0] == "imported" for row in rows))


if __name__ == "__main__":
    unittest.main()
