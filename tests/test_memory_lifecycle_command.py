from __future__ import annotations

import hashlib
import importlib
import io
import json
import multiprocessing
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _hold_committed_wal_row(
    db_path: str,
    ready: multiprocessing.synchronize.Event,
    release: multiprocessing.synchronize.Event,
) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute(
            """
            INSERT INTO memories(
                id, kind, scope, namespace, title, content, summary,
                tags_json, tags_text, links_json, source_type, source_ref,
                session_id, cwd, pinned, archived, confidence, created_at,
                updated_at
            ) VALUES (
                'wal-only', 'note', 'repo', 'wal-ns', 'private title',
                'private content', 'private summary', '[]', '', '[]',
                NULL, NULL, NULL, '/private/cwd', 0, 0, 60,
                '2000-01-01T00:00:00Z', '2000-01-01T00:00:00Z'
            )
            """
        )
        connection.commit()
        ready.set()
        if not release.wait(timeout=15):
            raise RuntimeError("timed out waiting to release WAL writer")
    finally:
        connection.close()


class _CommitFailureConnection:
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

    def execute(self, *args, **kwargs):
        return self.connection.execute(*args, **kwargs)

    def commit(self) -> None:
        raise sqlite3.OperationalError("injected pre-commit failure")

    def rollback(self) -> None:
        self.connection.rollback()

    def close(self) -> None:
        self.connection.close()


class _CommitThenRaiseConnection(_CommitFailureConnection):
    def commit(self) -> None:
        self.connection.commit()
        raise sqlite3.OperationalError("injected post-commit failure")


class _CloseFailureConnection(_CommitFailureConnection):
    def commit(self) -> None:
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
        raise sqlite3.OperationalError("injected close failure")


