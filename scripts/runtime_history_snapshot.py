from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
import uuid
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from session_sidecar_security import (  # type: ignore
    PRIVATE_DIRECTORY_MODE,
    PRIVATE_FILE_MODE,
    SidecarInspection,
    SidecarSecurityError,
    SidecarSnapshot,
    ensure_private_directory,
    inspect_private_directory,
    inspect_sidecar,
)

SNAPSHOT_SCHEMA_VERSION = 1
SNAPSHOT_KIND = "opencode-runtime-history-snapshot"
SNAPSHOT_FILE_NAME = "runtime.sqlite3"
SNAPSHOT_MANIFEST_NAME = "manifest.json"
SNAPSHOT_MANIFEST_MAX_BYTES = 1024 * 1024
SNAPSHOT_METADATA_ALLOWANCE_BYTES = 1024 * 1024
SNAPSHOT_MIN_RESERVE_BYTES = 64 * 1024 * 1024
SNAPSHOT_COPY_CHUNK_BYTES = 8 * 1024 * 1024
SNAPSHOT_BACKUP_PAGES = 1024
SNAPSHOT_BACKUP_SLEEP_SECONDS = 0.1


def _positive_float_env(name: str, default: float) -> float:
    try:
        return max(0.1, float(os.environ.get(name, str(default)) or str(default)))
    except ValueError:
        return default


SNAPSHOT_BACKUP_TIMEOUT_SECONDS = _positive_float_env(
    "MY_OPENCODE_RUNTIME_SNAPSHOT_BACKUP_TIMEOUT_SECONDS", 1800.0
)
SNAPSHOT_CHECK_TIMEOUT_SECONDS = _positive_float_env(
    "MY_OPENCODE_RUNTIME_SNAPSHOT_CHECK_TIMEOUT_SECONDS", 600.0
)
SNAPSHOT_COPY_TIMEOUT_SECONDS = _positive_float_env(
    "MY_OPENCODE_RUNTIME_SNAPSHOT_COPY_TIMEOUT_SECONDS", 600.0
)
SNAPSHOT_APPLICATION_TIMEOUT_SECONDS = _positive_float_env(
    "MY_OPENCODE_RUNTIME_SNAPSHOT_APPLICATION_TIMEOUT_SECONDS", 60.0
)


