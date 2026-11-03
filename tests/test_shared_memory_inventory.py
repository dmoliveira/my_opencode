from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import memory_lifecycle_command as lifecycle
import shared_memory_inventory as inventory
import shared_memory_runtime as runtime
import sqlite_doctor_command as doctor

CANARY = "SECRET-CONTENT-PRIVATE-CANARY"
CUTOFF = "2024-01-01T00:00:00Z"


@unittest.skipUnless(
    sys.platform.startswith(("darwin", "linux")), "owner preview requires Unix"
)
class SharedMemoryInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="memory-inventory-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.db = self.root / "private-store.db"
        self.conn = runtime.connect(self.db)
        self.addCleanup(self.conn.close)

    def insert(
        self,
        memory_id: str,
        *,
        scope="repo",
        namespace="private-namespace",
        pinned=0,
        archived=0,
        updated="2000-01-01T00:00:00Z",
        content=CANARY,
    ):
        self.conn.execute(
            """INSERT INTO memories
               (id, kind, scope, namespace, title, content, summary, tags_json,
                tags_text, links_json, source_type, source_ref, session_id, cwd,
                pinned, archived, confidence, created_at, updated_at)
               VALUES (?, 'note', ?, ?, ?, ?, ?, '[]', '', '[]', NULL, NULL,
                       ?, ?, ?, ?, 60, '2000-01-01T00:00:00Z', ?)""",
            (
                memory_id,
                scope,
                namespace,
                CANARY,
                content,
                CANARY,
                CANARY,
                CANARY,
                pinned,
                archived,
                updated,
            ),
        )
        self.conn.commit()

    def argv(
        self, *, db=None, scope="repo", namespace="private-namespace", cutoff=CUTOFF
    ):
        return [
            "--db-path",
            str(db or self.db),
            "--scope",
            scope,
            "--namespace",
            namespace,
            "--cutoff",
            cutoff,
        ]

    def snapshot(self):
        result = {}
        for path in sorted(self.root.iterdir()):
            info = path.lstat()
            item = (
                stat.S_IMODE(info.st_mode),
                info.st_ino,
                info.st_nlink,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
            )
            if path.is_file():
                item += (hashlib.sha256(path.read_bytes()).hexdigest(),)
            result[path.name] = item
        return result

    def run_cli(self, argv, *, via_lifecycle=False):
        env = {
            "HOME": str(self.root),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "MY_OPENCODE_SHARED_MEMORY_PATH": str(self.root / "never-open-default.db"),
        }
        script = (
            "data_lifecycle_command.py"
            if via_lifecycle
            else "shared_memory_inventory.py"
        )
        command = [sys.executable, "-B", str(ROOT / "scripts" / script)]
        if via_lifecycle:
            command.append("inventory-shared-memory")
        return subprocess.run(
            [*command, *argv],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )

    def test_snapshot_matches_owner_predicate_and_preserves_all_source_bytes(self):
        self.insert("secret-id-b")
        self.insert("secret-id-a", updated="2000-01-01T01:00:00+01:00")
        self.insert("created-fallback", updated="")
        self.insert("equal-cutoff", updated=CUTOFF)
        self.insert("pinned", pinned=1)
        self.insert("archived", archived=1)
        self.insert("recent", updated="2025-01-01T00:00:00Z")
        self.insert("other-scope", scope="shared")
        self.insert("other-namespace", namespace="other")
        before = self.snapshot()
        process = self.run_cli(self.argv())
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual("", process.stderr)
        report = json.loads(process.stdout)
        self.assertEqual(3, report["candidate_count"])
        self.assertTrue(report["source_inspected"])
        for key in (
            "apply_supported",
            "source_mutation_supported",
            "source_identity_bound",
            "authorization_verified",
            "quiescence_verified",
            "recovery_verified",
            "cross_store_inventory_complete",
        ):
            self.assertIs(report[key], False)
        self.assertEqual("local-sensitive", report["sensitivity"])
        self.assertNotIn(CANARY, process.stdout + process.stderr)
        self.assertNotIn("secret-id", process.stdout + process.stderr)
        self.assertNotIn("private-namespace", process.stdout + process.stderr)
        self.assertNotIn(str(self.root), process.stdout + process.stderr)
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.root / "never-open-default.db").exists())
        wrapper = self.run_cli(self.argv(), via_lifecycle=True)
        self.assertEqual(0, wrapper.returncode, wrapper.stderr)
        self.assertEqual(report, json.loads(wrapper.stdout))
        self.assertEqual(before, self.snapshot())
        readonly = runtime.connect_readonly(self.db)
        try:
            count, _ = lifecycle._cleanup_candidates(
                readonly,
                cutoff=CUTOFF,
                scope="repo",
                namespace="private-namespace",
                all_rows=True,
            )
        finally:
            readonly.close()
        self.assertEqual(count, report["candidate_count"])

    def test_inventory_cannot_reach_writable_owner_connection_or_initializer(self):
        self.insert("one")
        self.conn.close()
        before = self.snapshot()
        with (
            patch.object(
                runtime, "connect", side_effect=AssertionError("writable connect")
            ),
            patch.object(
                runtime, "initialize", side_effect=AssertionError("initializer")
            ),
        ):
            report = inventory._inventory(inventory._arguments(self.argv()))
        self.assertEqual(1, report["candidate_count"])
        after = self.snapshot()
        for name in before:
            self.assertEqual(before[name], after[name], name)

    def test_unenforced_sqlite_row_limit_fails_closed(self):
        fake = MagicMock()
        fake.getlimit.return_value = inventory.MAX_ROW_BYTES + 1
        with (
            patch.object(runtime, "connect_readonly", return_value=fake),
            self.assertRaises(inventory.InventoryError) as failure,
        ):
            inventory._inventory(inventory._arguments(self.argv()))
        self.assertEqual(
            "shared_memory_inventory_worker_unavailable", failure.exception.code
        )
        fake.close.assert_called_once()

    def test_fingerprint_tracks_entire_selected_row_even_without_timestamp_change(self):
        self.insert("selected")
        self.insert("excluded", pinned=1)
        args = inventory._arguments(self.argv())
        original = inventory._inventory(args)
        self.assertEqual(original, inventory._inventory(args))
        self.conn.execute(
            "UPDATE memories SET content = ? WHERE id = 'selected'", ("changed",)
        )
        self.conn.commit()
        changed = inventory._inventory(args)
        self.assertNotEqual(
            original["candidate_snapshot_sha256"], changed["candidate_snapshot_sha256"]
        )
        self.conn.execute(
            "UPDATE memories SET content = ? WHERE id = 'excluded'", ("ignored",)
        )
        self.conn.commit()
        self.assertEqual(changed, inventory._inventory(args))
        self.insert("selected-2")
        added = inventory._inventory(args)
        self.assertEqual(2, added["candidate_count"])
        self.assertNotEqual(
            changed["candidate_snapshot_sha256"], added["candidate_snapshot_sha256"]
        )
        self.conn.execute("UPDATE memories SET pinned = 1 WHERE id = 'selected-2'")
        self.conn.commit()
        self.assertEqual(changed, inventory._inventory(args))

    def test_wal_snapshot_is_pinned_before_owner_validates_wal(self):
        self.insert("before-validation")
        original_validate = runtime._validate_active_wal_headers

        def validate_then_commit(*args, **kwargs):
            original_validate(*args, **kwargs)
            self.insert("after-validation")

        with patch.object(
            runtime, "_validate_active_wal_headers", side_effect=validate_then_commit
        ):
            report = inventory._inventory(inventory._arguments(self.argv()))
        self.assertEqual(1, report["candidate_count"])
        self.assertEqual(
            2,
            inventory._inventory(inventory._arguments(self.argv()))["candidate_count"],
        )

    def test_fingerprint_binds_exact_selector_and_frozen_cutoff(self):
        self.insert("selected")
        first = inventory._inventory(inventory._arguments(self.argv()))
        changed_cutoff = inventory._inventory(
            inventory._arguments(self.argv(cutoff="2023-01-01T00:00:00Z"))
        )
        self.assertEqual(first["candidate_count"], changed_cutoff["candidate_count"])
        self.assertNotEqual(
            first["candidate_snapshot_sha256"],
            changed_cutoff["candidate_snapshot_sha256"],
        )
        first_empty = inventory._inventory(
            inventory._arguments(self.argv(namespace="empty-a"))
        )
        second_empty = inventory._inventory(
            inventory._arguments(self.argv(namespace="empty-b"))
        )
        self.assertEqual(0, first_empty["candidate_count"])
        self.assertEqual(0, second_empty["candidate_count"])
        self.assertNotEqual(
            first_empty["candidate_snapshot_sha256"],
            second_empty["candidate_snapshot_sha256"],
        )

    def test_fingerprint_is_order_independent_and_does_not_bind_database_identity(self):
        self.insert("b")
        self.insert("a")
        first = inventory._inventory(inventory._arguments(self.argv()))
        second_path = self.root / "other-store.db"
        other = runtime.connect(second_path)
        original = self.conn
        try:
            self.conn = other
            self.insert("a")
            self.insert("b")
            second = inventory._inventory(
                inventory._arguments(self.argv(db=second_path))
            )
        finally:
            self.conn = original
            other.close()
        self.assertEqual(
            first["candidate_snapshot_sha256"], second["candidate_snapshot_sha256"]
        )
        self.assertFalse(first["source_identity_bound"])
        self.assertFalse(second["source_identity_bound"])

    def test_missing_or_invalid_source_fails_without_creating_or_echoing_files(self):
        missing = self.root / "PRIVATE-NOT-CREATED.db"
        before = self.snapshot()
        process = self.run_cli(self.argv(db=missing))
        self.assertEqual(1, process.returncode)
        self.assertEqual("", process.stderr)
        self.assertEqual("FAIL", json.loads(process.stdout)["result"])
        self.assertNotIn("PRIVATE-NOT-CREATED", process.stdout)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(missing.exists())
        malformed = self.root / "malformed.db"
        malformed.write_bytes(b"not sqlite " + CANARY.encode())
        before = self.snapshot()
        process = self.run_cli(self.argv(db=malformed))
        self.assertEqual(1, process.returncode)
        self.assertEqual("FAIL", json.loads(process.stdout)["result"])
        self.assertNotIn(CANARY, process.stdout + process.stderr)
        self.assertEqual(before, self.snapshot())

    def test_checkpointed_source_inventory_leaves_no_sidecars_or_other_files(self):
        self.insert("checkpointed")
        self.conn.close()
        self.assertFalse(Path(str(self.db) + "-wal").exists())
        self.assertFalse(Path(str(self.db) + "-shm").exists())
        before = self.snapshot()
        process = self.run_cli(self.argv(), via_lifecycle=True)
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual(1, json.loads(process.stdout)["candidate_count"])
        self.assertEqual("", process.stderr)
        self.assertEqual(before, self.snapshot())

    def test_malformed_wal_sidecars_fail_without_changing_sources(self):
        self.insert("checkpointed")
        self.conn.close()
        wal = Path(str(self.db) + "-wal")
        shm = Path(str(self.db) + "-shm")
        wal.write_bytes(b"invalid-wal-" + CANARY.encode())
        shm.write_bytes(b"invalid-shm-" + CANARY.encode())
        before = self.snapshot()
        process = self.run_cli(self.argv(), via_lifecycle=True)
        self.assertEqual(1, process.returncode)
        self.assertEqual("FAIL", json.loads(process.stdout)["result"])
        self.assertNotIn(CANARY, process.stdout + process.stderr)
        self.assertEqual(before, self.snapshot())

    def test_invalid_or_duplicate_arguments_fail_before_worker_and_do_not_echo(self):
        bad_values = [
            self.argv(scope="project"),
            self.argv(namespace=" bad "),
            self.argv(namespace="-bad"),
            self.argv(namespace="private\nsecret"),
            self.argv(cutoff="2024-02-30T00:00:00Z"),
            self.argv(cutoff="2024-01-01"),
            self.argv(db="relative.db"),
            self.argv(db="/private/../elsewhere.db"),
            self.argv() + ["--scope", "shared"],
            self.argv() + ["--unknown", CANARY],
            self.argv()[:-1],
        ]
        for bad in bad_values:
            with (
                self.subTest(bad=bad),
                patch.object(doctor, "_run_bounded_command") as worker,
                redirect_stdout(io.StringIO()) as output,
            ):
                code = inventory.main(bad)
                self.assertEqual(1, code)
                self.assertEqual(
                    "shared_memory_inventory_invalid_arguments",
                    json.loads(output.getvalue())["reason_code"],
                )
                self.assertNotIn(CANARY, output.getvalue())
                worker.assert_not_called()

    def test_all_limits_and_malformed_dynamic_row_types_fail_closed(self):
        self.insert("one")
        self.insert("two")
        args = inventory._arguments(self.argv())
        with (
            patch.object(inventory, "MAX_CANDIDATES", 1),
            self.assertRaises(inventory.InventoryError) as failure,
        ):
            inventory._inventory(args)
        self.assertEqual(
            "shared_memory_inventory_limits_exceeded", failure.exception.code
        )
        with (
            patch.object(inventory, "MAX_SERIALIZED_BYTES", 10),
            self.assertRaises(inventory.InventoryError) as failure,
        ):
            inventory._inventory(args)
        self.assertEqual(
            "shared_memory_inventory_limits_exceeded", failure.exception.code
        )
        for limit in ("MAX_COLUMNS", "MAX_COLUMN_NAME_CHARS"):
            with (
                patch.object(inventory, limit, 1),
                self.assertRaises(inventory.InventoryError) as failure,
            ):
                inventory._inventory(args)
            self.assertEqual(
                "shared_memory_inventory_limits_exceeded", failure.exception.code
            )
        self.conn.execute("UPDATE memories SET confidence=60.5 WHERE id='one'")
        self.conn.commit()
        with self.assertRaises(inventory.InventoryError) as failure:
            inventory._inventory(args)
        self.assertEqual("shared_memory_inventory_unavailable", failure.exception.code)
        self.conn.execute(
            "UPDATE memories SET confidence=60, content=? WHERE id='one'",
            ("x" * (inventory.MAX_ROW_BYTES + 1),),
        )
        self.conn.commit()
        process = self.run_cli(self.argv())
        self.assertEqual(1, process.returncode)
        self.assertEqual(
            "shared_memory_inventory_limits_exceeded",
            json.loads(process.stdout)["reason_code"],
        )

    def test_candidate_with_null_identifier_fails_closed(self):
        self.insert("one")
        self.conn.execute("UPDATE memories SET id=NULL WHERE id='one'")
        self.conn.commit()
        process = self.run_cli(self.argv())
        self.assertEqual(1, process.returncode)
        self.assertEqual(
            "shared_memory_inventory_unavailable",
            json.loads(process.stdout)["reason_code"],
        )
        self.assertNotIn(CANARY, process.stdout + process.stderr)

    def test_worker_failures_never_echo_untrusted_output_or_stderr(self):
        outputs = [
            {
                "kind": "timeout",
                "exit_code": None,
                "stdout": CANARY.encode(),
                "stderr": CANARY.encode(),
            },
            {
                "kind": "completed",
                "exit_code": 1,
                "stdout": json.dumps(
                    {"result": "FAIL", "reason_code": CANARY}
                ).encode(),
                "stderr": CANARY.encode(),
            },
            {
                "kind": "completed",
                "exit_code": 0,
                "stdout": json.dumps({"result": "PASS", "secret": CANARY}).encode(),
                "stderr": CANARY.encode(),
            },
            {
                "kind": "completed",
                "exit_code": 0,
                "stdout": b"not-json",
                "stderr": CANARY.encode(),
            },
        ]
        for raw in outputs:
            with (
                self.subTest(kind=raw["kind"]),
                patch.object(doctor, "_run_bounded_command", return_value=raw),
                redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(1, inventory.main(self.argv()))
                self.assertEqual("FAIL", json.loads(output.getvalue())["result"])
                self.assertNotIn(CANARY, output.getvalue())

    def test_worker_memory_limit_failure_is_not_ignored(self):
        with (
            patch.object(inventory, "__name__", "__main__"),
            patch.object(
                inventory,
                "_enforce_memory_limit",
                side_effect=inventory.InventoryError(
                    "shared_memory_inventory_worker_unavailable"
                ),
            ),
            patch.object(inventory, "_inventory") as run,
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(1, inventory.main(["--internal-worker", *self.argv()]))
            run.assert_not_called()
        self.assertEqual(
            "shared_memory_inventory_worker_unavailable",
            json.loads(output.getvalue())["reason_code"],
        )

    def test_imported_entrypoint_rejects_internal_worker_bypass(self):
        with (
            patch.object(inventory, "_inventory") as run,
            patch.object(inventory, "_enforce_memory_limit") as limit,
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(1, inventory.main(["--internal-worker", *self.argv()]))
        run.assert_not_called()
        limit.assert_not_called()
        self.assertEqual(
            "shared_memory_inventory_invalid_arguments",
            json.loads(output.getvalue())["reason_code"],
        )

    def test_darwin_fallback_still_requires_sqlite_hard_heap_limit(self):
        import resource

        connection = MagicMock()
        connection.execute.return_value.fetchone.return_value = (
            inventory.MAX_SQLITE_HEAP_BYTES,
        )
        with (
            patch.object(inventory.sys, "platform", "darwin"),
            patch.object(
                resource,
                "getrlimit",
                return_value=(resource.RLIM_INFINITY, resource.RLIM_INFINITY),
            ),
            patch.object(resource, "setrlimit", side_effect=ValueError("unsupported")),
            patch.object(inventory.sqlite3, "connect", return_value=connection),
        ):
            inventory._enforce_memory_limit()
            connection.execute.return_value.fetchone.return_value = None
            with self.assertRaises(inventory.InventoryError) as failure:
                inventory._enforce_memory_limit()
        self.assertEqual(
            "shared_memory_inventory_worker_unavailable", failure.exception.code
        )

    def test_linux_address_space_limit_failure_is_not_ignored(self):
        import resource

        with (
            patch.object(inventory.sys, "platform", "linux"),
            patch.object(
                resource,
                "getrlimit",
                return_value=(resource.RLIM_INFINITY, resource.RLIM_INFINITY),
            ),
            patch.object(resource, "setrlimit", side_effect=ValueError("unsupported")),
            patch.object(inventory.sqlite3, "connect") as connect,
            self.assertRaises(inventory.InventoryError) as failure,
        ):
            inventory._enforce_memory_limit()
        connect.assert_not_called()
        self.assertEqual(
            "shared_memory_inventory_worker_unavailable", failure.exception.code
        )

    def test_source_size_limit_is_checked_at_locked_descriptor_before_copy(self):
        self.insert("one")
        self.conn.close()
        details = self.db.stat()
        with patch.object(runtime, "_read_fd_bytes") as read:
            with self.assertRaisesRegex(RuntimeError, "exceeds preview size limit"):
                runtime._checkpointed_database_image(
                    self.db, details, max_source_bytes=1
                )
            read.assert_not_called()
        for limit in (0, -1, True, 1.5):
            with patch.object(runtime, "_canonical_preview_path") as resolve:
                with self.assertRaises(ValueError):
                    runtime.connect_readonly(self.db, max_source_bytes=limit)
                resolve.assert_not_called()

    def test_wal_size_is_checked_before_scanning_committed_frames(self):
        self.insert("one")
        wal = Path(str(self.db) + "-wal")
        shm = Path(str(self.db) + "-shm")
        self.assertTrue(wal.is_file())
        self.assertTrue(shm.is_file())
        with patch.object(runtime, "_validate_committed_wal_frames") as validate:
            with self.assertRaisesRegex(RuntimeError, "exceeds preview size limit"):
                runtime._validate_active_wal_headers(
                    wal, shm, wal.stat(), shm.stat(), max_source_bytes=1
                )
            validate.assert_not_called()

    def test_hardlinked_database_is_refused_without_source_changes(self):
        self.insert("one")
        alias = self.root / "hardlinked.db"
        os.link(self.db, alias)
        before = self.snapshot()
        process = self.run_cli(self.argv())
        self.assertEqual(1, process.returncode)
        self.assertEqual("FAIL", json.loads(process.stdout)["result"])
        self.assertEqual(before, self.snapshot())

    def test_parent_rejects_forged_or_contradictory_worker_results(self):
        self.insert("one")
        args = inventory._arguments(self.argv())
        valid = inventory._inventory(args)
        self.assertTrue(inventory._valid_report(valid, args))
        for change in (
            {"authorization_verified": True},
            {"apply_supported": 0},
            {"source_identity_bound": True},
            {"candidate_count": True},
            {"candidate_count": inventory.MAX_CANDIDATES + 1},
            {"candidate_snapshot_sha256": CANARY},
            {"secret": CANARY},
        ):
            self.assertFalse(inventory._valid_report({**valid, **change}, args))

    def test_no_apply_or_source_mutation_option_exists(self):
        self.insert("one")
        before = self.snapshot()
        for extra in ("--apply", "--delete", "--redact", "--write", "--export"):
            process = self.run_cli([*self.argv(), extra])
            self.assertEqual(1, process.returncode)
            self.assertEqual(
                "shared_memory_inventory_invalid_arguments",
                json.loads(process.stdout)["reason_code"],
            )
            self.assertEqual("", process.stderr)
            self.assertEqual(before, self.snapshot())


if __name__ == "__main__":
    unittest.main()
