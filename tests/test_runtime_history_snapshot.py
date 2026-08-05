from __future__ import annotations

import contextlib
import hashlib
import importlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


class RuntimeHistorySnapshotTest(unittest.TestCase):
    def _module(self):
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        return importlib.reload(importlib.import_module("runtime_history_snapshot"))

    def _session_module(self):
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        return importlib.reload(importlib.import_module("session_command"))

    def _write_fake_opencode(self, path: Path, *, fail_query: bool = False) -> None:
        path.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sqlite3, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['XDG_CACHE_HOME']).joinpath('validator-cache').write_text('residue')\n"
            "Path(os.environ['HOME']).joinpath('validator.log').write_text('residue')\n"
            "Path(os.environ['TMPDIR']).joinpath('validator-tmp').write_text('residue')\n"
            "assert 'OPENCODE_SESSION_ID' not in os.environ\n"
            "if '--version' in sys.argv:\n"
            "    print('1.18.10-test')\n"
            "    raise SystemExit(0)\n"
            + (
                "print('injected failure', file=sys.stderr)\nraise SystemExit(7)\n"
                if fail_query
                else "db = Path(os.environ['XDG_DATA_HOME']) / 'opencode' / 'opencode.db'\n"
                "connection = sqlite3.connect(f'file:{db}?mode=ro', uri=True)\n"
                "value = connection.execute('PRAGMA schema_version').fetchone()[0]\n"
                "connection.close()\n"
                "print(json.dumps([{'schema_version': value}]))\n"
            ),
            encoding="utf-8",
        )
        path.chmod(0o700)

    def _create_source(
        self,
        root: Path,
        *,
        wal: bool = False,
    ) -> tuple[Path, sqlite3.Connection | None]:
        source_dir = root / "source"
        source_dir.mkdir(mode=0o700)
        db_path = source_dir / "opencode.db"
        initial = sqlite3.connect(db_path)
        initial.execute("CREATE TABLE marker (value TEXT PRIMARY KEY)")
        initial.commit()
        initial.close()
        db_path.chmod(0o600)
        if not wal:
            connection = sqlite3.connect(db_path)
            connection.execute("INSERT INTO marker VALUES ('source-row')")
            connection.commit()
            connection.close()
            return db_path, None

        writer = sqlite3.connect(db_path)
        self.assertEqual("wal", writer.execute("PRAGMA journal_mode=WAL").fetchone()[0])
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO marker VALUES ('committed-in-wal')")
        writer.commit()
        for sidecar in (Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
            self.assertTrue(sidecar.exists())
            sidecar.chmod(0o600)
        return db_path, writer

    def _private_output(self, root: Path) -> Path:
        output = root / "output"
        output.mkdir(mode=0o700)
        return output

    def test_two_private_bundles_include_wal_and_match_manifests(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path, writer = self._create_source(root, wal=True)
            assert writer is not None
            output = self._private_output(root)
            fake = root / "opencode"
            self._write_fake_opencode(fake)
            source_identity = (db_path.stat().st_dev, db_path.stat().st_ino)
            source_bytes = db_path.read_bytes()
            wal_path = Path(f"{db_path}-wal")
            wal_bytes = wal_path.read_bytes()
            shm_path = Path(f"{db_path}-shm")
            shm_identity = (shm_path.stat().st_dev, shm_path.stat().st_ino)
            external_tmp = root / "external-tmp"
            external_tmp.mkdir(mode=0o700)
            try:
                with patch.dict(
                    os.environ,
                    {
                        "MY_OPENCODE_RUNTIME_SNAPSHOT_OPENCODE_BIN": str(fake),
                        "TMPDIR": str(external_tmp),
                        "OPENCODE_SESSION_ID": "must-not-be-forwarded",
                    },
                ):
                    first = module.create_runtime_history_snapshot(db_path, output)
                    second = module.create_runtime_history_snapshot(
                        db_path,
                        output,
                        full_integrity_check=True,
                    )

                self.assertNotEqual(first["bundle_path"], second["bundle_path"])
                self.assertEqual("quick_check", first["check"])
                self.assertEqual("integrity_check", second["check"])
                for result in (first, second):
                    bundle = Path(result["bundle_path"])
                    snapshot = bundle / "runtime.sqlite3"
                    manifest_path = bundle / "manifest.json"
                    self.assertEqual(
                        ["manifest.json", "runtime.sqlite3"],
                        sorted(item.name for item in bundle.iterdir()),
                    )
                    self.assertEqual(0o700, bundle.stat().st_mode & 0o777)
                    self.assertEqual(0o600, snapshot.stat().st_mode & 0o777)
                    self.assertEqual(0o600, manifest_path.stat().st_mode & 0o777)
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    self.assertEqual(
                        module.SNAPSHOT_SCHEMA_VERSION, manifest["schema_version"]
                    )
                    self.assertEqual(module.SNAPSHOT_KIND, manifest["kind"])
                    self.assertEqual(
                        "open_file_descriptor",
                        manifest["backup"]["destination_binding"],
                    )
                    self.assertEqual(
                        hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                        manifest["artifact"]["sha256"],
                    )
                    self.assertEqual(
                        snapshot.stat().st_size, manifest["artifact"]["bytes"]
                    )
                    self.assertEqual(
                        "readable", manifest["application_validation"]["result"]
                    )
                    self.assertEqual(
                        "1.18.10-test",
                        manifest["application_validation"]["opencode_version"],
                    )
                    connection = sqlite3.connect(
                        f"file:{snapshot}?mode=ro&immutable=1", uri=True
                    )
                    try:
                        self.assertEqual(
                            [("committed-in-wal",)],
                            connection.execute("SELECT value FROM marker").fetchall(),
                        )
                    finally:
                        connection.close()

                self.assertEqual([], list(output.glob(".*.partial")))
                self.assertEqual([], list(output.glob(".*.validation")))
                self.assertEqual(
                    source_identity, (db_path.stat().st_dev, db_path.stat().st_ino)
                )
                self.assertEqual(source_bytes, db_path.read_bytes())
                self.assertEqual(wal_bytes, wal_path.read_bytes())
                self.assertEqual(
                    shm_identity,
                    (shm_path.stat().st_dev, shm_path.stat().st_ino),
                )
                self.assertEqual([], list(external_tmp.iterdir()))
            finally:
                writer.close()

    def test_capacity_and_application_failures_leave_no_bundle(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path, _ = self._create_source(root)
            output = self._private_output(root)
            fake = root / "opencode"
            self._write_fake_opencode(fake)
            with (
                patch.dict(
                    os.environ,
                    {"MY_OPENCODE_RUNTIME_SNAPSHOT_OPENCODE_BIN": str(fake)},
                ),
                patch.object(
                    module.shutil,
                    "disk_usage",
                    return_value=SimpleNamespace(free=0),
                ),
                self.assertRaises(module.RuntimeSnapshotError) as raised,
            ):
                module.create_runtime_history_snapshot(db_path, output)
            self.assertEqual("runtime_snapshot_insufficient_capacity", raised.exception.reason_code)
            self.assertEqual([], list(output.iterdir()))

        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path, _ = self._create_source(root)
            output = self._private_output(root)
            fake = root / "opencode"
            self._write_fake_opencode(fake)
            available = 1024 * 1024 * 1024
            with (
                patch.dict(
                    os.environ,
                    {"MY_OPENCODE_RUNTIME_SNAPSHOT_OPENCODE_BIN": str(fake)},
                ),
                patch.object(
                    module.shutil,
                    "disk_usage",
                    side_effect=[
                        SimpleNamespace(free=available),
                        SimpleNamespace(free=0),
                    ],
                ),
                self.assertRaises(module.RuntimeSnapshotError) as raised,
            ):
                module.create_runtime_history_snapshot(db_path, output)
            self.assertEqual("runtime_snapshot_insufficient_capacity", raised.exception.reason_code)
            self.assertEqual("capacity", raised.exception.phase)
            self.assertEqual([], list(output.iterdir()))

        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path, _ = self._create_source(root)
            output = self._private_output(root)
            fake = root / "opencode"
            self._write_fake_opencode(fake, fail_query=True)
            with (
                patch.dict(
                    os.environ,
                    {"MY_OPENCODE_RUNTIME_SNAPSHOT_OPENCODE_BIN": str(fake)},
                ),
                self.assertRaises(module.RuntimeSnapshotError) as raised,
            ):
                module.create_runtime_history_snapshot(db_path, output)
            self.assertEqual(
                "runtime_snapshot_application_open_failed", raised.exception.reason_code
            )
            self.assertEqual([], list(output.iterdir()))

    def test_backup_check_copy_and_application_timeouts_are_distinct(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination = root / "backup.db"
            destination_fd = os.open(
                destination,
                os.O_RDWR | os.O_CREAT | os.O_EXCL,
                0o600,
            )

            class Source:
                def execute(self, _statement):
                    return self

                def backup(self, _destination, *, pages, progress, sleep):
                    self.assertions = (pages, sleep)
                    progress(0, 1, 2)

            try:
                with (
                    patch.object(module, "SNAPSHOT_BACKUP_TIMEOUT_SECONDS", 0.5),
                    patch.object(
                        module.time,
                        "monotonic",
                        side_effect=[0.0, 0.0, 0.0, 0.0, 1.0],
                    ),
                    self.assertRaises(module.RuntimeSnapshotError) as raised,
                ):
                    module._run_online_backup(Source(), destination_fd)
            finally:
                os.close(destination_fd)
            self.assertEqual("runtime_snapshot_backup_timeout", raised.exception.reason_code)
            self.assertEqual("backup", raised.exception.phase)

        module = self._module()

        class CheckConnection:
            def __init__(self) -> None:
                self.progress = None

            def execute(self, statement):
                if statement == "PRAGMA quick_check":
                    assert self.progress is not None
                    self.progress()
                    raise sqlite3.OperationalError("interrupted")
                return self

            def set_progress_handler(self, handler, _steps):
                self.progress = handler

            def close(self):
                return None

        with (
            patch.object(module, "SNAPSHOT_CHECK_TIMEOUT_SECONDS", 0.5),
            patch.object(
                module.time,
                "monotonic",
                side_effect=[0.0, 0.0, 0.0, 1.0],
            ),
            patch.object(module.sqlite3, "connect", return_value=CheckConnection()),
            self.assertRaises(module.RuntimeSnapshotError) as raised,
        ):
            module._validate_snapshot_database(7, "quick_check")
        self.assertEqual("runtime_snapshot_check_timeout", raised.exception.reason_code)
        self.assertEqual("integrity_check", raised.exception.phase)

        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.write_bytes(b"snapshot")
            source.chmod(0o600)
            destination = root / "destination"
            destination_fd = os.open(
                destination,
                os.O_RDWR | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            source_fd = os.open(source, os.O_RDONLY)
            identity = module._identity_from_stat(os.lstat(source))
            try:
                with (
                    patch.object(module, "SNAPSHOT_COPY_TIMEOUT_SECONDS", 0.5),
                    patch.object(module.time, "monotonic", side_effect=[0.0, 1.0]),
                    self.assertRaises(module.RuntimeSnapshotError) as raised,
                ):
                    module._copy_and_hash(
                        source_fd,
                        destination_fd,
                        expected_source=identity,
                    )
            finally:
                os.close(source_fd)
                os.close(destination_fd)
            self.assertEqual("runtime_snapshot_copy_timeout", raised.exception.reason_code)
            self.assertEqual("copy_hash", raised.exception.phase)

        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sandbox = root / "sandbox"
            sandbox.mkdir(mode=0o700)
            sandbox_fd = os.open(
                sandbox,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            layout, opencode_fd = module._create_sandbox_layout(sandbox, sandbox_fd)
            fake = root / "opencode"
            self._write_fake_opencode(fake)
            binary = module._binary_identity(fake)
            try:
                with (
                    patch.object(
                        module.subprocess,
                        "run",
                        side_effect=subprocess.TimeoutExpired(
                            [str(fake), "--version"], 1
                        ),
                    ),
                    self.assertRaises(module.RuntimeSnapshotError) as raised,
                ):
                    module._run_application_validation(binary, layout)
            finally:
                os.close(opencode_fd)
                os.close(sandbox_fd)
            self.assertEqual(
                "runtime_snapshot_application_timeout", raised.exception.reason_code
            )
            self.assertEqual("application_validation", raised.exception.phase)

    def test_sqlite_setup_is_capped_by_each_phase_deadline(self) -> None:
        module = self._module()

        class SetupConnection:
            def __init__(self) -> None:
                self.progress_handlers = []

            def execute(self, statement):
                if statement == "PRAGMA journal_mode = OFF":
                    return SimpleNamespace(fetchone=lambda: ("off",))
                return self

            def set_progress_handler(self, handler, _steps):
                self.progress_handlers.append(handler)

            def close(self):
                return None

        class Source:
            def execute(self, _statement):
                return self

            def backup(self, *_args, **_kwargs):
                raise AssertionError("backup must not start after setup deadline")

        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "destination.db"
            destination_fd = os.open(
                destination,
                os.O_RDWR | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            connection = SetupConnection()
            try:
                with (
                    patch.object(module, "SNAPSHOT_BACKUP_TIMEOUT_SECONDS", 0.25),
                    patch.object(
                        module.time,
                        "monotonic",
                        side_effect=[0.0, 0.0, 0.0, 1.0],
                    ),
                    patch.object(
                        module.sqlite3,
                        "connect",
                        return_value=connection,
                    ) as connect,
                    self.assertRaises(module.RuntimeSnapshotError) as raised,
                ):
                    module._run_online_backup(Source(), destination_fd)
            finally:
                os.close(destination_fd)
            self.assertEqual("runtime_snapshot_backup_timeout", raised.exception.reason_code)
            self.assertEqual(0.25, connect.call_args.kwargs["timeout"])

        module = self._module()
        connection = SetupConnection()
        with (
            patch.object(module, "SNAPSHOT_CHECK_TIMEOUT_SECONDS", 0.25),
            patch.object(
                module.time,
                "monotonic",
                side_effect=[0.0, 0.0, 1.0],
            ),
            patch.object(
                module.sqlite3,
                "connect",
                return_value=connection,
            ) as connect,
            self.assertRaises(module.RuntimeSnapshotError) as raised,
        ):
            module._validate_snapshot_database(7, "quick_check")
        self.assertEqual("runtime_snapshot_check_timeout", raised.exception.reason_code)
        self.assertEqual(0.25, connect.call_args.kwargs["timeout"])
        self.assertFalse(any(handler is not None for handler in connection.progress_handlers))

    def test_source_targets_fail_closed_before_output_publication(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "source"
            source_dir.mkdir(mode=0o700)
            victim = source_dir / "victim.db"
            sqlite3.connect(victim).close()
            victim.chmod(0o600)
            symlink = source_dir / "opencode.db"
            symlink.symlink_to(victim)
            with self.assertRaises(module.RuntimeSnapshotError):
                module._inspect_source(symlink)

        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path, _ = self._create_source(root)
            os.link(db_path, db_path.with_name("linked.db"))
            with self.assertRaises(module.RuntimeSnapshotError):
                module._inspect_source(db_path)

        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path, _ = self._create_source(root)
            db_path.chmod(0o644)
            with self.assertRaises(module.RuntimeSnapshotError):
                module._inspect_source(db_path)

    def test_database_replacement_after_backup_blocks_publication(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path, _ = self._create_source(root)
            output = self._private_output(root)
            fake = root / "opencode"
            self._write_fake_opencode(fake)
            replacement = db_path.with_name("replacement.db")
            connection = sqlite3.connect(replacement)
            connection.execute("CREATE TABLE replacement (value TEXT)")
            connection.commit()
            connection.close()
            replacement.chmod(0o600)
            real_backup = module._run_online_backup

            def backup_then_replace(source, destination):
                result = real_backup(source, destination)
                os.replace(replacement, db_path)
                return result

            with (
                patch.dict(
                    os.environ,
                    {"MY_OPENCODE_RUNTIME_SNAPSHOT_OPENCODE_BIN": str(fake)},
                ),
                patch.object(
                    module,
                    "_run_online_backup",
                    side_effect=backup_then_replace,
                ),
                self.assertRaises(module.RuntimeSnapshotError) as raised,
            ):
                module.create_runtime_history_snapshot(db_path, output)
            self.assertEqual("runtime_snapshot_source_changed", raised.exception.reason_code)
            self.assertEqual([], list(output.iterdir()))
            check = sqlite3.connect(db_path)
            try:
                self.assertEqual(
                    [("replacement",)],
                    check.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall(),
                )
            finally:
                check.close()

    def test_artifact_mutation_after_hash_blocks_publication(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path, _ = self._create_source(root)
            output = self._private_output(root)
            fake = root / "opencode"
            self._write_fake_opencode(fake)
            real_inventory = module._bundle_inventory
            mutated = False

            def mutate_then_inventory(
                staging_fd,
                snapshot_fd,
                snapshot_identity,
                manifest_fd,
                manifest_identity,
            ):
                nonlocal mutated
                if not mutated:
                    os.lseek(snapshot_fd, 0, os.SEEK_END)
                    os.write(snapshot_fd, b"injected mutation")
                    os.fsync(snapshot_fd)
                    mutated = True
                return real_inventory(
                    staging_fd,
                    snapshot_fd,
                    snapshot_identity,
                    manifest_fd,
                    manifest_identity,
                )

            with (
                patch.dict(
                    os.environ,
                    {"MY_OPENCODE_RUNTIME_SNAPSHOT_OPENCODE_BIN": str(fake)},
                ),
                patch.object(
                    module,
                    "_bundle_inventory",
                    side_effect=mutate_then_inventory,
                ),
                self.assertRaises(module.RuntimeSnapshotError) as raised,
            ):
                module.create_runtime_history_snapshot(db_path, output)
            self.assertEqual("runtime_snapshot_artifact_changed", raised.exception.reason_code)
            self.assertFalse(raised.exception.committed)
            self.assertEqual([], list(output.iterdir()))

    def test_staging_directory_replacement_receives_no_snapshot_bytes(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path, _ = self._create_source(root)
            output = self._private_output(root)
            fake = root / "opencode"
            self._write_fake_opencode(fake)
            moved = output / ".moved-owned-staging"
            replacement: Path | None = None
            real_backup = module._run_online_backup

            def replace_then_backup(source, destination_fd):
                nonlocal replacement
                partials = list(output.glob(".*.partial"))
                self.assertEqual(1, len(partials))
                partial = partials[0]
                partial.rename(moved)
                partial.mkdir(mode=0o700)
                replacement = partial
                (partial / "replacement-marker").write_text(
                    "preserve",
                    encoding="utf-8",
                )
                return real_backup(source, destination_fd)

            with (
                patch.dict(
                    os.environ,
                    {"MY_OPENCODE_RUNTIME_SNAPSHOT_OPENCODE_BIN": str(fake)},
                ),
                patch.object(
                    module,
                    "_run_online_backup",
                    side_effect=replace_then_backup,
                ),
                self.assertRaises(module.RuntimeSnapshotError) as raised,
            ):
                module.create_runtime_history_snapshot(db_path, output)
            self.assertEqual(
                "runtime_snapshot_owned_path_changed", raised.exception.reason_code
            )
            self.assertFalse(raised.exception.committed)
            self.assertFalse(moved.exists())
            assert replacement is not None
            self.assertEqual(
                ["replacement-marker"],
                sorted(path.name for path in replacement.iterdir()),
            )
            self.assertEqual(
                "preserve",
                (replacement / "replacement-marker").read_text(encoding="utf-8"),
            )

    def test_exclusive_publication_preserves_raced_destination(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path, _ = self._create_source(root)
            output = self._private_output(root)
            fake = root / "opencode"
            self._write_fake_opencode(fake)
            real_rename = module._rename_exclusive
            raced_name: str | None = None

            def create_destination_then_rename(
                source_dir_fd,
                source_name,
                target_dir_fd,
                target_name,
            ):
                nonlocal raced_name
                raced_name = target_name
                os.mkdir(target_name, 0o700, dir_fd=target_dir_fd)
                target_fd = os.open(
                    target_name,
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | os.O_NOFOLLOW
                    | os.O_CLOEXEC,
                    dir_fd=target_dir_fd,
                )
                try:
                    marker_fd = os.open(
                        "replacement-marker",
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=target_fd,
                    )
                    os.write(marker_fd, b"preserve")
                    os.close(marker_fd)
                finally:
                    os.close(target_fd)
                return real_rename(
                    source_dir_fd,
                    source_name,
                    target_dir_fd,
                    target_name,
                )

            with (
                patch.dict(
                    os.environ,
                    {"MY_OPENCODE_RUNTIME_SNAPSHOT_OPENCODE_BIN": str(fake)},
                ),
                patch.object(
                    module,
                    "_rename_exclusive",
                    side_effect=create_destination_then_rename,
                ),
                self.assertRaises(module.RuntimeSnapshotError) as raised,
            ):
                module.create_runtime_history_snapshot(db_path, output)
            self.assertEqual("runtime_snapshot_name_collision", raised.exception.reason_code)
            self.assertFalse(raised.exception.committed)
            assert raced_name is not None
            raced = output / raced_name
            self.assertEqual(
                "preserve",
                (raced / "replacement-marker").read_text(encoding="utf-8"),
            )
            self.assertEqual([], list(output.glob(".*.partial")))
            self.assertEqual([], list(output.glob(".*.validation")))

    def test_application_validation_uses_one_shared_deadline(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sandbox = root / "sandbox"
            sandbox.mkdir(mode=0o700)
            sandbox_fd = os.open(
                sandbox,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            layout, opencode_fd = module._create_sandbox_layout(sandbox, sandbox_fd)
            fake = root / "opencode"
            self._write_fake_opencode(fake)
            binary = module._binary_identity(fake)
            runs = [
                subprocess.CompletedProcess([str(fake)], 0, "1.18.10-test\n", ""),
                subprocess.CompletedProcess(
                    [str(fake)],
                    0,
                    '[{"schema_version": 1}]\n',
                    "",
                ),
            ]
            try:
                with (
                    patch.object(module, "SNAPSHOT_APPLICATION_TIMEOUT_SECONDS", 60.0),
                    patch.object(
                        module.time,
                        "monotonic",
                        side_effect=[0.0, 1.0, 41.0],
                    ),
                    patch.object(
                        module.subprocess,
                        "run",
                        side_effect=runs,
                    ) as run,
                ):
                    result = module._run_application_validation(binary, layout)
            finally:
                os.close(opencode_fd)
                os.close(sandbox_fd)
            self.assertEqual("readable", result["result"])
            self.assertEqual(59.0, run.call_args_list[0].kwargs["timeout"])
            self.assertEqual(19.0, run.call_args_list[1].kwargs["timeout"])

    def test_post_rename_fsync_failure_reports_committed_uncertain_bundle(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path, _ = self._create_source(root)
            output = self._private_output(root)
            fake = root / "opencode"
            self._write_fake_opencode(fake)
            with (
                patch.dict(
                    os.environ,
                    {"MY_OPENCODE_RUNTIME_SNAPSHOT_OPENCODE_BIN": str(fake)},
                ),
                patch.object(
                    module,
                    "_fsync_output_directory",
                    side_effect=OSError("injected root fsync failure"),
                ),
                self.assertRaises(module.RuntimeSnapshotError) as raised,
            ):
                module.create_runtime_history_snapshot(db_path, output)
            self.assertTrue(
                raised.exception.committed,
                (raised.exception.reason_code, raised.exception.phase, str(raised.exception)),
            )
            self.assertEqual("uncertain", raised.exception.durability)
            self.assertIsNotNone(raised.exception.bundle_path)
            bundle = raised.exception.bundle_path
            assert bundle is not None
            self.assertTrue(bundle.is_dir())
            self.assertEqual(
                ["manifest.json", "runtime.sqlite3"],
                sorted(item.name for item in bundle.iterdir()),
            )

    def test_owned_cleanup_refuses_replaced_directory(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o700)
            root_fd = os.open(
                root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            owned, owned_fd, identity = module._mkdir_owned(root_fd, root, "owned")
            (owned / "created-by-snapshot").write_text("owned", encoding="utf-8")
            moved = root / "moved"
            real_clear = module._clear_owned_directory

            def swap_then_clear(descriptor: int) -> None:
                os.rename("owned", "moved", src_dir_fd=root_fd, dst_dir_fd=root_fd)
                os.mkdir("owned", 0o700, dir_fd=root_fd)
                (root / "owned" / "replacement").write_text(
                    "preserve",
                    encoding="utf-8",
                )
                real_clear(descriptor)

            try:
                with (
                    patch.object(
                        module,
                        "_clear_owned_directory",
                        side_effect=swap_then_clear,
                    ),
                    self.assertRaises(module.RuntimeSnapshotError) as raised,
                ):
                    module._cleanup_owned_tree(root_fd, "owned", owned_fd, identity)
            finally:
                os.close(owned_fd)
                os.close(root_fd)
            self.assertEqual(
                "runtime_snapshot_owned_path_changed", raised.exception.reason_code
            )
            self.assertEqual(
                "preserve",
                (root / "owned" / "replacement").read_text(encoding="utf-8"),
            )
            self.assertFalse(moved.exists())

    def test_cli_parser_rejects_duplicates_and_non_active_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / "source" / "opencode.db"
            active.parent.mkdir(mode=0o700)
            sqlite3.connect(active).close()
            active.chmod(0o600)
            output = root / "output"
            output.mkdir(mode=0o700)
            with patch.dict(
                os.environ,
                {"MY_OPENCODE_RUNTIME_DB_PATH": str(active)},
            ):
                module = self._session_module()
                self.assertIsNone(
                    module._parse_snapshot_runtime_options(
                        ["--output-dir", str(output), "--output-dir", str(output)]
                    )
                )
                with contextlib.redirect_stdout(io.StringIO()) as stdout:
                    code = module._command_snapshot_runtime(
                        [
                            "--db-path",
                            str(root / "other.db"),
                            "--output-dir",
                            str(output),
                            "--json",
                        ]
                    )
                payload = json.loads(stdout.getvalue())
            self.assertEqual(1, code)
            self.assertEqual("runtime_snapshot_path_not_active", payload["reason_code"])
            self.assertEqual([], list(output.iterdir()))


if __name__ == "__main__":
    unittest.main()