def default_runtime_snapshot_output_dir() -> Path:
    configured = os.environ.get("MY_OPENCODE_RUNTIME_SNAPSHOT_OUTPUT_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    state_home = os.environ.get("XDG_STATE_HOME", "").strip()
    root = Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state"
    return root / "my_opencode" / "runtime-history-snapshots"


class RuntimeSnapshotError(RuntimeError):
    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        phase: str,
        committed: bool = False,
        durability: str = "not_committed",
        bundle_path: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.phase = phase
        self.committed = committed
        self.durability = durability
        self.bundle_path = bundle_path


@dataclass(frozen=True)
class _Identity:
    dev: int
    ino: int
    mode: int
    uid: int
    nlink: int
    kind: str
    size: int
    mtime_ns: int
    ctime_ns: int

    def payload(self) -> dict[str, Any]:
        return {
            "dev": self.dev,
            "ino": self.ino,
            "mode": self.mode,
            "uid": self.uid,
            "nlink": self.nlink,
            "kind": self.kind,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "ctime_ns": self.ctime_ns,
        }


@dataclass(frozen=True)
class _BinaryIdentity:
    path: Path
    dev: int
    ino: int
    mode: int
    uid: int
    size: int
    mtime_ns: int

    def payload(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "dev": self.dev,
            "ino": self.ino,
            "mode": self.mode,
            "uid": self.uid,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
        }


def _error(
    reason_code: str,
    message: str,
    *,
    phase: str,
    committed: bool = False,
    durability: str = "not_committed",
    bundle_path: Path | None = None,
) -> RuntimeSnapshotError:
    return RuntimeSnapshotError(
        reason_code,
        message,
        phase=phase,
        committed=committed,
        durability=durability,
        bundle_path=bundle_path,
    )


def _identity_from_snapshot(snapshot: SidecarSnapshot, *, kind: str) -> _Identity:
    return _Identity(
        dev=snapshot.dev,
        ino=snapshot.ino,
        mode=snapshot.mode,
        uid=snapshot.uid,
        nlink=snapshot.nlink,
        kind=kind,
        size=snapshot.size,
        mtime_ns=snapshot.mtime_ns,
        ctime_ns=snapshot.ctime_ns,
    )


def _identity_from_stat(value: os.stat_result) -> _Identity:
    if stat.S_ISDIR(value.st_mode):
        kind = "directory"
    elif stat.S_ISREG(value.st_mode):
        kind = "file"
    else:
        kind = "other"
    return _Identity(
        dev=int(value.st_dev),
        ino=int(value.st_ino),
        mode=stat.S_IMODE(value.st_mode),
        uid=int(value.st_uid),
        nlink=int(value.st_nlink),
        kind=kind,
        size=int(value.st_size),
        mtime_ns=int(value.st_mtime_ns),
        ctime_ns=int(value.st_ctime_ns),
    )


def _bound_identity_matches(left: _Identity, right: _Identity) -> bool:
    return (
        left.dev == right.dev
        and left.ino == right.ino
        and left.mode == right.mode
        and left.uid == right.uid
        and left.kind == right.kind
        and (left.kind != "file" or left.nlink == right.nlink)
    )


def _strict_file_identity_matches(left: _Identity, right: _Identity) -> bool:
    return (
        left.kind == "file"
        and right.kind == "file"
        and _bound_identity_matches(left, right)
        and left.size == right.size
        and left.mtime_ns == right.mtime_ns
        and left.ctime_ns == right.ctime_ns
    )


def _require_private_inspection(
    inspection: SidecarInspection,
    *,
    allow_missing: bool,
) -> None:
    if inspection.state == "private":
        return
    if allow_missing and inspection.state == "missing":
        return
    reason = inspection.reason_code or "runtime_snapshot_source_not_private"
    raise _error(
        reason,
        f"runtime snapshot source target {inspection.target} is not private and safe",
        phase="source_authority",
    )


def _inspect_source(db_path: Path) -> dict[str, SidecarInspection]:
    absolute = Path(os.path.abspath(os.fspath(db_path.expanduser())))
    paths = {
        "runtime_parent": absolute.parent,
        "runtime_db": absolute,
        "runtime_wal": Path(f"{absolute}-wal"),
        "runtime_shm": Path(f"{absolute}-shm"),
    }
    try:
        observations = {
            "runtime_parent": inspect_private_directory(
                paths["runtime_parent"], target="runtime_parent"
            ),
            "runtime_db": inspect_sidecar(paths["runtime_db"], target="runtime_db"),
            "runtime_wal": inspect_sidecar(
                paths["runtime_wal"], target="runtime_wal"
            ),
            "runtime_shm": inspect_sidecar(
                paths["runtime_shm"], target="runtime_shm"
            ),
        }
    except SidecarSecurityError as exc:
        raise _error(
            exc.reason_code,
            "runtime snapshot source authority check failed",
            phase="source_authority",
        ) from exc
    _require_private_inspection(observations["runtime_parent"], allow_missing=False)
    _require_private_inspection(observations["runtime_db"], allow_missing=False)
    _require_private_inspection(observations["runtime_wal"], allow_missing=True)
    _require_private_inspection(observations["runtime_shm"], allow_missing=True)
    return observations


def _source_observation_payload(
    observations: Mapping[str, SidecarInspection],
) -> list[dict[str, Any]]:
    return [observations[target].to_payload() for target in observations]


def _require_stable_database_identity(
    observations: Mapping[str, SidecarInspection],
    expected: _Identity,
) -> None:
    snapshot = observations["runtime_db"].snapshot
    if snapshot is None or not _bound_identity_matches(
        _identity_from_snapshot(snapshot, kind="file"), expected
    ):
        raise _error(
            "runtime_snapshot_source_changed",
            "runtime database identity changed during snapshot creation",
            phase="source_authority",
        )


def _prepare_private_output_root(path: Path) -> tuple[Path, int, _Identity]:
    try:
        normalized = ensure_private_directory(path)
        inspection = inspect_private_directory(normalized, target="snapshot_output")
    except SidecarSecurityError as exc:
        raise _error(
            exc.reason_code,
            "runtime snapshot output authority is unsafe",
            phase="output_authority",
        ) from exc
    if inspection.state != "private" or inspection.snapshot is None:
        raise _error(
            "runtime_snapshot_output_not_private",
            "runtime snapshot output directory must be mode 0700",
            phase="output_authority",
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        descriptor = os.open(normalized, flags)
        opened = os.fstat(descriptor)
        current = os.lstat(normalized)
    except OSError as exc:
        if "descriptor" in locals():
            os.close(descriptor)
        raise _error(
            "runtime_snapshot_output_unavailable",
            "runtime snapshot output directory could not be opened",
            phase="output_authority",
        ) from exc
    identity = _identity_from_stat(opened)
    if (
        identity.kind != "directory"
        or identity.mode != PRIVATE_DIRECTORY_MODE
        or identity.uid != os.geteuid()
        or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
    ):
        os.close(descriptor)
        raise _error(
            "runtime_snapshot_output_changed",
            "runtime snapshot output directory changed while opening",
            phase="output_authority",
        )
    return normalized, descriptor, identity


def _verify_output_root(path: Path, descriptor: int, expected: _Identity) -> None:
    try:
        opened = _identity_from_stat(os.fstat(descriptor))
        current = _identity_from_stat(os.lstat(path))
    except OSError as exc:
        raise _error(
            "runtime_snapshot_output_changed",
            "runtime snapshot output authority became unavailable",
            phase="output_authority",
        ) from exc
    if not _bound_identity_matches(opened, expected) or not _bound_identity_matches(
        current, expected
    ):
        raise _error(
            "runtime_snapshot_output_changed",
            "runtime snapshot output authority changed",
            phase="output_authority",
        )


def _mkdir_owned(
    parent_fd: int,
    parent: Path,
    name: str,
) -> tuple[Path, int, _Identity]:
    descriptor: int | None = None
    created = False
    try:
        os.mkdir(name, PRIVATE_DIRECTORY_MODE, dir_fd=parent_fd)
        created = True
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_fd,
        )
        metadata = os.fstat(descriptor)
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileExistsError as exc:
        raise _error(
            "runtime_snapshot_name_collision",
            "runtime snapshot generated name already exists",
            phase="staging",
        ) from exc
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            try:
                os.rmdir(name, dir_fd=parent_fd)
            except OSError as cleanup_exc:
                raise _error(
                    "runtime_snapshot_cleanup_failed",
                    "runtime snapshot newly created directory could not be removed",
                    phase="cleanup",
                ) from cleanup_exc
        raise _error(
            "runtime_snapshot_staging_failed",
            "runtime snapshot staging directory could not be created",
            phase="staging",
        ) from exc
    identity = _identity_from_stat(metadata)
    if (
        identity.kind != "directory"
        or identity.uid != os.geteuid()
        or identity.mode != PRIVATE_DIRECTORY_MODE
        or (metadata.st_dev, metadata.st_ino) != (current.st_dev, current.st_ino)
    ):
        os.close(descriptor)
        try:
            os.rmdir(name, dir_fd=parent_fd)
        except OSError as exc:
            raise _error(
                "runtime_snapshot_cleanup_failed",
                "unsafe runtime snapshot directory could not be removed",
                phase="cleanup",
            ) from exc
        raise _error(
            "runtime_snapshot_staging_failed",
            "runtime snapshot staging directory is not private",
            phase="staging",
        )
    return parent / name, descriptor, identity


def _create_private_file_at(
    parent_fd: int,
    parent: Path,
    name: str,
) -> tuple[Path, int, _Identity]:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor: int | None = None
    try:
        descriptor = os.open(name, flags, PRIVATE_FILE_MODE, dir_fd=parent_fd)
        metadata = os.fstat(descriptor)
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise _error(
            "runtime_snapshot_file_create_failed",
            "runtime snapshot private file could not be created",
            phase="staging",
        ) from exc
    identity = _identity_from_stat(metadata)
    if (
        identity.kind != "file"
        or identity.uid != os.geteuid()
        or identity.nlink != 1
        or identity.mode != PRIVATE_FILE_MODE
    ):
        os.close(descriptor)
        raise _error(
            "runtime_snapshot_file_create_failed",
            "runtime snapshot private file identity is unsafe",
            phase="staging",
        )
    return parent / name, descriptor, identity


def _verify_file_entry(
    parent_fd: int,
    name: str,
    descriptor: int,
    expected: _Identity,
    *,
    phase: str,
    strict: bool,
) -> _Identity:
    try:
        opened = _identity_from_stat(os.fstat(descriptor))
        current = _identity_from_stat(
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        )
    except OSError as exc:
        raise _error(
            "runtime_snapshot_artifact_changed",
            "runtime snapshot artifact became unavailable",
            phase=phase,
        ) from exc
    matcher = _strict_file_identity_matches if strict else _bound_identity_matches
    if not matcher(opened, expected) or not matcher(current, expected):
        raise _error(
            "runtime_snapshot_artifact_changed",
            "runtime snapshot artifact identity changed",
            phase=phase,
        )
    return opened


def _verify_owned_entry(
    parent_fd: int,
    name: str,
    descriptor: int,
    expected: _Identity,
    *,
    phase: str = "cleanup",
) -> None:
    try:
        opened = _identity_from_stat(os.fstat(descriptor))
        current = _identity_from_stat(
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        )
    except OSError as exc:
        raise _error(
            "runtime_snapshot_owned_path_changed",
            "runtime snapshot owned path became unavailable",
            phase=phase,
        ) from exc
    if not _bound_identity_matches(opened, expected) or not _bound_identity_matches(
        current, expected
    ):
        raise _error(
            "runtime_snapshot_owned_path_changed",
            "runtime snapshot owned path identity changed",
            phase=phase,
        )


def _clear_owned_directory(descriptor: int) -> None:
    try:
        with os.scandir(descriptor) as entries:
            names = [entry.name for entry in entries]
        for name in names:
            metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                child = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=descriptor,
                )
                try:
                    opened = os.fstat(child)
                    if (opened.st_dev, opened.st_ino) != (
                        metadata.st_dev,
                        metadata.st_ino,
                    ):
                        raise _error(
                            "runtime_snapshot_owned_path_changed",
                            "runtime snapshot cleanup child identity changed",
                            phase="cleanup",
                        )
                    _clear_owned_directory(child)
                finally:
                    os.close(child)
                os.rmdir(name, dir_fd=descriptor)
            else:
                os.unlink(name, dir_fd=descriptor)
    except RuntimeSnapshotError:
        raise
    except OSError as exc:
        raise _error(
            "runtime_snapshot_cleanup_failed",
            "runtime snapshot owned directory contents could not be removed",
            phase="cleanup",
        ) from exc


