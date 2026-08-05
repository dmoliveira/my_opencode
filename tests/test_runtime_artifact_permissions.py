from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


class RuntimeArtifactPermissionsTest(unittest.TestCase):
    def _module(self):
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        return importlib.reload(importlib.import_module("session_command"))

    def _run_json(self, callback, arguments: list[str]) -> tuple[int, dict]:
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = callback(arguments)
        return code, json.loads(output.getvalue())

    def _create_wal_database(self, path: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        self.assertEqual(
            "wal", connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        )
        connection.execute("CREATE TABLE IF NOT EXISTS canary (value TEXT NOT NULL)")
        connection.execute("INSERT INTO canary (value) VALUES ('before')")
        connection.commit()
        self.assertTrue(Path(f"{path}-wal").exists())
        self.assertTrue(Path(f"{path}-shm").exists())
        return connection

    def test_preview_apply_and_wal_recreation_preserve_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp) / "runtime"
            runtime_dir.mkdir(mode=0o755)
            db_path = runtime_dir / "opencode.db"
            connection = self._create_wal_database(db_path)
            wal_path = Path(f"{db_path}-wal")
            shm_path = Path(f"{db_path}-shm")
            runtime_dir.chmod(0o755)
            for path in (db_path, wal_path, shm_path):
                path.chmod(0o644)
            bytes_before = {
                path: path.read_bytes() for path in (db_path, wal_path, shm_path)
            }
            identities_before = {
                path: (path.stat().st_dev, path.stat().st_ino)
                for path in (runtime_dir, db_path, wal_path, shm_path)
            }

            with patch.dict(
                os.environ,
                {"MY_OPENCODE_RUNTIME_DB_PATH": str(db_path)},
            ):
                module = self._module()
                code, preview = self._run_json(
                    module._command_repair_runtime_permissions,
                    ["--db-path", str(db_path), "--json"],
                )
                self.assertEqual(1, code)
                self.assertEqual(
                    "runtime_permission_repair_required",
                    preview["reason_code"],
                )
                self.assertEqual(0, preview["changed_count"])
                self.assertFalse(preview["partial"])
                self.assertEqual(0o755, runtime_dir.stat().st_mode & 0o777)
                self.assertTrue(
                    all(path.stat().st_mode & 0o777 == 0o644 for path in bytes_before)
                )

                code, applied = self._run_json(
                    module._command_repair_runtime_permissions,
                    ["--db-path", str(db_path), "--apply", "--json"],
                )
                self.assertEqual(0, code)
                self.assertEqual("PASS", applied["result"])
                self.assertEqual(4, applied["changed_count"])
                self.assertFalse(applied["partial"])
                self.assertGreaterEqual(applied["reconciliation_attempts"], 1)

            self.assertEqual(0o700, runtime_dir.stat().st_mode & 0o777)
            self.assertTrue(
                all(path.stat().st_mode & 0o777 == 0o600 for path in bytes_before)
            )
            self.assertEqual(
                bytes_before,
                {path: path.read_bytes() for path in (db_path, wal_path, shm_path)},
            )
            self.assertEqual(
                identities_before,
                {
                    path: (path.stat().st_dev, path.stat().st_ino)
                    for path in (runtime_dir, db_path, wal_path, shm_path)
                },
            )

            connection.execute("INSERT INTO canary (value) VALUES ('after')")
            connection.commit()
            self.assertEqual(
                2,
                connection.execute("SELECT COUNT(*) FROM canary").fetchone()[0],
            )
            self.assertEqual(
                "ok",
                connection.execute("PRAGMA quick_check").fetchone()[0],
            )
            connection.close()
            self.assertFalse(wal_path.exists())
            self.assertFalse(shm_path.exists())

            recreated = sqlite3.connect(db_path)
            try:
                recreated.execute("INSERT INTO canary (value) VALUES ('recreated')")
                recreated.commit()
                self.assertTrue(wal_path.exists())
                self.assertTrue(shm_path.exists())
                self.assertEqual(0o600, wal_path.stat().st_mode & 0o777)
                self.assertEqual(0o600, shm_path.stat().st_mode & 0o777)
                self.assertEqual(
                    "ok",
                    recreated.execute("PRAGMA quick_check").fetchone()[0],
                )
            finally:
                recreated.close()

    def test_apply_rejects_non_active_and_missing_database_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active_dir = root / "active"
            other_dir = root / "other"
            active_dir.mkdir(mode=0o755)
            other_dir.mkdir(mode=0o755)
            active_db = active_dir / "opencode.db"
            other_db = other_dir / "opencode.db"
            active_db.write_bytes(b"active")
            other_db.write_bytes(b"other")
            active_db.chmod(0o644)
            other_db.chmod(0o644)
            with patch.dict(
                os.environ,
                {"MY_OPENCODE_RUNTIME_DB_PATH": str(active_db)},
            ):
                module = self._module()
                code, payload = self._run_json(
                    module._command_repair_runtime_permissions,
                    ["--db-path", str(other_db), "--apply", "--json"],
                )
            self.assertEqual(1, code)
            self.assertEqual(
                "runtime_permission_path_not_active",
                payload["reason_code"],
            )
            self.assertEqual(0o755, other_dir.stat().st_mode & 0o777)
            self.assertEqual(0o644, other_db.stat().st_mode & 0o777)

        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp) / "runtime"
            runtime_dir.mkdir(mode=0o755)
            missing_db = runtime_dir / "opencode.db"
            with patch.dict(
                os.environ,
                {"MY_OPENCODE_RUNTIME_DB_PATH": str(missing_db)},
            ):
                module = self._module()
                code, payload = self._run_json(
                    module._command_repair_runtime_permissions,
                    ["--apply", "--json"],
                )
            self.assertEqual(1, code)
            self.assertEqual("runtime_db_missing", payload["reason_code"])
            self.assertEqual(0, payload["changed_count"])
            self.assertEqual(0o755, runtime_dir.stat().st_mode & 0o777)

    @unittest.skipUnless(hasattr(os, "link"), "hard links unsupported")
    def test_global_preflight_blocks_linked_or_permission_adding_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp) / "runtime"
            runtime_dir.mkdir(mode=0o755)
            db_path = runtime_dir / "opencode.db"
            db_path.write_bytes(b"linked")
            db_path.chmod(0o644)
            os.link(db_path, Path(f"{db_path}-wal"))
            with patch.dict(
                os.environ,
                {"MY_OPENCODE_RUNTIME_DB_PATH": str(db_path)},
            ):
                module = self._module()
                code, payload = self._run_json(
                    module._command_repair_runtime_permissions,
                    ["--apply", "--json"],
                )
            self.assertEqual(1, code)
            self.assertEqual(0, payload["changed_count"])
            self.assertEqual(0o755, runtime_dir.stat().st_mode & 0o777)
            self.assertEqual(0o644, db_path.stat().st_mode & 0o777)

        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp) / "runtime"
            runtime_dir.mkdir(mode=0o755)
            db_path = runtime_dir / "opencode.db"
            db_path.write_bytes(b"read-only")
            db_path.chmod(0o400)
            with patch.dict(
                os.environ,
                {"MY_OPENCODE_RUNTIME_DB_PATH": str(db_path)},
            ):
                module = self._module()
                code, payload = self._run_json(
                    module._command_repair_runtime_permissions,
                    ["--apply", "--json"],
                )
            self.assertEqual(1, code)
            self.assertEqual(
                "session_sidecar_insecure_permissions",
                payload["reason_code"],
            )
            self.assertEqual(0, payload["changed_count"])
            self.assertEqual(0o755, runtime_dir.stat().st_mode & 0o777)
            self.assertEqual(0o400, db_path.stat().st_mode & 0o777)

    def test_late_database_race_reports_partial_parent_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp) / "runtime"
            runtime_dir.mkdir(mode=0o755)
            db_path = runtime_dir / "opencode.db"
            db_path.write_bytes(b"database")
            db_path.chmod(0o644)
            with patch.dict(
                os.environ,
                {"MY_OPENCODE_RUNTIME_DB_PATH": str(db_path)},
            ):
                module = self._module()
                failure = module.SidecarSecurityError(
                    "session_sidecar_snapshot_changed",
                    "injected database race",
                    phase="repair",
                )
                with patch.object(
                    module,
                    "repair_active_file_mode",
                    side_effect=failure,
                ):
                    code, payload = self._run_json(
                        module._command_repair_runtime_permissions,
                        ["--apply", "--json"],
                    )
            self.assertEqual(1, code)
            self.assertTrue(payload["partial"])
            self.assertEqual(1, payload["changed_count"])
            self.assertEqual(0o700, runtime_dir.stat().st_mode & 0o777)
            self.assertEqual(0o644, db_path.stat().st_mode & 0o777)

    def test_committed_database_failure_is_reported_as_partial_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp) / "runtime"
            runtime_dir.mkdir(mode=0o700)
            db_path = runtime_dir / "opencode.db"
            db_path.write_bytes(b"database")
            db_path.chmod(0o644)
            with patch.dict(
                os.environ,
                {"MY_OPENCODE_RUNTIME_DB_PATH": str(db_path)},
            ):
                module = self._module()
                real_repair = module.repair_active_file_mode

                def fail_after_repair(path: Path, **kwargs):
                    real_repair(path, **kwargs)
                    raise module.SidecarSecurityError(
                        "session_sidecar_snapshot_changed",
                        "injected post-chmod reporting failure",
                        phase="authority",
                        committed=True,
                        durability="mode_applied",
                    )

                with patch.object(
                    module,
                    "repair_active_file_mode",
                    side_effect=fail_after_repair,
                ):
                    code, payload = self._run_json(
                        module._command_repair_runtime_permissions,
                        ["--apply", "--json"],
                    )
            self.assertEqual(1, code)
            self.assertTrue(payload["partial"])
            self.assertEqual(1, payload["changed_count"])
            db_finding = next(
                item
                for item in payload["runtime_permission_findings"]
                if item["target"] == "runtime_db"
            )
            self.assertTrue(db_finding["changed"])
            self.assertEqual("failed", db_finding["state"])
            self.assertEqual(0o600, db_path.stat().st_mode & 0o777)

    def test_doctor_and_gateway_share_permission_projection_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_dir = root / "runtime"
            runtime_dir.mkdir(mode=0o755)
            db_path = runtime_dir / "opencode.db"
            sqlite3.connect(db_path).close()
            db_path.chmod(0o644)
            index_path = root / "sessions" / "index.json"
            digest_path = root / "digests" / "last-session.json"
            index_path.parent.mkdir(mode=0o700)
            digest_path.parent.mkdir(mode=0o700)
            index_path.write_text(
                '{"version": 1, "sessions": []}', encoding="utf-8"
            )
            digest_path.write_text("{}", encoding="utf-8")
            index_path.chmod(0o600)
            digest_path.chmod(0o600)

            with patch.dict(
                os.environ,
                {
                    "MY_OPENCODE_RUNTIME_DB_PATH": str(db_path),
                    "MY_OPENCODE_DIGEST_PATH": str(digest_path),
                },
            ):
                module = self._module()
                code, doctor = self._run_json(
                    lambda argv: module._command_doctor(argv, index_path),
                    ["--db-path", str(db_path), "--json"],
                )
                self.assertEqual(1, code)
                self.assertEqual(
                    "repair_required",
                    doctor["runtime_permission_status"],
                )
                self.assertTrue(doctor["runtime_permission_apply_allowed"])
                self.assertEqual(
                    4,
                    len(doctor["runtime_permission_findings"]),
                )
                self.assertTrue(
                    any(
                        "repair-runtime-permissions" in item
                        for item in doctor["quick_fixes"]
                    )
                )

                gateway = importlib.reload(importlib.import_module("gateway_command"))
                summary = gateway.runtime_session_health_summary(db_path=db_path)
                self.assertEqual(
                    doctor["runtime_permission_status"],
                    summary["runtime_permission_status"],
                )
                self.assertEqual(
                    doctor["runtime_permission_findings"],
                    summary["runtime_permission_findings"],
                )
                self.assertTrue(
                    any(
                        "repair-runtime-permissions" in item
                        for item in summary["repair_commands"]
                    )
                )

                index_path.write_text("{malformed", encoding="utf-8")
                index_path.chmod(0o600)
                code, malformed = self._run_json(
                    lambda argv: module._command_doctor(argv, index_path),
                    ["--db-path", str(db_path), "--json"],
                )
                self.assertEqual(1, code)
                self.assertEqual(
                    doctor["runtime_permission_findings"],
                    malformed["runtime_permission_findings"],
                )

            self.assertEqual(0o755, runtime_dir.stat().st_mode & 0o777)
            self.assertEqual(0o644, db_path.stat().st_mode & 0o777)


if __name__ == "__main__":
    unittest.main()