class MemoryLifecycleCommandTest(unittest.TestCase):
    @contextmanager
    def _bound_modules(self, root: Path, relative_path: str = "store/memory.db"):
        db_path = root / relative_path
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
            self.assertEqual(db_path.resolve(), lifecycle.runtime_path().resolve())
            self.assertTrue(db_path.resolve().is_relative_to(root.resolve()))
            yield runtime, lifecycle, db_path

    def _insert_memory(
        self,
        connection: sqlite3.Connection,
        memory_id: str,
        *,
        scope: str = "repo",
        namespace: str = "Secret-Namespace",
        pinned: bool = False,
        archived: bool = False,
        created_at: str = "2000-01-01T00:00:00Z",
        updated_at: str = "2000-01-01T00:00:00Z",
        title: str = "DO-NOT-LEAK title",
        content: str = "DO-NOT-LEAK content",
        summary: str = "DO-NOT-LEAK summary",
        source_type: str | None = None,
        source_ref: str | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO memories(
                id, kind, scope, namespace, title, content, summary,
                tags_json, tags_text, links_json, source_type, source_ref,
                session_id, cwd, pinned, archived, confidence, created_at,
                updated_at
            ) VALUES (?, 'note', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 60, ?, ?)
            """,
            (
                memory_id,
                scope,
                namespace,
                title,
                content,
                summary,
                json.dumps(["DO-NOT-LEAK-tag"]),
                "DO-NOT-LEAK-tag",
                json.dumps(["DO-NOT-LEAK-link"]),
                source_type,
                source_ref,
                "DO-NOT-LEAK-session",
                "/DO-NOT-LEAK/cwd",
                1 if pinned else 0,
                1 if archived else 0,
                created_at,
                updated_at,
            ),
        )

    def _capture(self, function, argv: list[str]) -> tuple[int, str, dict | None]:
        output = io.StringIO()
        with redirect_stdout(output):
            status = function(list(argv))
        rendered = output.getvalue()
        payload = json.loads(rendered) if "--json" in argv and rendered.strip() else None
        return status, rendered, payload

    def _filesystem_snapshot(self, parent: Path) -> dict:
        if not parent.exists():
            return {"exists": False}

        def metadata(path: Path) -> dict:
            details = path.stat()
            payload = {
                "device": details.st_dev,
                "inode": details.st_ino,
                "mode": stat.S_IMODE(details.st_mode),
                "uid": details.st_uid,
                "gid": details.st_gid,
                "links": details.st_nlink,
                "size": details.st_size,
                "mtime_ns": details.st_mtime_ns,
                "ctime_ns": details.st_ctime_ns,
            }
            if path.is_file():
                payload["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            return payload

        children = sorted(parent.iterdir(), key=lambda item: item.name)
        return {
            "exists": True,
            "directory": metadata(parent),
            "entries": {child.name: metadata(child) for child in children},
        }

    def _logical_snapshot(self, db_path: Path) -> dict[str, list[tuple]]:
        connection = sqlite3.connect(db_path)
        try:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                )
            }
            snapshot = {
                "memories": connection.execute(
                    "SELECT * FROM memories ORDER BY id"
                ).fetchall(),
                "meta": connection.execute(
                    "SELECT key, value FROM meta ORDER BY key"
                ).fetchall(),
                "schema": connection.execute(
                    "SELECT type, name, tbl_name, sql FROM sqlite_master "
                    "ORDER BY type, name"
                ).fetchall(),
            }
            if "memory_fts" in tables:
                snapshot["memory_fts"] = connection.execute(
                    "SELECT rowid, id, title, summary, content, tags "
                    "FROM memory_fts ORDER BY rowid"
                ).fetchall()
            return snapshot
        finally:
            connection.close()

    def test_absent_store_dry_runs_create_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self._bound_modules(root) as (runtime, lifecycle, db_path):
                self.assertFalse(db_path.parent.exists())
                with (
                    patch.object(
                        lifecycle,
                        "connect",
                        side_effect=AssertionError("dry-run reached writable connect"),
                    ),
                    patch.object(
                        runtime,
                        "initialize",
                        side_effect=AssertionError("dry-run initialized schema"),
                    ),
                ):
                    cleanup = self._capture(
                        lifecycle.cmd_cleanup, ["--dry-run", "--json"]
                    )
                    compress = self._capture(
                        lifecycle.cmd_compress, ["--dry-run", "--json"]
                    )

                for status, _rendered, payload in (cleanup, compress):
                    self.assertEqual(0, status)
                    self.assertEqual("PASS", payload["result"])
                    self.assertEqual(0, payload["candidate_count"])
                    self.assertEqual([], payload["candidate_sample"])
                    self.assertEqual(0, payload["changed_count"])
                    self.assertEqual(0, payload["entry_count"])
                    self.assertEqual(0, payload["archive_count"])
                    self.assertTrue(payload["whole_store"])
                    self.assertFalse(payload["automatic_export"])
                self.assertFalse(db_path.parent.exists())

    def test_cleanup_preview_is_scoped_private_bounded_and_physically_readonly(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self._bound_modules(root) as (runtime, lifecycle, db_path):
                connection = lifecycle.connect()
                try:
                    for index in range(25):
                        self._insert_memory(
                            connection,
                            f"candidate-{index:02d}",
                            updated_at="2000-01-01T00:00:00+00:00",
                            source_type="DO-NOT-LEAK-source-type",
                            source_ref=f"DO-NOT-LEAK-source-ref-{index:02d}",
                        )
                    self._insert_memory(
                        connection,
                        "other-scope",
                        scope="shared",
                    )
                    self._insert_memory(
                        connection,
                        "other-namespace",
                        namespace="Other-Namespace",
                    )
                    connection.commit()
                finally:
                    connection.close()

                self.assertFalse(Path(f"{db_path}-wal").exists())
                self.assertFalse(Path(f"{db_path}-shm").exists())

                logical_before = self._logical_snapshot(db_path)
                filesystem_before = self._filesystem_snapshot(db_path.parent)
                real_sqlite_connect = sqlite3.connect
                with (
                    patch.object(
                        lifecycle,
                        "connect",
                        side_effect=AssertionError("dry-run reached writable connect"),
                    ),
                    patch.object(
                        runtime.sqlite3,
                        "connect",
                        wraps=real_sqlite_connect,
                    ) as sqlite_connect,
                ):
                    status, rendered, payload = self._capture(
                        lifecycle.cmd_cleanup,
                        [
                            "--older-days",
                            "1",
                            "--scope",
                            "repo",
                            "--namespace",
                            "Secret-Namespace",
                            "--dry-run",
                            "--json",
                        ],
                    )
                self.assertTrue(
                    any(
                        call.args and call.args[0] == ":memory:"
                        for call in sqlite_connect.call_args_list
                    )
                )

                self.assertEqual(0, status)
                self.assertEqual(25, payload["candidate_count"])
                self.assertEqual(20, len(payload["candidate_sample"]))
                self.assertTrue(payload["candidate_sample_truncated"])
                self.assertEqual(
                    [f"candidate-{index:02d}" for index in range(20)],
                    [item["id"] for item in payload["candidate_sample"]],
                )
                for item in payload["candidate_sample"]:
                    self.assertEqual(
                        {"id", "scope", "reason_code"}, set(item)
                    )
                    self.assertEqual("repo", item["scope"])
                    self.assertEqual("older_than_cutoff", item["reason_code"])
                self.assertNotIn("DO-NOT-LEAK", rendered)
                self.assertEqual("repo", payload["scope"])
                self.assertEqual("Secret-Namespace", payload["namespace"])
                self.assertFalse(payload["whole_store"])
                self.assertEqual(0, payload["changed_count"])
                self.assertEqual(25, payload["moved"])
                self.assertEqual(27, payload["entry_count"])
                self.assertEqual(0, payload["archive_count"])
                self.assertEqual(2, payload["projected_entry_count"])
                self.assertEqual(25, payload["projected_archive_count"])
                filesystem_after = self._filesystem_snapshot(db_path.parent)
                logical_after = self._logical_snapshot(db_path)
                self.assertEqual(logical_before, logical_after)
                self.assertEqual(
                    filesystem_before,
                    filesystem_after,
                )
                status, rendered, _payload = self._capture(
                    lifecycle.cmd_cleanup,
                    [
                        "--older-days",
                        "1",
                        "--scope",
                        "repo",
                        "--namespace",
                        "Secret-Namespace",
                        "--dry-run",
                    ],
                )
                self.assertEqual(0, status)
                self.assertNotIn("DO-NOT-LEAK", rendered)

    def test_cleanup_filter_dimensions_and_unfiltered_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self._bound_modules(root) as (_runtime, lifecycle, _db_path):
                connection = lifecycle.connect()
                try:
                    for scope in ("repo", "shared"):
                        for namespace in ("Namespace-A", "Namespace-B"):
                            self._insert_memory(
                                connection,
                                f"{scope}-{namespace}",
                                scope=scope,
                                namespace=namespace,
                            )
                    connection.commit()
                finally:
                    connection.close()

                cases = (
                    (["--scope", "repo"], 2, False),
                    (["--namespace", "Namespace-A"], 2, False),
                    (
                        ["--scope", "repo", "--namespace", "Namespace-A"],
                        1,
                        False,
                    ),
                    (
                        ["--scope", "session", "--namespace", "Namespace-A"],
                        0,
                        False,
                    ),
                    ([], 4, True),
                )
                for filters, expected, whole_store in cases:
                    with self.subTest(filters=filters):
                        status, _rendered, payload = self._capture(
                            lifecycle.cmd_cleanup,
                            [
                                "--older-days",
                                "1",
                                *filters,
                                "--dry-run",
                                "--json",
                            ],
                        )
                        self.assertEqual(0, status)
                        self.assertEqual(expected, payload["candidate_count"])
                        self.assertEqual(expected, payload["moved"])
                        self.assertEqual(0, payload["changed_count"])
                        self.assertEqual(whole_store, payload["whole_store"])

    def test_invalid_lifecycle_arguments_fail_before_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self._bound_modules(root) as (runtime, lifecycle, _db_path):
                with (
                    patch.object(
                        lifecycle,
                        "connect",
                        side_effect=AssertionError("invalid args reached writable open"),
                    ) as writable,
                    patch.object(
                        lifecycle,
                        "connect_readonly",
                        side_effect=AssertionError("invalid args reached readonly open"),
                    ) as readonly,
                ):
                    cases = (
                        (lifecycle.cmd_cleanup, ["--scope", "invalid", "--dry-run"]),
                        (
                            lifecycle.cmd_cleanup,
                            ["--scope", "repo", "--scope", "shared", "--dry-run"],
                        ),
                        (lifecycle.cmd_cleanup, ["--unknown", "--dry-run"]),
                        (lifecycle.cmd_compress, ["--namespace", "", "--dry-run"]),
                        (lifecycle.cmd_compress, ["trailing", "--dry-run"]),
                        (lifecycle.cmd_restore, ["--id", ""]),
                        (lifecycle.cmd_restore, ["--id", "one", "--id", "two"]),
                        (lifecycle.cmd_restore, ["--id", "one", "--unknown"]),
                    )
                    for function, argv in cases:
                        with self.subTest(function=function.__name__, argv=argv):
                            status, _rendered, _payload = self._capture(function, argv)
                            self.assertNotEqual(0, status)
                writable.assert_not_called()
                readonly.assert_not_called()

    def test_compression_filters_tuple_keys_timestamps_and_all_pins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self._bound_modules(root) as (_runtime, lifecycle, db_path):
                connection = lifecycle.connect()
                try:
                    shared = {
                        "scope": "repo",
                        "namespace": "Secret-Namespace",
                        "source_type": None,
                        "source_ref": None,
                    }
                    self._insert_memory(
                        connection,
                        "chronological-old",
                        title="chronological",
                        content="chronological",
                        summary="chronological",
                        updated_at="2026-07-27T01:00:00+02:00",
                        **shared,
                    )
                    self._insert_memory(
                        connection,
                        "chronological-new",
                        title="chronological",
                        content="chronological",
                        summary="chronological",
                        updated_at="2026-07-26T23:30:00+00:00",
                        **shared,
                    )
                    for memory_id, pinned, updated_at in (
                        ("pin-old", True, "2026-07-25T00:00:00Z"),
                        ("pin-new", True, "2026-07-26T00:00:00Z"),
                        ("unpin-a", False, "2026-07-27T00:00:00Z"),
                        ("unpin-b", False, "2026-07-28T00:00:00Z"),
                    ):
                        self._insert_memory(
                            connection,
                            memory_id,
                            pinned=pinned,
                            title="pinned group",
                            content="pinned group",
                            summary="pinned group",
                            updated_at=updated_at,
                            **shared,
                        )
                    for memory_id, title, summary in (
                        ("collision-a-drop", "a:b", "c"),
                        ("collision-a-keep", "a:b", "c"),
                        ("collision-b-drop", "a", "b:c"),
                        ("collision-b-keep", "a", "b:c"),
                    ):
                        self._insert_memory(
                            connection,
                            memory_id,
                            title=title,
                            summary=summary,
                            content="delimiter content",
                            updated_at="2026-07-29T00:00:00Z",
                            **shared,
                        )
                    for memory_id in ("outside-a", "outside-b"):
                        self._insert_memory(
                            connection,
                            memory_id,
                            scope="shared",
                            namespace="Secret-Namespace",
                            title="outside",
                            content="outside",
                            summary="outside",
                        )
                    connection.commit()
                finally:
                    connection.close()
                before = self._logical_snapshot(db_path)

                status, _rendered, preview = self._capture(
                    lifecycle.cmd_compress,
                    [
                        "--scope",
                        "repo",
                        "--namespace",
                        "Secret-Namespace",
                        "--dry-run",
                        "--json",
                    ],
                )
                self.assertEqual(0, status)
                self.assertEqual(5, preview["candidate_count"])
                expected_ids = [
                    "chronological-old",
                    "collision-a-drop",
                    "collision-b-drop",
                    "unpin-a",
                    "unpin-b",
                ]
                self.assertEqual(
                    expected_ids,
                    [item["id"] for item in preview["candidate_sample"]],
                )
                keepers = {
                    item["id"]: item["keeper_id"]
                    for item in preview["candidate_sample"]
                }
                self.assertEqual("chronological-new", keepers["chronological-old"])
                self.assertEqual("pin-new", keepers["unpin-a"])
                self.assertEqual("pin-new", keepers["unpin-b"])
                self.assertEqual("collision-a-keep", keepers["collision-a-drop"])
                self.assertEqual("collision-b-keep", keepers["collision-b-drop"])
                self.assertEqual(preview["before"], preview["after"])
                self.assertEqual(5, preview["removed"])
                self.assertEqual(0, preview["changed_count"])
                self.assertEqual(before, self._logical_snapshot(db_path))

                status, _rendered, applied = self._capture(
                    lifecycle.cmd_compress,
                    [
                        "--scope",
                        "repo",
                        "--namespace",
                        "Secret-Namespace",
                        "--json",
                    ],
                )
                self.assertEqual(0, status)
                self.assertEqual(5, applied["changed_count"])
                self.assertEqual(5, applied["removed"])
                connection = sqlite3.connect(db_path)
                try:
                    archived = {
                        str(row[0])
                        for row in connection.execute(
                            "SELECT id FROM memories WHERE archived = 1"
                        )
                    }
                    pinned_active = {
                        str(row[0])
                        for row in connection.execute(
                            "SELECT id FROM memories WHERE pinned = 1 AND archived = 0"
                        )
                    }
                finally:
                    connection.close()
                self.assertEqual(set(expected_ids), archived)
                self.assertEqual({"pin-old", "pin-new"}, pinned_active)
                self.assertTrue({"outside-a", "outside-b"}.isdisjoint(archived))
                self.assertEqual([], list(root.glob("*.pre-*.json")))

    def test_cleanup_apply_restore_and_doctor_preserve_fts_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self._bound_modules(root) as (runtime, lifecycle, db_path):
                connection = runtime.connect(db_path)
                try:
                    self._insert_memory(
                        connection,
                        "restore-me",
                        title="restore unique phrase",
                        content="restore unique phrase",
                        summary="restore unique phrase",
                    )
                    self._insert_memory(
                        connection,
                        "pinned-old",
                        pinned=True,
                        title="pinned",
                        content="pinned",
                        summary="pinned",
                    )
                    self._insert_memory(
                        connection,
                        "fresh",
                        title="fresh",
                        content="fresh",
                        summary="fresh",
                        created_at="2099-01-01T00:00:00Z",
                        updated_at="2099-01-01T00:00:00Z",
                    )
                    runtime._rebuild_fts(connection)
                    connection.commit()
                    self.assertTrue(runtime.fts_enabled(connection))
                    fts_before = connection.execute(
                        "SELECT rowid, id, title, summary, content, tags "
                        "FROM memory_fts ORDER BY rowid"
                    ).fetchall()
                finally:
                    connection.close()

                traces: list[str] = []
                traced = runtime.connect(db_path)
                traced.set_trace_callback(traces.append)
                with patch.object(lifecycle, "connect", return_value=traced):
                    status, _rendered, cleanup = self._capture(
                        lifecycle.cmd_cleanup,
                        ["--older-days", "1", "--json"],
                    )
                self.assertEqual(0, status)
                self.assertEqual(1, cleanup["candidate_count"])
                self.assertEqual(1, cleanup["changed_count"])
                begin_index = next(
                    index
                    for index, statement in enumerate(traces)
                    if statement.strip().upper() == "BEGIN IMMEDIATE"
                )
                first_memory_select = next(
                    index
                    for index, statement in enumerate(traces)
                    if "FROM memories" in statement
                )
                self.assertLess(begin_index, first_memory_select)

                connection = runtime.connect(db_path)
                try:
                    self.assertEqual(
                        1,
                        connection.execute(
                            "SELECT archived FROM memories WHERE id = 'restore-me'"
                        ).fetchone()[0],
                    )
                    self.assertEqual(
                        fts_before,
                        connection.execute(
                            "SELECT rowid, id, title, summary, content, tags "
                            "FROM memory_fts ORDER BY rowid"
                        ).fetchall(),
                    )
                    self.assertEqual(
                        [],
                        runtime.find_memories(
                            connection,
                            query="restore unique phrase",
                            limit=10,
                        ),
                    )
                    report = runtime.doctor_report(connection, db_path)
                    self.assertEqual("PASS", report["result"])
                    self.assertEqual(2, report["memory_count"])
                    self.assertEqual(1, report["archive_count"])
                    self.assertEqual(3, report["total_memory_count"])
                    self.assertEqual(3, report["fts_count"])
                    self.assertEqual("ready", report["fts_status"])
                finally:
                    connection.close()

                status, _rendered, restored = self._capture(
                    lifecycle.cmd_restore, ["--id", "restore-me", "--json"]
                )
                self.assertEqual(0, status)
                self.assertEqual("memory_restored", restored["reason_code"])
                self.assertEqual("restored", restored["outcome"])
                self.assertEqual(1, restored["restored"])
                self.assertTrue(restored["changed"])

                connection = runtime.connect(db_path)
                try:
                    restored_timestamp = connection.execute(
                        "SELECT updated_at FROM memories WHERE id = 'restore-me'"
                    ).fetchone()[0]
                    self.assertEqual(
                        ["restore-me"],
                        [
                            record.memory_id
                            for record in runtime.find_memories(
                                connection,
                                query="restore unique phrase",
                                limit=10,
                            )
                        ],
                    )
                    connection.execute(
                        "DELETE FROM memory_fts WHERE id = 'fresh'"
                    )
                    connection.commit()
                    stale_report = runtime.doctor_report(connection, db_path)
                    self.assertEqual("WARN", stale_report["result"])
                    self.assertEqual("stale", stale_report["fts_status"])
                    self.assertIn(
                        "fts_record_count_mismatch", stale_report["warnings"]
                    )
                finally:
                    connection.close()

                memory = importlib.reload(importlib.import_module("memory_command"))
                status, _rendered, memory_doctor = self._capture(
                    memory.cmd_doctor, ["--json"]
                )
                self.assertEqual(0, status)
                self.assertEqual(3, memory_doctor["total_memory_count"])
                self.assertEqual(0, memory_doctor["archive_count"])
                self.assertEqual("stale", memory_doctor["fts_status"])

                status, _rendered, repeated = self._capture(
                    lifecycle.cmd_restore, ["--id", "restore-me", "--json"]
                )
                self.assertEqual(0, status)
                self.assertEqual("already_active", repeated["reason_code"])
                self.assertEqual(0, repeated["restored"])
                self.assertFalse(repeated["changed"])
                connection = sqlite3.connect(db_path)
                try:
                    self.assertEqual(
                        restored_timestamp,
                        connection.execute(
                            "SELECT updated_at FROM memories WHERE id = 'restore-me'"
                        ).fetchone()[0],
                    )
                finally:
                    connection.close()

                status, _rendered, missing = self._capture(
                    lifecycle.cmd_restore, ["--id", "missing", "--json"]
                )
                self.assertEqual(1, status)
                self.assertEqual("memory_not_found", missing["reason_code"])
                self.assertEqual("not_found", missing["outcome"])
                self.assertEqual("rolled_back", missing["transaction_outcome"])
                self.assertEqual("plan", missing["failure_phase"])
                self.assertFalse(missing["commit_attempted"])
                self.assertEqual(0, missing["restored"])

    def test_apply_failures_roll_back_without_partial_reporting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for failure in (
                "writer-lock",
                "plan",
                "mid-update",
                "compression-mid-update",
                "pre-commit",
            ):
                with self.subTest(failure=failure):
                    with self._bound_modules(
                        root, f"{failure}/memory.db"
                    ) as (runtime, lifecycle, db_path):
                        connection = runtime.connect(db_path)
                        try:
                            self._insert_memory(connection, "old-a")
                            self._insert_memory(connection, "old-b")
                            runtime._rebuild_fts(connection)
                            connection.commit()
                        finally:
                            connection.close()
                        baseline = self._logical_snapshot(db_path)

                        if failure == "writer-lock":
                            contender = runtime.connect(db_path)
                            contender.execute("PRAGMA busy_timeout=1")
                            holder = runtime.connect(db_path)
                            holder.execute("BEGIN IMMEDIATE")
                            try:
                                with patch.object(
                                    lifecycle, "connect", return_value=contender
                                ):
                                    status, _rendered, payload = self._capture(
                                        lifecycle.cmd_cleanup,
                                        ["--older-days", "1", "--json"],
                                    )
                            finally:
                                holder.rollback()
                                holder.close()
                        elif failure == "plan":
                            with patch.object(
                                lifecycle,
                                "_cleanup_candidates",
                                side_effect=RuntimeError("injected planner failure"),
                            ):
                                status, _rendered, payload = self._capture(
                                    lifecycle.cmd_cleanup,
                                    ["--older-days", "1", "--json"],
                                )
                        elif failure in {"mid-update", "compression-mid-update"}:
                            real_archive = lifecycle._archive_candidate_rows

                            def fail_after_first(conn, candidates, timestamp):
                                real_archive(conn, candidates[:1], timestamp)
                                raise RuntimeError("injected mid-update failure")

                            with patch.object(
                                lifecycle,
                                "_archive_candidate_rows",
                                side_effect=fail_after_first,
                            ):
                                status, _rendered, payload = self._capture(
                                    (
                                        lifecycle.cmd_compress
                                        if failure == "compression-mid-update"
                                        else lifecycle.cmd_cleanup
                                    ),
                                    (
                                        ["--json"]
                                        if failure == "compression-mid-update"
                                        else ["--older-days", "1", "--json"]
                                    ),
                                )
                        else:
                            failing = _CommitFailureConnection(
                                runtime.connect(db_path)
                            )
                            with patch.object(
                                lifecycle, "connect", return_value=failing
                            ):
                                status, _rendered, payload = self._capture(
                                    lifecycle.cmd_cleanup,
                                    ["--older-days", "1", "--json"],
                                )

                        self.assertEqual(1, status)
                        self.assertEqual("FAIL", payload["result"])
                        self.assertEqual(0, payload["changed_count"])
                        self.assertEqual(
                            0,
                            payload[
                                "removed"
                                if failure == "compression-mid-update"
                                else "moved"
                            ],
                        )
                        self.assertEqual([], payload["candidate_sample"])
                        self.assertEqual(
                            "not_started"
                            if failure == "writer-lock"
                            else "rolled_back",
                            payload["transaction_outcome"],
                        )
                        self.assertEqual(
                            failure == "pre-commit", payload["commit_attempted"]
                        )
                        self.assertEqual(baseline, self._logical_snapshot(db_path))

    def test_commit_ambiguity_never_claims_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for command in ("cleanup", "compress"):
                with self.subTest(command=command):
                    with self._bound_modules(
                        root, f"{command}/memory.db"
                    ) as (runtime, lifecycle, db_path):
                        connection = runtime.connect(db_path)
                        try:
                            self._insert_memory(connection, "old-a")
                            self._insert_memory(connection, "old-b")
                            connection.commit()
                        finally:
                            connection.close()
                        ambiguous = _CommitThenRaiseConnection(
                            runtime.connect(db_path)
                        )
                        with patch.object(
                            lifecycle, "connect", return_value=ambiguous
                        ):
                            status, _rendered, payload = self._capture(
                                (
                                    lifecycle.cmd_cleanup
                                    if command == "cleanup"
                                    else lifecycle.cmd_compress
                                ),
                                (
                                    ["--older-days", "1", "--json"]
                                    if command == "cleanup"
                                    else ["--json"]
                                ),
                            )

                        self.assertEqual(1, status)
                        self.assertEqual("unknown", payload["transaction_outcome"])
                        self.assertEqual("commit", payload["failure_phase"])
                        self.assertTrue(payload["commit_attempted"])
                        self.assertIsNone(payload["changed_count"])
                        self.assertIsNone(
                            payload["moved" if command == "cleanup" else "removed"]
                        )
                        self.assertEqual(
                            f"memory_{'cleanup' if command == 'cleanup' else 'compression'}_commit_outcome_unknown",
                            payload["reason_code"],
                        )
                        connection = sqlite3.connect(db_path)
                        try:
                            self.assertEqual(
                                2 if command == "cleanup" else 1,
                                connection.execute(
                                    "SELECT COUNT(*) FROM memories WHERE archived = 1"
                                ).fetchone()[0],
                            )
                        finally:
                            connection.close()

            with self._bound_modules(root, "close-failure/memory.db") as (
                runtime,
                lifecycle,
                db_path,
            ):
                connection = runtime.connect(db_path)
                try:
                    self._insert_memory(connection, "close-after-commit")
                    connection.commit()
                finally:
                    connection.close()
                close_failure = _CloseFailureConnection(runtime.connect(db_path))
                with patch.object(
                    lifecycle, "connect", return_value=close_failure
                ):
                    status, _rendered, payload = self._capture(
                        lifecycle.cmd_cleanup,
                        ["--older-days", "1", "--json"],
                    )
                self.assertEqual(0, status)
                self.assertEqual("PASS", payload["result"])
                self.assertEqual("committed", payload["transaction_outcome"])
                self.assertIn("close cleanup failed", payload["warnings"][0])
                connection = sqlite3.connect(db_path)
                try:
                    self.assertEqual(
                        1,
                        connection.execute(
                            "SELECT archived FROM memories WHERE id = ?",
                            ("close-after-commit",),
                        ).fetchone()[0],
                    )
                finally:
                    connection.close()

            for failure_class, expected_outcome, expected_archived in (
                (_CommitFailureConnection, "rolled_back", 1),
                (_CommitThenRaiseConnection, "unknown", 0),
            ):
                with self.subTest(restore=failure_class.__name__):
                    with self._bound_modules(
                        root, f"restore-{failure_class.__name__}/memory.db"
                    ) as (runtime, lifecycle, db_path):
                        connection = runtime.connect(db_path)
                        try:
                            self._insert_memory(
                                connection, "restore-ambiguous", archived=True
                            )
                            connection.commit()
                        finally:
                            connection.close()
                        failing = failure_class(runtime.connect(db_path))
                        with patch.object(
                            lifecycle, "connect", return_value=failing
                        ):
                            status, _rendered, payload = self._capture(
                                lifecycle.cmd_restore,
                                ["--id", "restore-ambiguous", "--json"],
                            )
                        self.assertEqual(1, status)
                        self.assertEqual(
                            expected_outcome, payload["transaction_outcome"]
                        )
                        if expected_outcome == "unknown":
                            self.assertIsNone(payload["restored"])
                            self.assertIsNone(payload["changed"])
                        else:
                            self.assertEqual(0, payload["restored"])
                            self.assertFalse(payload["changed"])
                        connection = sqlite3.connect(db_path)
                        try:
                            self.assertEqual(
                                expected_archived,
                                connection.execute(
                                    "SELECT archived FROM memories WHERE id = ?",
                                    ("restore-ambiguous",),
                                ).fetchone()[0],
                            )
                        finally:
                            connection.close()

    def test_unsafe_sidecar_states_fail_without_preview_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for state in ("missing-shm", "malformed-pair", "nonregular", "journal"):
                with self.subTest(state=state):
                    with self._bound_modules(
                        root, f"{state}/memory.db"
                    ) as (_runtime, lifecycle, db_path):
                        connection = lifecycle.connect()
                        connection.close()
                        wal_path = Path(f"{db_path}-wal")
                        shm_path = Path(f"{db_path}-shm")
                        if state == "missing-shm":
                            wal_path.write_bytes(b"not-a-complete-wal")
                        elif state == "malformed-pair":
                            wal_path.write_bytes(b"not-a-complete-wal")
                            shm_path.write_bytes(b"not-a-complete-shm")
                        elif state == "nonregular":
                            wal_path.mkdir()
                            shm_path.write_bytes(b"not-a-complete-shm")
                        else:
                            Path(f"{db_path}-journal").write_bytes(b"active")
                        before = self._filesystem_snapshot(db_path.parent)
                        status, _rendered, payload = self._capture(
                            lifecycle.cmd_cleanup,
                            ["--older-days", "1", "--dry-run", "--json"],
                        )
                        after = self._filesystem_snapshot(db_path.parent)
                        self.assertEqual(1, status)
                        self.assertEqual(
                            "shared_memory_preview_unavailable",
                            payload["reason_code"],
                        )
                        self.assertEqual("not_started", payload["transaction_outcome"])
                        self.assertEqual(before, after)

    @unittest.skipUnless(
        sys.platform.startswith("darwin") or sys.platform.startswith("linux"),
        "readonly_shm requires the Unix VFS",
    )
    def test_valid_wal_missing_shm_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self._bound_modules(root) as (runtime, lifecycle, db_path):
                connection = runtime.connect(db_path)
                connection.close()
                context = multiprocessing.get_context("spawn")
                ready = context.Event()
                release = context.Event()
                writer = context.Process(
                    target=_hold_committed_wal_row,
                    args=(str(db_path), ready, release),
                )
                writer.start()
                try:
                    self.assertTrue(ready.wait(timeout=15))
                    wal_path = Path(f"{db_path}-wal")
                    shm_path = Path(f"{db_path}-shm")
                    self.assertGreaterEqual(wal_path.stat().st_size, 32)
                    self.assertIn(
                        wal_path.read_bytes()[:4],
                        (b"7\x7f\x06\x82", b"7\x7f\x06\x83"),
                    )
                    shm_path.unlink()
                    before = self._filesystem_snapshot(db_path.parent)
                    status, _rendered, payload = self._capture(
                        lifecycle.cmd_cleanup,
                        ["--older-days", "1", "--dry-run", "--json"],
                    )
                    after = self._filesystem_snapshot(db_path.parent)
                    self.assertEqual(1, status)
                    self.assertEqual(
                        "shared_memory_preview_unavailable", payload["reason_code"]
                    )
                    self.assertEqual(before, after)
                    self.assertFalse(shm_path.exists())
                finally:
                    release.set()
                    writer.join(timeout=15)
                    if writer.is_alive():
                        writer.terminate()
                        writer.join(timeout=5)
                self.assertEqual(0, writer.exitcode)

    @unittest.skipUnless(
        sys.platform.startswith("darwin") or sys.platform.startswith("linux"),
        "readonly_shm requires the Unix VFS",
    )
    def test_corrupt_committed_and_partial_wal_frames_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for corruption in ("committed-frame", "partial-frame"):
                with self.subTest(corruption=corruption):
                    with self._bound_modules(
                        root, f"{corruption}/memory.db"
                    ) as (runtime, lifecycle, db_path):
                        connection = runtime.connect(db_path)
                        connection.close()
                        context = multiprocessing.get_context("spawn")
                        ready = context.Event()
                        release = context.Event()
                        writer = context.Process(
                            target=_hold_committed_wal_row,
                            args=(str(db_path), ready, release),
                        )
                        writer.start()
                        try:
                            self.assertTrue(ready.wait(timeout=15))
                            wal_path = Path(f"{db_path}-wal")
                            shm_path = Path(f"{db_path}-shm")
                            original = wal_path.read_bytes()
                            damaged = bytearray(original)
                            page_size = int.from_bytes(damaged[8:12], "big")
                            if page_size == 1:
                                page_size = 65536
                            max_frame = int.from_bytes(
                                shm_path.read_bytes()[16:20], sys.byteorder
                            )
                            self.assertGreater(max_frame, 0)
                            if corruption == "committed-frame":
                                page_offset = (
                                    32
                                    + (max_frame - 1) * (page_size + 24)
                                    + 24
                                )
                                damaged[page_offset] ^= 0x01
                            else:
                                damaged = damaged[:-1]
                            wal_path.write_bytes(damaged)
                            before = self._filesystem_snapshot(db_path.parent)
                            with self.assertRaises(RuntimeError):
                                runtime._validate_active_wal_headers(
                                    wal_path,
                                    shm_path,
                                    wal_path.stat(),
                                    shm_path.stat(),
                                )
                            status, _rendered, payload = self._capture(
                                lifecycle.cmd_cleanup,
                                ["--older-days", "1", "--dry-run", "--json"],
                            )
                            after = self._filesystem_snapshot(db_path.parent)
                            self.assertEqual(1, status)
                            self.assertEqual(
                                "shared_memory_preview_unavailable",
                                payload["reason_code"],
                            )
                            self.assertEqual(before, after)
                            wal_path.write_bytes(original)
                        finally:
                            release.set()
                            writer.join(timeout=15)
                            if writer.is_alive():
                                writer.terminate()
                                writer.join(timeout=5)

    @unittest.skipUnless(
        sys.platform.startswith("darwin") or sys.platform.startswith("linux"),
        "readonly_shm requires the Unix VFS",
    )
    def test_canonical_alias_uses_target_wal_and_rejects_unsafe_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self._bound_modules(root, "alias.db") as (
                runtime,
                lifecycle,
                alias_path,
            ):
                real_path = root / "real.db"
                connection = runtime.connect(real_path)
                connection.close()
                alias_path.symlink_to(real_path.name)

                context = multiprocessing.get_context("spawn")
                ready = context.Event()
                release = context.Event()
                writer = context.Process(
                    target=_hold_committed_wal_row,
                    args=(str(real_path), ready, release),
                )
                writer.start()
                try:
                    self.assertTrue(ready.wait(timeout=15))
                    before = self._filesystem_snapshot(root)
                    status, _rendered, payload = self._capture(
                        lifecycle.cmd_cleanup,
                        ["--older-days", "1", "--dry-run", "--json"],
                    )
                    after = self._filesystem_snapshot(root)
                    self.assertEqual(0, status)
                    self.assertEqual("wal-only", payload["candidate_sample"][0]["id"])
                    self.assertEqual(before, after)
                    self.assertFalse(Path(f"{alias_path}-wal").exists())
                    self.assertFalse(Path(f"{alias_path}-shm").exists())
                finally:
                    release.set()
                    writer.join(timeout=15)
                    if writer.is_alive():
                        writer.terminate()
                        writer.join(timeout=5)
                self.assertEqual(0, writer.exitcode)

            for alias_kind in ("hardlink", "dangling-symlink"):
                with self.subTest(alias_kind=alias_kind):
                    with self._bound_modules(
                        root, f"{alias_kind}/alias.db"
                    ) as (runtime, lifecycle, alias_path):
                        alias_path.parent.mkdir(parents=True, exist_ok=True)
                        if alias_kind == "hardlink":
                            real_path = alias_path.parent / "real.db"
                            connection = runtime.connect(real_path)
                            connection.close()
                            os.link(real_path, alias_path)
                        else:
                            alias_path.symlink_to("missing.db")
                        status, _rendered, payload = self._capture(
                            lifecycle.cmd_cleanup,
                            ["--older-days", "1", "--dry-run", "--json"],
                        )
                        self.assertEqual(1, status)
                        self.assertEqual(
                            "shared_memory_preview_unavailable",
                            payload["reason_code"],
                        )

    @unittest.skipUnless(
        sys.platform.startswith("darwin") or sys.platform.startswith("linux"),
        "POSIX locks require a Unix host",
    )
    def test_checkpointed_snapshot_lock_blocks_writer_interleaving(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self._bound_modules(root) as (runtime, lifecycle, db_path):
                connection = runtime.connect(db_path)
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                connection.execute("PRAGMA journal_mode=DELETE")
                connection.close()
                self.assertFalse(Path(f"{db_path}-wal").exists())
                self.assertFalse(Path(f"{db_path}-shm").exists())

                real_reader = runtime._read_fd_bytes
                attempts: list[subprocess.CompletedProcess[str]] = []

                def read_while_writer_contends(descriptor: int, size: int) -> bytes:
                    script = (
                        "import sqlite3, sys\n"
                        "connection = sqlite3.connect(sys.argv[1], timeout=0.1)\n"
                        "try:\n"
                        "    connection.execute(\"INSERT INTO meta(key, value) VALUES('race_probe', '1')\")\n"
                        "    connection.commit()\n"
                        "except Exception as exc:\n"
                        "    print(exc, file=sys.stderr)\n"
                        "    raise SystemExit(3)\n"
                        "finally:\n"
                        "    connection.close()\n"
                    )
                    attempts.append(
                        subprocess.run(
                            [sys.executable, "-c", script, str(db_path)],
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=5,
                        )
                    )
                    return real_reader(descriptor, size)

                with patch.object(
                    runtime,
                    "_read_fd_bytes",
                    side_effect=read_while_writer_contends,
                ):
                    status, _rendered, payload = self._capture(
                        lifecycle.cmd_cleanup,
                        ["--older-days", "1", "--dry-run", "--json"],
                    )
                self.assertEqual(0, status)
                self.assertEqual("PASS", payload["result"])
                self.assertEqual(1, len(attempts))
                self.assertEqual(3, attempts[0].returncode)
                self.assertIn("locked", attempts[0].stderr.lower())
                connection = sqlite3.connect(db_path)
                try:
                    self.assertIsNone(
                        connection.execute(
                            "SELECT value FROM meta WHERE key = 'race_probe'"
                        ).fetchone()
                    )
                finally:
                    connection.close()

    @unittest.skipUnless(
        sys.platform.startswith("darwin") or sys.platform.startswith("linux"),
        "readonly_shm requires the Unix VFS",
    )
    def test_mismatched_wal_shm_pair_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self._bound_modules(root, "first.db") as (
                runtime,
                lifecycle,
                first_path,
            ):
                second_path = root / "second.db"
                for path in (first_path, second_path):
                    connection = runtime.connect(path)
                    connection.close()
                context = multiprocessing.get_context("spawn")
                first_ready, second_ready = context.Event(), context.Event()
                first_release, second_release = context.Event(), context.Event()
                first_writer = context.Process(
                    target=_hold_committed_wal_row,
                    args=(str(first_path), first_ready, first_release),
                )
                second_writer = context.Process(
                    target=_hold_committed_wal_row,
                    args=(str(second_path), second_ready, second_release),
                )
                first_writer.start()
                second_writer.start()
                try:
                    self.assertTrue(first_ready.wait(timeout=15))
                    self.assertTrue(second_ready.wait(timeout=15))
                    shutil.copyfile(
                        Path(f"{second_path}-shm"), Path(f"{first_path}-shm")
                    )
                    before = self._filesystem_snapshot(root)
                    status, _rendered, payload = self._capture(
                        lifecycle.cmd_cleanup,
                        ["--older-days", "1", "--dry-run", "--json"],
                    )
                    after = self._filesystem_snapshot(root)
                    self.assertEqual(1, status)
                    self.assertEqual(
                        "shared_memory_preview_unavailable", payload["reason_code"]
                    )
                    self.assertEqual(before, after)
                finally:
                    first_release.set()
                    second_release.set()
                    for writer in (first_writer, second_writer):
                        writer.join(timeout=15)
                        if writer.is_alive():
                            writer.terminate()
                            writer.join(timeout=5)

    def test_gateway_compress_alias_remains_applying(self) -> None:
        gateway = importlib.reload(importlib.import_module("gateway_command"))
        completed = SimpleNamespace(returncode=0)
        with patch.object(
            gateway.subprocess, "run", return_value=completed
        ) as run:
            status = gateway.command_concise(True, ["compress"])
        self.assertEqual(0, status)
        command = run.call_args.args[0]
        self.assertEqual("compress", command[-2])
        self.assertEqual("--json", command[-1])
        self.assertNotIn("--dry-run", command)

    @unittest.skipUnless(
        sys.platform.startswith("darwin") or sys.platform.startswith("linux"),
        "readonly_shm requires the Unix VFS",
    )
    def test_wal_only_row_is_visible_without_artifact_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self._bound_modules(root) as (runtime, lifecycle, db_path):
                connection = runtime.connect(db_path)
                connection.close()

                context = multiprocessing.get_context("spawn")
                ready = context.Event()
                release = context.Event()
                writer = context.Process(
                    target=_hold_committed_wal_row,
                    args=(str(db_path), ready, release),
                )
                writer.start()
                try:
                    self.assertTrue(ready.wait(timeout=15))
                    self.assertTrue(Path(f"{db_path}-wal").exists())
                    self.assertTrue(Path(f"{db_path}-shm").exists())
                    immutable = sqlite3.connect(
                        f"{db_path.resolve().as_uri()}?mode=ro&immutable=1",
                        uri=True,
                    )
                    try:
                        self.assertEqual(
                            0,
                            immutable.execute(
                                "SELECT COUNT(*) FROM memories"
                            ).fetchone()[0],
                        )
                    finally:
                        immutable.close()

                    before = self._filesystem_snapshot(db_path.parent)
                    with patch.object(
                        lifecycle,
                        "connect",
                        side_effect=AssertionError("dry-run reached writable connect"),
                    ):
                        status, _rendered, payload = self._capture(
                            lifecycle.cmd_cleanup,
                            ["--older-days", "1", "--dry-run", "--json"],
                        )
                    after = self._filesystem_snapshot(db_path.parent)
                    self.assertEqual(0, status)
                    self.assertEqual(1, payload["candidate_count"])
                    self.assertEqual("wal-only", payload["candidate_sample"][0]["id"])
                    self.assertEqual(before, after)
                finally:
                    release.set()
                    writer.join(timeout=15)
                    if writer.is_alive():
                        writer.terminate()
                        writer.join(timeout=5)
                self.assertEqual(0, writer.exitcode)


if __name__ == "__main__":
    unittest.main()