def _find_owned_entry_name(
    parent_fd: int,
    expected: _Identity,
) -> str | None:
    try:
        with os.scandir(parent_fd) as entries:
            names = [entry.name for entry in entries]
        matches: list[str] = []
        for name in names:
            metadata = _identity_from_stat(
                os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            )
            if _bound_identity_matches(metadata, expected):
                matches.append(name)
    except OSError as exc:
        raise _error(
            "runtime_snapshot_cleanup_failed",
            "runtime snapshot output directory could not be searched for owned cleanup",
            phase="cleanup",
        ) from exc
    if len(matches) > 1:
        raise _error(
            "runtime_snapshot_owned_path_changed",
            "runtime snapshot owned directory has ambiguous names",
            phase="cleanup",
        )
    return matches[0] if matches else None


def _resolve_owned_entry_name(
    parent_fd: int,
    preferred_name: str,
    descriptor: int,
    expected: _Identity,
) -> str | None:
    opened = _identity_from_stat(os.fstat(descriptor))
    if not _bound_identity_matches(opened, expected):
        raise _error(
            "runtime_snapshot_owned_path_changed",
            "runtime snapshot owned directory descriptor changed",
            phase="cleanup",
        )
    try:
        preferred = _identity_from_stat(
            os.stat(preferred_name, dir_fd=parent_fd, follow_symlinks=False)
        )
    except FileNotFoundError:
        preferred = None
    except OSError as exc:
        raise _error(
            "runtime_snapshot_cleanup_failed",
            "runtime snapshot owned directory name could not be inspected",
            phase="cleanup",
        ) from exc
    if preferred is not None and _bound_identity_matches(preferred, expected):
        return preferred_name
    return _find_owned_entry_name(parent_fd, expected)


def _cleanup_owned_tree(
    parent_fd: int | None,
    name: str | None,
    descriptor: int | None,
    identity: _Identity | None,
) -> None:
    if parent_fd is None or name is None or descriptor is None or identity is None:
        return
    if identity.kind != "directory":
        raise _error(
            "runtime_snapshot_cleanup_failed",
            "runtime snapshot cleanup target is not a directory",
            phase="cleanup",
        )
    resolved_name = _resolve_owned_entry_name(parent_fd, name, descriptor, identity)
    relocated = resolved_name != name
    try:
        _clear_owned_directory(descriptor)
        current_name = _resolve_owned_entry_name(parent_fd, name, descriptor, identity)
        relocated = relocated or current_name != name
        if current_name is not None:
            os.rmdir(current_name, dir_fd=parent_fd)
    except OSError as exc:
        raise _error(
            "runtime_snapshot_cleanup_failed",
            "runtime snapshot owned directory could not be removed",
            phase="cleanup",
        ) from exc
    if resolved_name is None or current_name is None or relocated:
        raise _error(
            "runtime_snapshot_owned_path_changed",
            "runtime snapshot owned directory moved during cleanup",
            phase="cleanup",
        )


def _cleanup_before_publication(
    output_fd: int | None,
    sandbox_name: str | None,
    sandbox_fd: int | None,
    sandbox_identity: _Identity | None,
    staging_name: str | None,
    staging_fd: int | None,
    staging_identity: _Identity | None,
) -> None:
    errors: list[RuntimeSnapshotError] = []
    for name, descriptor, identity in (
        (sandbox_name, sandbox_fd, sandbox_identity),
        (staging_name, staging_fd, staging_identity),
    ):
        try:
            _cleanup_owned_tree(output_fd, name, descriptor, identity)
        except RuntimeSnapshotError as exc:
            errors.append(exc)
    if errors:
        raise errors[0]


def _binary_identity(path: Path) -> _BinaryIdentity:
    try:
        metadata = os.stat(path)
    except OSError as exc:
        raise _error(
            "runtime_snapshot_opencode_unavailable",
            "OpenCode validator binary is unavailable",
            phase="application_validation",
        ) from exc
    if not stat.S_ISREG(metadata.st_mode) or not os.access(path, os.X_OK):
        raise _error(
            "runtime_snapshot_opencode_unavailable",
            "OpenCode validator binary is not an executable regular file",
            phase="application_validation",
        )
    return _BinaryIdentity(
        path=path,
        dev=int(metadata.st_dev),
        ino=int(metadata.st_ino),
        mode=stat.S_IMODE(metadata.st_mode),
        uid=int(metadata.st_uid),
        size=int(metadata.st_size),
        mtime_ns=int(metadata.st_mtime_ns),
    )


def _resolve_opencode_binary() -> _BinaryIdentity:
    spec = os.environ.get("MY_OPENCODE_RUNTIME_SNAPSHOT_OPENCODE_BIN", "opencode").strip()
    candidate = shutil.which(spec) if os.path.sep not in spec else spec
    if not candidate:
        raise _error(
            "runtime_snapshot_opencode_unavailable",
            "OpenCode validator binary was not found",
            phase="application_validation",
        )
    try:
        resolved = Path(candidate).expanduser().resolve(strict=True)
    except OSError as exc:
        raise _error(
            "runtime_snapshot_opencode_unavailable",
            "OpenCode validator binary could not be resolved",
            phase="application_validation",
        ) from exc
    return _binary_identity(resolved)


def _binary_identity_matches(left: _BinaryIdentity, right: _BinaryIdentity) -> bool:
    return (
        left.path == right.path
        and left.dev == right.dev
        and left.ino == right.ino
        and left.mode == right.mode
        and left.uid == right.uid
        and left.size == right.size
        and left.mtime_ns == right.mtime_ns
    )


def _open_source_database(
    db_path: Path,
    expected_identity: _Identity,
) -> tuple[sqlite3.Connection, dict[str, Any], dict[str, SidecarInspection]]:
    try:
        connection = sqlite3.connect(
            f"{Path(os.path.abspath(os.fspath(db_path))).as_uri()}?mode=ro",
            uri=True,
            timeout=5.0,
        )
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA query_only = ON")
        query_only = connection.execute("PRAGMA query_only").fetchone()
        if query_only is None or int(query_only[0]) != 1:
            raise _error(
                "runtime_snapshot_query_only_unavailable",
                "runtime snapshot source query-only mode could not be verified",
                phase="source_open",
            )
        observations = _inspect_source(db_path)
        _require_stable_database_identity(observations, expected_identity)
        metadata = {
            "page_count": int(connection.execute("PRAGMA page_count").fetchone()[0]),
            "page_size": int(connection.execute("PRAGMA page_size").fetchone()[0]),
            "journal_mode": str(connection.execute("PRAGMA journal_mode").fetchone()[0]),
            "encoding": str(connection.execute("PRAGMA encoding").fetchone()[0]),
            "application_id": int(
                connection.execute("PRAGMA application_id").fetchone()[0]
            ),
            "user_version": int(connection.execute("PRAGMA user_version").fetchone()[0]),
            "schema_version": int(
                connection.execute("PRAGMA schema_version").fetchone()[0]
            ),
            "sqlite_version": str(
                connection.execute("SELECT sqlite_version()").fetchone()[0]
            ),
            "query_only": True,
        }
        metadata["logical_bytes"] = metadata["page_count"] * metadata["page_size"]
        return connection, metadata, observations
    except RuntimeSnapshotError:
        if "connection" in locals():
            connection.close()
        raise
    except sqlite3.Error as exc:
        if "connection" in locals():
            connection.close()
        raise _error(
            "runtime_snapshot_source_open_failed",
            "runtime snapshot source database could not be opened read-only",
            phase="source_open",
        ) from exc


def _capacity_reserve(estimated_bytes: int) -> int:
    return max(SNAPSHOT_MIN_RESERVE_BYTES, (estimated_bytes + 9) // 10)


def _capacity_preflight(output_root: Path, estimated_bytes: int) -> dict[str, int]:
    available = int(shutil.disk_usage(output_root).free)
    reserve = _capacity_reserve(estimated_bytes)
    required = (
        (2 * estimated_bytes) + reserve + SNAPSHOT_METADATA_ALLOWANCE_BYTES
    )
    if available < required:
        raise _error(
            "runtime_snapshot_insufficient_capacity",
            "runtime snapshot destination lacks capacity for output and validation copy",
            phase="capacity",
        )
    return {
        "estimated_snapshot_bytes": estimated_bytes,
        "available_bytes_before_backup": available,
        "reserve_bytes": reserve,
        "metadata_allowance_bytes": SNAPSHOT_METADATA_ALLOWANCE_BYTES,
        "required_bytes": required,
    }


def _remaining_sqlite_timeout(
    deadline: float,
    *,
    reason_code: str,
    message: str,
    phase: str,
) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _error(reason_code, message, phase=phase)
    return min(5.0, max(0.001, remaining))


def _run_online_backup(
    source: sqlite3.Connection,
    destination_fd: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + SNAPSHOT_BACKUP_TIMEOUT_SECONDS
    started = time.perf_counter()
    progress_calls = 0
    status_counts: Counter[str] = Counter()
    final_remaining: int | None = None
    final_page_count: int | None = None

    def progress(status: int, remaining: int, page_count: int) -> None:
        nonlocal progress_calls, final_remaining, final_page_count
        progress_calls += 1
        status_counts[str(status)] += 1
        final_remaining = int(remaining)
        final_page_count = int(page_count)
        if time.monotonic() >= deadline:
            raise _error(
                "runtime_snapshot_backup_timeout",
                "runtime snapshot online backup exceeded its deadline",
                phase="backup",
            )

    destination: sqlite3.Connection | None = None
    try:
        source_timeout = _remaining_sqlite_timeout(
            deadline,
            reason_code="runtime_snapshot_backup_timeout",
            message="runtime snapshot online backup exceeded its deadline",
            phase="backup",
        )
        source.execute(
            f"PRAGMA busy_timeout = {max(1, int(source_timeout * 1000))}"
        )
        timeout = _remaining_sqlite_timeout(
            deadline,
            reason_code="runtime_snapshot_backup_timeout",
            message="runtime snapshot online backup exceeded its deadline",
            phase="backup",
        )
        destination = sqlite3.connect(
            f"file:///dev/fd/{destination_fd}?mode=rw",
            uri=True,
            timeout=timeout,
        )
        busy_timeout_ms = max(1, int(timeout * 1000))
        destination.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
        journal_mode = destination.execute("PRAGMA journal_mode = OFF").fetchone()
        if journal_mode is None or str(journal_mode[0]).lower() != "off":
            raise _error(
                "runtime_snapshot_backup_binding_failed",
                "runtime snapshot descriptor-bound destination could not disable journaling",
                phase="backup",
            )
        _remaining_sqlite_timeout(
            deadline,
            reason_code="runtime_snapshot_backup_timeout",
            message="runtime snapshot online backup exceeded its deadline",
            phase="backup",
        )
        source.backup(
            destination,
            pages=SNAPSHOT_BACKUP_PAGES,
            progress=progress,
            sleep=SNAPSHOT_BACKUP_SLEEP_SECONDS,
        )
        _remaining_sqlite_timeout(
            deadline,
            reason_code="runtime_snapshot_backup_timeout",
            message="runtime snapshot online backup exceeded its deadline",
            phase="backup",
        )
    except RuntimeSnapshotError:
        raise
    except sqlite3.Error as exc:
        if time.monotonic() >= deadline:
            raise _error(
                "runtime_snapshot_backup_timeout",
                "runtime snapshot online backup exceeded its deadline",
                phase="backup",
            ) from exc
        raise _error(
            "runtime_snapshot_backup_failed",
            "runtime snapshot online backup failed",
            phase="backup",
        ) from exc
    finally:
        if destination is not None:
            destination.close()
    return {
        "api": "sqlite_online_backup",
        "destination_binding": "open_file_descriptor",
        "pages_per_step": SNAPSHOT_BACKUP_PAGES,
        "sleep_seconds": SNAPSHOT_BACKUP_SLEEP_SECONDS,
        "timeout_seconds": SNAPSHOT_BACKUP_TIMEOUT_SECONDS,
        "progress_calls": progress_calls,
        "status_counts": dict(status_counts),
        "final_remaining_pages": final_remaining,
        "final_page_count": final_page_count,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def _validate_snapshot_database(descriptor: int, check_kind: str) -> dict[str, Any]:
    deadline = time.monotonic() + SNAPSHOT_CHECK_TIMEOUT_SECONDS
    timed_out = False
    started = time.perf_counter()

    def progress() -> int:
        nonlocal timed_out
        if time.monotonic() < deadline:
            return 0
        timed_out = True
        return 1

    connection: sqlite3.Connection | None = None
    try:
        timeout = _remaining_sqlite_timeout(
            deadline,
            reason_code="runtime_snapshot_check_timeout",
            message="runtime snapshot consistency check exceeded its deadline",
            phase="integrity_check",
        )
        connection = sqlite3.connect(
            f"file:///dev/fd/{descriptor}?mode=ro&immutable=1",
            uri=True,
            timeout=timeout,
        )
        connection.execute(f"PRAGMA busy_timeout = {max(1, int(timeout * 1000))}")
        connection.execute("PRAGMA query_only = ON")
        _remaining_sqlite_timeout(
            deadline,
            reason_code="runtime_snapshot_check_timeout",
            message="runtime snapshot consistency check exceeded its deadline",
            phase="integrity_check",
        )
        connection.set_progress_handler(progress, 1000)
        rows = connection.execute(f"PRAGMA {check_kind}").fetchall()
        if rows != [("ok",)]:
            raise _error(
                "runtime_snapshot_integrity_failed",
                "runtime snapshot consistency check did not return exactly one ok row",
                phase="integrity_check",
            )
        metadata = {
            "page_count": int(connection.execute("PRAGMA page_count").fetchone()[0]),
            "page_size": int(connection.execute("PRAGMA page_size").fetchone()[0]),
            "application_id": int(
                connection.execute("PRAGMA application_id").fetchone()[0]
            ),
            "user_version": int(connection.execute("PRAGMA user_version").fetchone()[0]),
            "schema_version": int(
                connection.execute("PRAGMA schema_version").fetchone()[0]
            ),
            "encoding": str(connection.execute("PRAGMA encoding").fetchone()[0]),
            "sqlite_version": str(
                connection.execute("SELECT sqlite_version()").fetchone()[0]
            ),
        }
    except RuntimeSnapshotError:
        raise
    except sqlite3.Error as exc:
        if timed_out or time.monotonic() >= deadline:
            raise _error(
                "runtime_snapshot_check_timeout",
                "runtime snapshot consistency check exceeded its deadline",
                phase="integrity_check",
            ) from exc
        raise _error(
            "runtime_snapshot_integrity_failed",
            "runtime snapshot consistency check failed",
            phase="integrity_check",
        ) from exc
    finally:
        if connection is not None:
            try:
                connection.set_progress_handler(None, 0)
            finally:
                connection.close()
    return {
        "check": check_kind,
        "result": "ok",
        "timeout_seconds": SNAPSHOT_CHECK_TIMEOUT_SECONDS,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "database": metadata,
    }


def _create_sandbox_layout(
    sandbox: Path,
    sandbox_fd: int,
) -> tuple[dict[str, Path], int]:
    names = ("home", "config", "cache", "state", "data", "tmp")
    paths: dict[str, Path] = {}
    opencode_fd: int | None = None
    try:
        for name in names:
            os.mkdir(name, PRIVATE_DIRECTORY_MODE, dir_fd=sandbox_fd)
            metadata = os.stat(name, dir_fd=sandbox_fd, follow_symlinks=False)
            identity = _identity_from_stat(metadata)
            if (
                identity.kind != "directory"
                or identity.uid != os.geteuid()
                or identity.mode != PRIVATE_DIRECTORY_MODE
            ):
                raise _error(
                    "runtime_snapshot_sandbox_failed",
                    "runtime snapshot validation sandbox is unsafe",
                    phase="application_validation",
                )
            paths[name] = sandbox / name
        data_fd = os.open(
            "data",
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=sandbox_fd,
        )
        try:
            os.mkdir("opencode", PRIVATE_DIRECTORY_MODE, dir_fd=data_fd)
            metadata = os.stat("opencode", dir_fd=data_fd, follow_symlinks=False)
            opencode_fd = os.open(
                "opencode",
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=data_fd,
            )
            opened = os.fstat(opencode_fd)
        finally:
            os.close(data_fd)
    except RuntimeSnapshotError:
        if opencode_fd is not None:
            os.close(opencode_fd)
        raise
    except OSError as exc:
        if opencode_fd is not None:
            os.close(opencode_fd)
        raise _error(
            "runtime_snapshot_sandbox_failed",
            "runtime snapshot validation sandbox could not be prepared",
            phase="application_validation",
        ) from exc
    opencode_identity = _identity_from_stat(metadata)
    if (
        opencode_identity.kind != "directory"
        or opencode_identity.uid != os.geteuid()
        or opencode_identity.mode != PRIVATE_DIRECTORY_MODE
        or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
    ):
        assert opencode_fd is not None
        os.close(opencode_fd)
        raise _error(
            "runtime_snapshot_sandbox_failed",
            "runtime snapshot application data directory is unsafe",
            phase="application_validation",
        )
    paths["opencode_data"] = paths["data"] / "opencode"
    assert opencode_fd is not None
    return paths, opencode_fd


def _copy_and_hash(
    source_fd: int,
    destination_fd: int,
    *,
    expected_source: _Identity,
) -> dict[str, Any]:
    deadline = time.monotonic() + SNAPSHOT_COPY_TIMEOUT_SECONDS
    started = time.perf_counter()
    digest = hashlib.sha256()
    copied = 0
    try:
        opened_source = _identity_from_stat(os.fstat(source_fd))
        if not _strict_file_identity_matches(opened_source, expected_source):
            raise _error(
                "runtime_snapshot_artifact_changed",
                "runtime snapshot artifact changed before hashing",
                phase="copy_hash",
            )
        os.lseek(source_fd, 0, os.SEEK_SET)
        os.ftruncate(destination_fd, 0)
        os.lseek(destination_fd, 0, os.SEEK_SET)
        while True:
            if time.monotonic() >= deadline:
                raise _error(
                    "runtime_snapshot_copy_timeout",
                    "runtime snapshot validation copy exceeded its deadline",
                    phase="copy_hash",
                )
            chunk = os.read(source_fd, SNAPSHOT_COPY_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            offset = 0
            while offset < len(chunk):
                offset += os.write(destination_fd, chunk[offset:])
            copied += len(chunk)
        os.fsync(destination_fd)
        final_source = _identity_from_stat(os.fstat(source_fd))
        if not _strict_file_identity_matches(final_source, expected_source):
            raise _error(
                "runtime_snapshot_artifact_changed",
                "runtime snapshot artifact changed while hashing",
                phase="copy_hash",
            )
    except RuntimeSnapshotError:
        raise
    except OSError as exc:
        raise _error(
            "runtime_snapshot_copy_failed",
            "runtime snapshot validation copy failed",
            phase="copy_hash",
        ) from exc
    return {
        "bytes": copied,
        "sha256": digest.hexdigest(),
        "timeout_seconds": SNAPSHOT_COPY_TIMEOUT_SECONDS,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def _isolated_opencode_env(layout: Mapping[str, Path]) -> dict[str, str]:
    environment: dict[str, str] = {}
    for key in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR"):
        value = os.environ.get(key)
        if value:
            environment[key] = value
    environment.update(
        {
            "HOME": str(layout["home"]),
            "XDG_CONFIG_HOME": str(layout["config"]),
            "XDG_CACHE_HOME": str(layout["cache"]),
            "XDG_DATA_HOME": str(layout["data"]),
            "XDG_STATE_HOME": str(layout["state"]),
            "TMPDIR": str(layout["tmp"]),
            "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
            "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
            "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
            "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS": "1",
            "OPENCODE_CONFIG_CONTENT": '{"$schema":"https://opencode.ai/config.json","plugin":[]}',
        }
    )
    return environment


def _run_application_validation(
    binary: _BinaryIdentity,
    layout: Mapping[str, Path],
) -> dict[str, Any]:
    environment = _isolated_opencode_env(layout)
    started = time.perf_counter()
    deadline = time.monotonic() + SNAPSHOT_APPLICATION_TIMEOUT_SECONDS

    def remaining_timeout() -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _error(
                "runtime_snapshot_application_timeout",
                "OpenCode disposable snapshot validation exceeded its deadline",
                phase="application_validation",
            )
        return remaining

    try:
        version = subprocess.run(
            [str(binary.path), "--version"],
            cwd=layout["home"],
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=remaining_timeout(),
            check=False,
        )
        query = subprocess.run(
            [
                str(binary.path),
                "--pure",
                "db",
                "PRAGMA schema_version;",
                "--format",
                "json",
            ],
            cwd=layout["home"],
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=remaining_timeout(),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise _error(
            "runtime_snapshot_application_timeout",
            "OpenCode disposable snapshot validation exceeded its deadline",
            phase="application_validation",
        ) from exc
    if version.returncode != 0 or query.returncode != 0:
        raise _error(
            "runtime_snapshot_application_open_failed",
            "OpenCode could not open the disposable runtime snapshot",
            phase="application_validation",
        )
    version_text = version.stdout.strip()
    if not version_text or len(version_text.encode("utf-8")) > 256:
        raise _error(
            "runtime_snapshot_application_version_invalid",
            "OpenCode validator returned an invalid version",
            phase="application_validation",
        )
    try:
        payload = json.loads(query.stdout)
    except json.JSONDecodeError as exc:
        raise _error(
            "runtime_snapshot_application_output_invalid",
            "OpenCode disposable snapshot validation returned invalid JSON",
            phase="application_validation",
        ) from exc
    if (
        not isinstance(payload, list)
        or len(payload) != 1
        or not isinstance(payload[0], dict)
        or not isinstance(payload[0].get("schema_version"), int)
    ):
        raise _error(
            "runtime_snapshot_application_output_invalid",
            "OpenCode disposable snapshot validation returned an unexpected schema result",
            phase="application_validation",
        )
    after = _binary_identity(binary.path)
    if not _binary_identity_matches(binary, after):
        raise _error(
            "runtime_snapshot_opencode_changed",
            "OpenCode validator binary changed during snapshot validation",
            phase="application_validation",
        )
    return {
        "result": "readable",
        "opencode_version": version_text,
        "binary": binary.payload(),
        "query": "PRAGMA schema_version;",
        "schema_version": int(payload[0]["schema_version"]),
        "timeout_seconds": SNAPSHOT_APPLICATION_TIMEOUT_SECONDS,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "claim": "readability_only_not_restoration",
    }


def _fsync_file(descriptor: int) -> None:
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise _error(
            "runtime_snapshot_fsync_failed",
            "runtime snapshot artifact could not be synchronized",
            phase="publication",
        ) from exc


def _fsync_owned_directory(descriptor: int) -> None:
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise _error(
            "runtime_snapshot_fsync_failed",
            "runtime snapshot staging directory could not be synchronized",
            phase="publication",
        ) from exc


def _fsync_output_directory(descriptor: int) -> None:
    os.fsync(descriptor)


def _write_manifest_at(
    staging_fd: int,
    staging_path: Path,
    payload: Mapping[str, Any],
) -> tuple[Path, int, _Identity]:
    try:
        encoded = (json.dumps(dict(payload), indent=2) + "\n").encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise _error(
            "runtime_snapshot_manifest_invalid",
            "runtime snapshot manifest could not be serialized",
            phase="publication",
        ) from exc
    if len(encoded) > SNAPSHOT_MANIFEST_MAX_BYTES:
        raise _error(
            "runtime_snapshot_manifest_too_large",
            "runtime snapshot manifest exceeds its size limit",
            phase="publication",
        )
    path, descriptor, initial = _create_private_file_at(
        staging_fd,
        staging_path,
        SNAPSHOT_MANIFEST_NAME,
    )
    try:
        written = 0
        while written < len(encoded):
            count = os.write(descriptor, encoded[written:])
            if count <= 0:
                raise OSError("manifest write made no progress")
            written += count
        os.fsync(descriptor)
        _verify_file_entry(
            staging_fd,
            SNAPSHOT_MANIFEST_NAME,
            descriptor,
            initial,
            phase="publication",
            strict=False,
        )
        identity = _identity_from_stat(os.fstat(descriptor))
        _verify_file_entry(
            staging_fd,
            SNAPSHOT_MANIFEST_NAME,
            descriptor,
            identity,
            phase="publication",
            strict=True,
        )
    except RuntimeSnapshotError:
        os.close(descriptor)
        raise
    except OSError as exc:
        os.close(descriptor)
        raise _error(
            "runtime_snapshot_manifest_write_failed",
            "runtime snapshot manifest could not be written",
            phase="publication",
        ) from exc
    return path, descriptor, identity


def _rename_exclusive(
    source_dir_fd: int,
    source_name: str,
    target_dir_fd: int,
    target_name: str,
) -> None:
    for name in (source_name, target_name):
        if not name or name in {".", ".."} or "/" in name or "\x00" in name:
            raise _error(
                "runtime_snapshot_publish_failed",
                "runtime snapshot publication name is unsafe",
                phase="publication",
            )
    libc = ctypes.CDLL(None, use_errno=True)
    flags: int
    try:
        if sys.platform == "darwin":
            function = libc.renameatx_np
            flags = 0x00000004  # RENAME_EXCL
        elif sys.platform.startswith("linux"):
            function = libc.renameat2
            flags = 0x00000001  # RENAME_NOREPLACE
        else:
            raise AttributeError("exclusive rename is unsupported")
    except AttributeError as exc:
        raise _error(
            "runtime_snapshot_publish_unsupported",
            "atomic no-replace runtime snapshot publication is unavailable",
            phase="publication",
        ) from exc
    function.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_int
    ctypes.set_errno(0)
    result = function(
        source_dir_fd,
        os.fsencode(source_name),
        target_dir_fd,
        os.fsencode(target_name),
        flags,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        reason_code = "runtime_snapshot_name_collision"
    elif error_number in {
        errno.EINVAL,
        errno.ENOSYS,
        errno.ENOTSUP,
        getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
    }:
        reason_code = "runtime_snapshot_publish_unsupported"
    else:
        reason_code = "runtime_snapshot_publish_failed"
    raise _error(
        reason_code,
        "runtime snapshot bundle could not be published without replacement",
        phase="publication",
    ) from OSError(error_number, os.strerror(error_number), target_name)


def _bundle_inventory(
    staging_fd: int,
    snapshot_fd: int,
    snapshot_identity: _Identity,
    manifest_fd: int,
    manifest_identity: _Identity,
) -> None:
    try:
        with os.scandir(staging_fd) as entries:
            names = sorted(item.name for item in entries)
    except OSError as exc:
        raise _error(
            "runtime_snapshot_bundle_invalid",
            "runtime snapshot staging bundle could not be inventoried",
            phase="publication",
        ) from exc
    if names != [SNAPSHOT_MANIFEST_NAME, SNAPSHOT_FILE_NAME]:
        raise _error(
            "runtime_snapshot_bundle_invalid",
            "runtime snapshot bundle contains unexpected files",
            phase="publication",
        )
    _verify_file_entry(
        staging_fd,
        SNAPSHOT_FILE_NAME,
        snapshot_fd,
        snapshot_identity,
        phase="publication",
        strict=True,
    )
    _verify_file_entry(
        staging_fd,
        SNAPSHOT_MANIFEST_NAME,
        manifest_fd,
        manifest_identity,
        phase="publication",
        strict=True,
    )


def create_runtime_history_snapshot(
    db_path: Path,
    output_dir: Path,
    *,
    full_integrity_check: bool = False,
) -> dict[str, Any]:
    operation_started = time.perf_counter()
    started_at = datetime.now(UTC)
    source_initial = _inspect_source(db_path)
    source_db_snapshot = source_initial["runtime_db"].snapshot
    assert source_db_snapshot is not None
    source_identity = _identity_from_snapshot(source_db_snapshot, kind="file")
    canonical_db_path = source_initial["runtime_db"].path
    binary = _resolve_opencode_binary()

    output_root: Path | None = None
    output_fd: int | None = None
    output_identity: _Identity | None = None
    staging_name: str | None = None
    staging_path: Path | None = None
    staging_fd: int | None = None
    staging_identity: _Identity | None = None
    sandbox_name: str | None = None
    sandbox_path: Path | None = None
    sandbox_fd: int | None = None
    sandbox_identity: _Identity | None = None
    snapshot_fd: int | None = None
    disposable_parent_fd: int | None = None
    disposable_fd: int | None = None
    manifest_fd: int | None = None
    final_bundle: Path | None = None
    committed = False
    source: sqlite3.Connection | None = None

    try:
        output_root, output_fd, output_identity = _prepare_private_output_root(output_dir)
        source, source_metadata, source_after_open = _open_source_database(
            canonical_db_path, source_identity
        )
        capacity = _capacity_preflight(
            output_root, int(source_metadata["logical_bytes"])
        )
        stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
        snapshot_id = f"{stamp}-{uuid.uuid4().hex}"
        final_name = f"runtime-history-{snapshot_id}"
        staging_name = f".{final_name}.partial"
        sandbox_name = f".{final_name}.validation"
        try:
            os.stat(final_name, dir_fd=output_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise _error(
                "runtime_snapshot_name_collision",
                "runtime snapshot final bundle name already exists",
                phase="staging",
            )
        staging_path, staging_fd, staging_identity = _mkdir_owned(
            output_fd, output_root, staging_name
        )
        sandbox_path, sandbox_fd, sandbox_identity = _mkdir_owned(
            output_fd, output_root, sandbox_name
        )
        _, snapshot_fd, snapshot_identity = _create_private_file_at(
            staging_fd,
            staging_path,
            SNAPSHOT_FILE_NAME,
        )

        backup = _run_online_backup(source, snapshot_fd)
        _verify_file_entry(
            staging_fd,
            SNAPSHOT_FILE_NAME,
            snapshot_fd,
            snapshot_identity,
            phase="backup",
            strict=False,
        )
        snapshot_identity = _identity_from_stat(os.fstat(snapshot_fd))
        source_after_backup = _inspect_source(canonical_db_path)
        _require_stable_database_identity(source_after_backup, source_identity)
        source.close()
        source = None
        source_after_close = _inspect_source(canonical_db_path)
        _require_stable_database_identity(source_after_close, source_identity)

        check_kind = "integrity_check" if full_integrity_check else "quick_check"
        integrity = _validate_snapshot_database(snapshot_fd, check_kind)
        snapshot_identity = _verify_file_entry(
            staging_fd,
            SNAPSHOT_FILE_NAME,
            snapshot_fd,
            snapshot_identity,
            phase="integrity_check",
            strict=True,
        )
        if (
            snapshot_identity.kind != "file"
            or snapshot_identity.mode != PRIVATE_FILE_MODE
            or snapshot_identity.uid != os.geteuid()
            or snapshot_identity.nlink != 1
        ):
            raise _error(
                "runtime_snapshot_artifact_changed",
                "runtime snapshot artifact identity is unsafe after backup",
                phase="integrity_check",
            )
        actual_bytes = snapshot_identity.size
        free_before_copy = int(shutil.disk_usage(output_root).free)
        actual_reserve = _capacity_reserve(actual_bytes)
        required_before_copy = (
            actual_bytes + actual_reserve + SNAPSHOT_METADATA_ALLOWANCE_BYTES
        )
        if free_before_copy < required_before_copy:
            raise _error(
                "runtime_snapshot_insufficient_capacity",
                "runtime snapshot destination lacks capacity for disposable validation",
                phase="capacity",
            )
        capacity.update(
            {
                "actual_snapshot_bytes": actual_bytes,
                "available_bytes_before_copy": free_before_copy,
                "required_bytes_before_copy": required_before_copy,
            }
        )

        layout, disposable_parent_fd = _create_sandbox_layout(
            sandbox_path,
            sandbox_fd,
        )
        _, disposable_fd, disposable_identity = _create_private_file_at(
            disposable_parent_fd,
            layout["opencode_data"],
            "opencode.db",
        )
        artifact = _copy_and_hash(
            snapshot_fd,
            disposable_fd,
            expected_source=snapshot_identity,
        )
        disposable_identity = _identity_from_stat(os.fstat(disposable_fd))
        _verify_file_entry(
            disposable_parent_fd,
            "opencode.db",
            disposable_fd,
            disposable_identity,
            phase="application_validation",
            strict=True,
        )
        _verify_owned_entry(
            output_fd,
            sandbox_name,
            sandbox_fd,
            sandbox_identity,
            phase="application_validation",
        )
        application = _run_application_validation(binary, layout)
        _verify_file_entry(
            disposable_parent_fd,
            "opencode.db",
            disposable_fd,
            disposable_identity,
            phase="application_validation",
            strict=True,
        )
        os.close(disposable_fd)
        disposable_fd = None
        os.close(disposable_parent_fd)
        disposable_parent_fd = None
        _cleanup_owned_tree(
            output_fd,
            sandbox_name,
            sandbox_fd,
            sandbox_identity,
        )
        os.close(sandbox_fd)
        sandbox_fd = None
        sandbox_name = None
        sandbox_path = None
        sandbox_identity = None

        completed_at = datetime.now(UTC)
        manifest = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "kind": SNAPSHOT_KIND,
            "snapshot_id": snapshot_id,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "source": {
                "path": str(canonical_db_path),
                "identity": source_identity.payload(),
                "metadata": source_metadata,
                "initial_observations": _source_observation_payload(source_initial),
                "after_open_observations": _source_observation_payload(
                    source_after_open
                ),
                "after_backup_observations": _source_observation_payload(
                    source_after_backup
                ),
                "after_close_observations": _source_observation_payload(
                    source_after_close
                ),
            },
            "artifact": {
                "relative_path": SNAPSHOT_FILE_NAME,
                "bytes": artifact["bytes"],
                "sha256": artifact["sha256"],
                "mode": PRIVATE_FILE_MODE,
            },
            "backup": backup,
            "integrity": integrity,
            "application_validation": application,
            "capacity": capacity,
            "runtime": {
                "python_version": sys.version.split()[0],
                "python_sqlite_version": sqlite3.sqlite_version,
            },
            "limitations": [
                "consistent_completed_online_backup_not_invocation_start_state",
                "same_version_open_proves_readability_not_restoration",
                "same_uid_swap_and_restore_not_excluded_by_path_based_sqlite_api",
                "wal_reader_may_update_transient_source_shm_coordination_state",
            ],
        }
        _, manifest_fd, manifest_identity = _write_manifest_at(
            staging_fd,
            staging_path,
            manifest,
        )
        _bundle_inventory(
            staging_fd,
            snapshot_fd,
            snapshot_identity,
            manifest_fd,
            manifest_identity,
        )
        _fsync_file(snapshot_fd)
        _fsync_file(manifest_fd)
        _fsync_owned_directory(staging_fd)
        _bundle_inventory(
            staging_fd,
            snapshot_fd,
            snapshot_identity,
            manifest_fd,
            manifest_identity,
        )
        _verify_owned_entry(
            output_fd,
            staging_name,
            staging_fd,
            staging_identity,
            phase="publication",
        )
        _verify_output_root(output_root, output_fd, output_identity)
        try:
            _rename_exclusive(
                output_fd,
                staging_name,
                output_fd,
                final_name,
            )
        except RuntimeSnapshotError:
            raise
        except OSError as exc:
            raise _error(
                "runtime_snapshot_publish_failed",
                "runtime snapshot bundle could not be published",
                phase="publication",
            ) from exc
        committed = True
        final_bundle = output_root / final_name
        staging_name = None
        staging_path = None
        try:
            final_metadata = _identity_from_stat(
                os.stat(final_name, dir_fd=output_fd, follow_symlinks=False)
            )
            opened_final = _identity_from_stat(os.fstat(staging_fd))
            if not _bound_identity_matches(
                final_metadata, staging_identity
            ) or not _bound_identity_matches(opened_final, staging_identity):
                raise _error(
                    "runtime_snapshot_publish_uncertain",
                    "published runtime snapshot bundle identity is uncertain",
                    phase="publication",
                    committed=True,
                    durability="uncertain",
                    bundle_path=final_bundle,
                )
            _fsync_output_directory(output_fd)
            _verify_output_root(output_root, output_fd, output_identity)
        except RuntimeSnapshotError:
            raise
        except OSError as exc:
            raise _error(
                "runtime_snapshot_publish_uncertain",
                "published runtime snapshot durability could not be confirmed",
                phase="publication",
                committed=True,
                durability="uncertain",
                bundle_path=final_bundle,
            ) from exc
        return {
            "result": "PASS",
            "snapshot_id": snapshot_id,
            "bundle_path": str(final_bundle),
            "snapshot_path": str(final_bundle / SNAPSHOT_FILE_NAME),
            "manifest_path": str(final_bundle / SNAPSHOT_MANIFEST_NAME),
            "bytes": artifact["bytes"],
            "sha256": artifact["sha256"],
            "check": check_kind,
            "check_result": "ok",
            "application_readable": True,
            "opencode_version": application["opencode_version"],
            "duration_ms": round((time.perf_counter() - operation_started) * 1000, 2),
            "durability": "synced",
            "limitations": manifest["limitations"],
        }
    except RuntimeSnapshotError as exc:
        if committed and not exc.committed:
            raise _error(
                exc.reason_code,
                str(exc),
                phase=exc.phase,
                committed=True,
                durability="uncertain",
                bundle_path=final_bundle,
            ) from exc
        if not committed:
            try:
                _cleanup_before_publication(
                    output_fd,
                    sandbox_name,
                    sandbox_fd,
                    sandbox_identity,
                    staging_name,
                    staging_fd,
                    staging_identity,
                )
            except RuntimeSnapshotError as cleanup_exc:
                raise cleanup_exc from exc
        raise
    except (OSError, sqlite3.Error, SidecarSecurityError) as exc:
        if not committed:
            _cleanup_before_publication(
                output_fd,
                sandbox_name,
                sandbox_fd,
                sandbox_identity,
                staging_name,
                staging_fd,
                staging_identity,
            )
        raise _error(
            "runtime_snapshot_failed",
            "runtime snapshot creation failed",
            phase="snapshot",
            committed=committed,
            durability="uncertain" if committed else "not_committed",
            bundle_path=final_bundle,
        ) from exc
    finally:
        if source is not None:
            source.close()
        for descriptor in (
            manifest_fd,
            disposable_fd,
            disposable_parent_fd,
            snapshot_fd,
            sandbox_fd,
            staging_fd,
        ):
            if descriptor is not None:
                os.close(descriptor)
        if output_fd is not None:
            os.close(output_fd)
