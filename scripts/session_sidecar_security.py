from __future__ import annotations

import errno
import json
import os
import stat
import sys
import threading
import time
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterator, Mapping


PRIVATE_FILE_MODE = 0o600
PRIVATE_DIRECTORY_MODE = 0o700
SUPPORTED_PLATFORMS = {"darwin", "linux"}
_EXPECTED_UNSET = object()
_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.Lock] = {}


class SidecarSecurityError(RuntimeError):
    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        phase: str,
        committed: bool = False,
        durability: str = "not_committed",
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.phase = phase
        self.committed = committed
        self.durability = durability


@dataclass(frozen=True)
class SidecarSnapshot:
    path: Path
    dev: int
    ino: int
    mode: int
    uid: int
    nlink: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True)
class SecureBytes:
    data: bytes
    snapshot: SidecarSnapshot


@dataclass(frozen=True)
class SecureJson:
    payload: dict[str, Any]
    snapshot: SidecarSnapshot


@dataclass(frozen=True)
class PublicationResult:
    committed: bool
    durability: str
    snapshot: SidecarSnapshot


@dataclass(frozen=True)
class SidecarInspection:
    target: str
    path: Path
    state: str
    exists: bool
    before_mode: int | None
    after_mode: int | None
    reason_code: str | None
    changed: bool = False
    snapshot: SidecarSnapshot | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "path": str(self.path),
            "state": self.state,
            "exists": self.exists,
            "before_mode": self.before_mode,
            "after_mode": self.after_mode,
            "reason_code": self.reason_code,
            "changed": self.changed,
        }


@dataclass(frozen=True)
class _ParentPlan:
    target: Path
    parent: Path
    existing: Path
    missing_parts: tuple[str, ...]


@dataclass
class _Authority:
    target: Path
    parent: Path
    name: str
    parent_fd: int
    parent_dev: int
    parent_ino: int


@dataclass(frozen=True)
class _AliasCandidate:
    role: str
    path: Path
    canonical_key: str
    identity: tuple[int, int] | None
    metadata: os.stat_result | None


def _error(
    reason_code: str,
    message: str,
    *,
    phase: str,
    committed: bool = False,
    durability: str = "not_committed",
) -> SidecarSecurityError:
    return SidecarSecurityError(
        reason_code,
        message,
        phase=phase,
        committed=committed,
        durability=durability,
    )


def _require_supported_platform() -> None:
    required_flags = ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
    if (
        sys.platform not in SUPPORTED_PLATFORMS
        or not hasattr(os, "geteuid")
        or not hasattr(os, "fchmod")
        or any(not hasattr(os, name) for name in required_flags)
        or os.open not in os.supports_dir_fd
        or os.mkdir not in os.supports_dir_fd
        or os.rename not in os.supports_dir_fd
        or os.stat not in os.supports_dir_fd
        or os.unlink not in os.supports_dir_fd
        or os.stat not in os.supports_follow_symlinks
    ):
        raise _error(
            "session_sidecar_unsupported_platform",
            "secure session sidecars require Darwin or Linux descriptor primitives",
            phase="capability",
        )


def _absolute(path: Path) -> Path:
    expanded = path.expanduser()
    resolved = Path(os.path.abspath(os.fspath(expanded)))
    if not resolved.name or resolved.name in {".", ".."}:
        raise _error(
            "session_sidecar_unsafe_target",
            "session sidecar target name is invalid",
            phase="authority",
        )
    return resolved


def _canonical_path_key(path: Path) -> str:
    key = os.fspath(path)
    if sys.platform == "darwin":
        key = unicodedata.normalize("NFD", key).casefold()
    return key


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _file_read_flags() -> int:
    return os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


def _stat_signature(value: os.stat_result) -> tuple[int, ...]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mode),
        int(value.st_nlink),
        int(value.st_uid),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
    )


def _snapshot(path: Path, value: os.stat_result) -> SidecarSnapshot:
    return SidecarSnapshot(
        path=path,
        dev=int(value.st_dev),
        ino=int(value.st_ino),
        mode=stat.S_IMODE(value.st_mode),
        uid=int(value.st_uid),
        nlink=int(value.st_nlink),
        size=int(value.st_size),
        mtime_ns=int(value.st_mtime_ns),
        ctime_ns=int(value.st_ctime_ns),
    )


def _same_snapshot(value: os.stat_result, expected: SidecarSnapshot) -> bool:
    return (
        int(value.st_dev) == expected.dev
        and int(value.st_ino) == expected.ino
        and stat.S_IMODE(value.st_mode) == expected.mode
        and int(value.st_uid) == expected.uid
        and int(value.st_nlink) == expected.nlink
        and int(value.st_size) == expected.size
        and int(value.st_mtime_ns) == expected.mtime_ns
        and int(value.st_ctime_ns) == expected.ctime_ns
    )


def _validate_ancestor_namespace(path: Path) -> None:
    child = path
    while True:
        parent = child.parent
        if parent == child:
            return
        try:
            parent_metadata = os.lstat(parent)
            child_metadata = os.lstat(child)
        except OSError as exc:
            raise _error(
                "session_sidecar_unsafe_ancestor",
                "session sidecar ancestor namespace is unavailable",
                phase="authority",
            ) from exc
        if not stat.S_ISDIR(parent_metadata.st_mode) or not stat.S_ISDIR(
            child_metadata.st_mode
        ):
            raise _error(
                "session_sidecar_unsafe_ancestor",
                "session sidecar ancestor namespace contains a non-directory",
                phase="authority",
            )
        if parent_metadata.st_uid not in {os.geteuid(), 0}:
            raise _error(
                "session_sidecar_unsafe_ancestor",
                "session sidecar ancestor namespace has a foreign owner",
                phase="authority",
            )
        if stat.S_IMODE(parent_metadata.st_mode) & 0o022:
            sticky = bool(parent_metadata.st_mode & stat.S_ISVTX)
            protected_child = child_metadata.st_uid in {os.geteuid(), 0}
            if not sticky or not protected_child:
                raise _error(
                    "session_sidecar_unsafe_ancestor",
                    "session sidecar ancestor namespace permits unsafe rename",
                    phase="authority",
                )
        child = parent


def _validate_final_parent(value: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(value.st_mode)
        or value.st_uid != os.geteuid()
        or stat.S_IMODE(value.st_mode) & 0o022
    ):
        raise _error(
            "session_sidecar_unsafe_parent",
            "session sidecar parent must be current-user-owned and not group/world writable",
            phase="authority",
        )


def _validate_creation_base(value: os.stat_result) -> None:
    if not stat.S_ISDIR(value.st_mode) or value.st_uid not in {os.geteuid(), 0}:
        raise _error(
            "session_sidecar_unsafe_ancestor",
            "session sidecar creation authority is unsafe",
            phase="authority",
        )
    if stat.S_IMODE(value.st_mode) & 0o022 and not value.st_mode & stat.S_ISVTX:
        raise _error(
            "session_sidecar_unsafe_ancestor",
            "session sidecar creation authority is writable without sticky protection",
            phase="authority",
        )


def _parent_plan(path: Path) -> _ParentPlan:
    logical_target = _absolute(path)
    logical_parent = logical_target.parent
    pending = list(logical_parent.parts[1:])
    cursor = Path(logical_parent.anchor or os.sep)
    missing: list[str] = []
    link_count = 0
    while pending:
        component = pending.pop(0)
        candidate = cursor / component
        try:
            metadata = os.lstat(candidate)
        except FileNotFoundError:
            missing = [component, *pending]
            break
        except OSError as exc:
            raise _error(
                "session_sidecar_unsafe_parent",
                "session sidecar parent authority is unavailable",
                phase="authority",
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            link_count += 1
            try:
                cursor_metadata = os.lstat(cursor)
                raw_target = os.readlink(candidate)
                confirmed = os.lstat(candidate)
            except OSError as exc:
                raise _error(
                    "session_sidecar_unsafe_ancestor",
                    "session sidecar ancestor symlink could not be verified",
                    phase="authority",
                ) from exc
            if (
                link_count > 40
                or metadata.st_uid != 0
                or cursor_metadata.st_uid != 0
                or stat.S_IMODE(cursor_metadata.st_mode) & 0o022
                or _stat_signature(metadata) != _stat_signature(confirmed)
            ):
                raise _error(
                    "session_sidecar_unsafe_ancestor",
                    "session sidecar path contains an untrusted ancestor symlink",
                    phase="authority",
                )
            target = Path(raw_target)
            resolved_target = target if target.is_absolute() else cursor / target
            normalized_target = Path(os.path.abspath(os.fspath(resolved_target)))
            pending = list(normalized_target.parts[1:]) + pending
            cursor = Path(normalized_target.anchor or os.sep)
            continue
        if not stat.S_ISDIR(metadata.st_mode):
            raise _error(
                "session_sidecar_unsafe_ancestor",
                "session sidecar path contains a non-directory or symlink",
                phase="authority",
            )
        cursor = candidate
    canonical_metadata = os.lstat(cursor)
    _validate_ancestor_namespace(cursor)
    _validate_creation_base(canonical_metadata)
    if not missing:
        _validate_final_parent(canonical_metadata)
    canonical_parent = cursor.joinpath(*missing)
    target = canonical_parent / logical_target.name
    return _ParentPlan(
        target=target,
        parent=canonical_parent,
        existing=cursor,
        missing_parts=tuple(missing),
    )


def _open_verified_directory(path: Path, *, final: bool) -> tuple[int, os.stat_result]:
    try:
        before = os.lstat(path)
        if final:
            _validate_final_parent(before)
        else:
            _validate_creation_base(before)
        descriptor = os.open(path, _directory_flags())
    except SidecarSecurityError:
        raise
    except OSError as exc:
        raise _error(
            "session_sidecar_unsafe_parent",
            "session sidecar directory could not be opened",
            phase="authority",
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise _error(
                "session_sidecar_snapshot_changed",
                "session sidecar directory changed while opening",
                phase="authority",
            )
        if final:
            _validate_final_parent(opened)
        else:
            _validate_creation_base(opened)
        return descriptor, opened
    except BaseException:
        os.close(descriptor)
        raise


def _verify_authority(authority: _Authority) -> None:
    try:
        current = os.lstat(authority.parent)
        opened = os.fstat(authority.parent_fd)
    except OSError as exc:
        raise _error(
            "session_sidecar_snapshot_changed",
            "session sidecar parent became unavailable",
            phase="authority",
        ) from exc
    if (
        (current.st_dev, current.st_ino)
        != (authority.parent_dev, authority.parent_ino)
        or (opened.st_dev, opened.st_ino)
        != (authority.parent_dev, authority.parent_ino)
    ):
        raise _error(
            "session_sidecar_snapshot_changed",
            "session sidecar parent authority changed",
            phase="authority",
        )
    _validate_final_parent(current)
    _validate_final_parent(opened)
    _validate_ancestor_namespace(authority.parent)


@contextmanager
def _sidecar_authority(path: Path, *, create_parent: bool) -> Iterator[_Authority | None]:
    _require_supported_platform()
    plan = _parent_plan(path)
    if plan.missing_parts and not create_parent:
        yield None
        return

    descriptor, metadata = _open_verified_directory(
        plan.existing,
        final=not plan.missing_parts,
    )
    current_path = plan.existing
    try:
        for component in plan.missing_parts:
            created = False
            try:
                os.mkdir(
                    component,
                    PRIVATE_DIRECTORY_MODE,
                    dir_fd=descriptor,
                )
                created = True
            except FileExistsError:
                pass
            except OSError as exc:
                raise _error(
                    "session_sidecar_unsafe_parent",
                    "private session sidecar directory could not be created",
                    phase="authority",
                ) from exc
            if created:
                _fsync_directory(descriptor)
            try:
                child_metadata = os.stat(
                    component,
                    dir_fd=descriptor,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise _error(
                    "session_sidecar_unsafe_parent",
                    "session sidecar directory could not be verified",
                    phase="authority",
                ) from exc
            _validate_final_parent(child_metadata)
            child_descriptor: int | None = None
            try:
                child_descriptor = os.open(
                    component,
                    _directory_flags(),
                    dir_fd=descriptor,
                )
                child_opened = os.fstat(child_descriptor)
            except OSError as exc:
                if child_descriptor is not None:
                    os.close(child_descriptor)
                raise _error(
                    "session_sidecar_unsafe_parent",
                    "session sidecar directory could not be opened",
                    phase="authority",
                ) from exc
            assert child_descriptor is not None
            if (child_opened.st_dev, child_opened.st_ino) != (
                child_metadata.st_dev,
                child_metadata.st_ino,
            ):
                os.close(child_descriptor)
                raise _error(
                    "session_sidecar_snapshot_changed",
                    "session sidecar directory changed while opening",
                    phase="authority",
                )
            os.close(descriptor)
            descriptor = child_descriptor
            metadata = child_opened
            current_path = current_path / component

        authority = _Authority(
            target=plan.target,
            parent=plan.parent,
            name=plan.target.name,
            parent_fd=descriptor,
            parent_dev=int(metadata.st_dev),
            parent_ino=int(metadata.st_ino),
        )
        _verify_authority(authority)
        yield authority
    finally:
        os.close(descriptor)


def _raw_target_stat(authority: _Authority) -> os.stat_result | None:
    try:
        return os.stat(
            authority.name,
            dir_fd=authority.parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _error(
            "session_sidecar_unsafe_target",
            "session sidecar target metadata is unavailable",
            phase="target",
        ) from exc


def _validate_target(value: os.stat_result, *, require_private: bool) -> None:
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_uid != os.geteuid()
        or value.st_nlink != 1
    ):
        raise _error(
            "session_sidecar_unsafe_target",
            "session sidecar must be a current-user-owned regular single-link file",
            phase="target",
        )
    if require_private and stat.S_IMODE(value.st_mode) != PRIVATE_FILE_MODE:
        raise _error(
            "session_sidecar_insecure_permissions",
            "session sidecar mode must be 0600",
            phase="target",
        )


def _inspection_for_metadata(
    path: Path,
    target: str,
    metadata: os.stat_result | None,
) -> SidecarInspection:
    if metadata is None:
        return SidecarInspection(target, path, "missing", False, None, None, None)
    mode = stat.S_IMODE(metadata.st_mode)
    snapshot = _snapshot(path, metadata)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
    ):
        return SidecarInspection(
            target,
            path,
            "blocked",
            True,
            mode,
            None,
            "session_sidecar_unsafe_target",
            snapshot=snapshot,
        )
    if mode == PRIVATE_FILE_MODE:
        return SidecarInspection(
            target,
            path,
            "private",
            True,
            mode,
            mode,
            None,
            snapshot=snapshot,
        )
    if PRIVATE_FILE_MODE & ~mode == 0:
        return SidecarInspection(
            target,
            path,
            "repairable",
            True,
            mode,
            PRIVATE_FILE_MODE,
            "session_sidecar_repair_required",
            snapshot=snapshot,
        )
    return SidecarInspection(
        target,
        path,
        "blocked",
        True,
        mode,
        None,
        "session_sidecar_insecure_permissions",
        snapshot=snapshot,
    )


def inspect_sidecar(path: Path, *, target: str = "sidecar") -> SidecarInspection:
    _require_supported_platform()
    normalized = _absolute(path)
    with _sidecar_authority(normalized, create_parent=False) as authority:
        if authority is None:
            return SidecarInspection(
                target, normalized, "missing", False, None, None, None
            )
        metadata = _raw_target_stat(authority)
        _verify_authority(authority)
        return _inspection_for_metadata(normalized, target, metadata)


def ensure_private_directory(path: Path) -> Path:
    """Create and verify a private directory without creating a content file."""
    _require_supported_platform()
    normalized = _absolute(path / ".session-sidecar-authority")
    with _sidecar_authority(normalized, create_parent=True) as authority:
        assert authority is not None
        _verify_authority(authority)
        return authority.parent


def _read_bounded(descriptor: int, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    remaining = max_bytes + 1
    while remaining > 0:
        chunk = os.read(descriptor, min(1024 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    data = b"".join(chunks)
    if len(data) > max_bytes:
        raise _error(
            "session_sidecar_too_large",
            "session sidecar exceeds the configured read limit",
            phase="read",
        )
    return data


def read_private_bytes(
    path: Path,
    *,
    max_bytes: int,
    allow_missing: bool = False,
) -> SecureBytes | None:
    _require_supported_platform()
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    normalized = _absolute(path)
    with _sidecar_authority(normalized, create_parent=False) as authority:
        if authority is None:
            if allow_missing:
                return None
            raise _error(
                "session_sidecar_unsafe_parent",
                "session sidecar parent does not exist",
                phase="read",
            )
        before = _raw_target_stat(authority)
        if before is None:
            if allow_missing:
                return None
            raise _error(
                "session_sidecar_unsafe_target",
                "session sidecar does not exist",
                phase="read",
            )
        _validate_target(before, require_private=True)
        if before.st_size > max_bytes:
            raise _error(
                "session_sidecar_too_large",
                "session sidecar exceeds the configured read limit",
                phase="read",
            )
        try:
            descriptor = os.open(
                authority.name,
                _file_read_flags(),
                dir_fd=authority.parent_fd,
            )
        except OSError as exc:
            raise _error(
                "session_sidecar_unsafe_target",
                "session sidecar could not be opened safely",
                phase="read",
            ) from exc
        try:
            opened = os.fstat(descriptor)
            if _stat_signature(opened) != _stat_signature(before):
                raise _error(
                    "session_sidecar_snapshot_changed",
                    "session sidecar changed while opening",
                    phase="read",
                )
            data = _read_bounded(descriptor, max_bytes)
            completed = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = _raw_target_stat(authority)
        if (
            after is None
            or _stat_signature(opened) != _stat_signature(completed)
            or _stat_signature(completed) != _stat_signature(after)
        ):
            raise _error(
                "session_sidecar_snapshot_changed",
                "session sidecar changed while reading",
                phase="read",
            )
        _verify_authority(authority)
        return SecureBytes(data, _snapshot(normalized, completed))


def read_private_json(
    path: Path,
    *,
    max_bytes: int,
    allow_missing: bool = False,
) -> SecureJson | None:
    loaded = read_private_bytes(path, max_bytes=max_bytes, allow_missing=allow_missing)
    if loaded is None:
        return None
    try:
        text = loaded.data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _error(
            "session_sidecar_invalid_utf8",
            "session sidecar is not valid UTF-8",
            phase="parse",
        ) from exc
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise _error(
            "session_sidecar_malformed_json",
            "session sidecar contains malformed JSON",
            phase="parse",
        ) from exc
    if not isinstance(payload, dict):
        raise _error(
            "session_sidecar_invalid_root",
            "session sidecar JSON root must be an object",
            phase="parse",
        )
    return SecureJson(payload, loaded.snapshot)


def _write_all(descriptor: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written <= 0:
            raise OSError("short sidecar write")
        offset += written


def _fsync_directory(descriptor: int) -> None:
    os.fsync(descriptor)


def _cleanup_owned_name(
    authority: _Authority,
    name: str,
    identity: tuple[int, int] | None,
) -> bool:
    if identity is None:
        return False
    try:
        current = os.stat(
            name,
            dir_fd=authority.parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if (int(current.st_dev), int(current.st_ino)) != identity:
        return False
    try:
        os.unlink(name, dir_fd=authority.parent_fd)
    except OSError:
        return False
    return True


def _replacement_state(
    authority: _Authority,
    temporary_name: str,
    temporary_identity: tuple[int, int] | None,
    source_snapshot: SidecarSnapshot | None,
) -> bool | None:
    try:
        if temporary_identity is None:
            return None
        target = _raw_target_stat(authority)
        if target is not None and (
            int(target.st_dev),
            int(target.st_ino),
        ) == temporary_identity:
            return True
        temporary = os.stat(
            temporary_name,
            dir_fd=authority.parent_fd,
            follow_symlinks=False,
        )
        temporary_unchanged = (
            int(temporary.st_dev),
            int(temporary.st_ino),
        ) == temporary_identity
        source_unchanged = (
            target is None
            if source_snapshot is None
            else target is not None and _same_snapshot(target, source_snapshot)
        )
        return False if temporary_unchanged and source_unchanged else None
    except BaseException:
        return None


def atomic_write_private_json(
    path: Path,
    payload: Mapping[str, Any],
    *,
    max_bytes: int,
    expected_snapshot: SidecarSnapshot | None | object = _EXPECTED_UNSET,
) -> PublicationResult:
    _require_supported_platform()
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    try:
        encoded = (json.dumps(dict(payload), indent=2) + "\n").encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise _error(
            "session_sidecar_write_error",
            "session sidecar payload could not be serialized",
            phase="serialize",
        ) from exc
    if len(encoded) > max_bytes:
        raise _error(
            "session_sidecar_too_large",
            "session sidecar payload exceeds the configured write limit",
            phase="serialize",
        )

    normalized = _absolute(path)
    with _sidecar_authority(normalized, create_parent=True) as authority:
        assert authority is not None
        source_metadata = _raw_target_stat(authority)
        if source_metadata is not None:
            _validate_target(source_metadata, require_private=True)
        source_snapshot = (
            _snapshot(normalized, source_metadata)
            if source_metadata is not None
            else None
        )
        if expected_snapshot is not _EXPECTED_UNSET:
            if expected_snapshot is None:
                if source_snapshot is not None:
                    raise _error(
                        "session_sidecar_snapshot_changed",
                        "session sidecar appeared after its caller snapshot",
                        phase="publish",
                    )
            elif not isinstance(expected_snapshot, SidecarSnapshot) or (
                source_metadata is None
                or not _same_snapshot(source_metadata, expected_snapshot)
            ):
                raise _error(
                    "session_sidecar_snapshot_changed",
                    "session sidecar changed after its caller snapshot",
                    phase="publish",
                )
        temporary_name = f".{authority.name}.{uuid.uuid4().hex}.tmp"
        temporary_identity: tuple[int, int] | None = None
        committed = False
        try:
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_NOFOLLOW
                | os.O_NONBLOCK
                | os.O_CLOEXEC,
                PRIVATE_FILE_MODE,
                dir_fd=authority.parent_fd,
            )
            try:
                created = os.fstat(descriptor)
                temporary_identity = (int(created.st_dev), int(created.st_ino))
                os.fchmod(descriptor, PRIVATE_FILE_MODE)
                _write_all(descriptor, encoded)
                os.fsync(descriptor)
                staged = os.fstat(descriptor)
                named_stage = os.stat(
                    temporary_name,
                    dir_fd=authority.parent_fd,
                    follow_symlinks=False,
                )
                if (
                    (staged.st_dev, staged.st_ino) != temporary_identity
                    or _stat_signature(staged) != _stat_signature(named_stage)
                ):
                    raise _error(
                        "session_sidecar_snapshot_changed",
                        "staged session sidecar changed before publication",
                        phase="stage",
                    )
                _validate_target(staged, require_private=True)
            finally:
                os.close(descriptor)

            current = _raw_target_stat(authority)
            if source_snapshot is None:
                if current is not None:
                    raise _error(
                        "session_sidecar_snapshot_changed",
                        "session sidecar appeared before publication",
                        phase="publish",
                    )
            elif current is None or not _same_snapshot(current, source_snapshot):
                raise _error(
                    "session_sidecar_snapshot_changed",
                    "session sidecar changed before publication",
                    phase="publish",
                )
            _verify_authority(authority)
            try:
                os.replace(
                    temporary_name,
                    authority.name,
                    src_dir_fd=authority.parent_fd,
                    dst_dir_fd=authority.parent_fd,
                )
            except BaseException as exc:
                replacement_state = _replacement_state(
                    authority,
                    temporary_name,
                    temporary_identity,
                    source_snapshot,
                )
                if replacement_state is False:
                    raise _error(
                        "session_sidecar_write_error",
                        "session sidecar could not be published",
                        phase="publish",
                    ) from exc
                raise _error(
                    "session_sidecar_durability_uncertain",
                    "session sidecar replacement outcome is uncertain",
                    phase="durability",
                    committed=True,
                    durability="uncertain",
                ) from exc
            committed = True
            published = _raw_target_stat(authority)
            if (
                published is None
                or (published.st_dev, published.st_ino) != temporary_identity
            ):
                raise _error(
                    "session_sidecar_durability_uncertain",
                    "published session sidecar identity could not be verified",
                    phase="durability",
                    committed=True,
                    durability="uncertain",
                )
            _validate_target(published, require_private=True)
            _fsync_directory(authority.parent_fd)
            _verify_authority(authority)
            final = _raw_target_stat(authority)
            if final is None or _stat_signature(final) != _stat_signature(published):
                raise _error(
                    "session_sidecar_durability_uncertain",
                    "published session sidecar changed during durability verification",
                    phase="durability",
                    committed=True,
                    durability="uncertain",
                )
            return PublicationResult(True, "synced", _snapshot(normalized, final))
        except SidecarSecurityError as exc:
            if committed and not exc.committed:
                raise _error(
                    "session_sidecar_durability_uncertain",
                    "session sidecar publication failed after replacement",
                    phase="durability",
                    committed=True,
                    durability="uncertain",
                ) from exc
            raise
        except OSError as exc:
            if committed:
                raise _error(
                    "session_sidecar_durability_uncertain",
                    "session sidecar durability could not be confirmed",
                    phase="durability",
                    committed=True,
                    durability="uncertain",
                ) from exc
            raise _error(
                "session_sidecar_write_error",
                "session sidecar could not be published",
                phase="publish",
            ) from exc
        finally:
            _cleanup_owned_name(authority, temporary_name, temporary_identity)


def repair_sidecar_mode(
    path: Path,
    *,
    target: str = "sidecar",
    expected_snapshot: SidecarSnapshot | None = None,
) -> SidecarInspection:
    inspection = inspect_sidecar(path, target=target)
    if expected_snapshot is not None and inspection.snapshot != expected_snapshot:
        raise _error(
            "session_sidecar_snapshot_changed",
            "session sidecar changed after repair preflight",
            phase="repair",
        )
    if inspection.state in {"missing", "private"}:
        return inspection
    if inspection.state != "repairable":
        raise _error(
            inspection.reason_code or "session_sidecar_repair_failed",
            "session sidecar permissions cannot be safely narrowed",
            phase="repair",
        )
    normalized = inspection.path
    with _sidecar_authority(normalized, create_parent=False) as authority:
        assert authority is not None
        before = _raw_target_stat(authority)
        if before is None:
            raise _error(
                "session_sidecar_snapshot_changed",
                "session sidecar disappeared before permission repair",
                phase="repair",
            )
        current = _inspection_for_metadata(normalized, target, before)
        if (
            current.state != "repairable"
            or current.snapshot != inspection.snapshot
            or (
                expected_snapshot is not None
                and current.snapshot != expected_snapshot
            )
        ):
            raise _error(
                "session_sidecar_snapshot_changed",
                "session sidecar changed before permission repair",
                phase="repair",
            )
        try:
            descriptor = os.open(
                authority.name,
                os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=authority.parent_fd,
            )
        except OSError as exc:
            raise _error(
                "session_sidecar_repair_failed",
                "session sidecar could not be opened for permission repair",
                phase="repair",
            ) from exc
        try:
            opened = os.fstat(descriptor)
            if _stat_signature(opened) != _stat_signature(before):
                raise _error(
                    "session_sidecar_snapshot_changed",
                    "session sidecar changed while opening for repair",
                    phase="repair",
                )
            os.fchmod(descriptor, PRIVATE_FILE_MODE)
            os.fsync(descriptor)
            repaired = os.fstat(descriptor)
        except OSError as exc:
            raise _error(
                "session_sidecar_repair_failed",
                "session sidecar permission repair failed",
                phase="repair",
            ) from exc
        finally:
            os.close(descriptor)
        after = _raw_target_stat(authority)
        if (
            after is None
            or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
            or _stat_signature(after) != _stat_signature(repaired)
            or stat.S_IMODE(after.st_mode) != PRIVATE_FILE_MODE
        ):
            raise _error(
                "session_sidecar_repair_failed",
                "session sidecar permission repair could not be verified",
                phase="repair",
            )
        _verify_authority(authority)
        return replace(
            current,
            state="repaired",
            after_mode=PRIVATE_FILE_MODE,
            reason_code=None,
            changed=True,
            snapshot=_snapshot(normalized, after),
        )


def _alias_candidate(role: str, path: Path) -> _AliasCandidate:
    plan = _parent_plan(path)
    normalized = plan.target
    if plan.missing_parts:
        return _AliasCandidate(
            role,
            normalized,
            _canonical_path_key(normalized),
            None,
            None,
        )
    with _sidecar_authority(normalized, create_parent=False) as authority:
        assert authority is not None
        metadata = _raw_target_stat(authority)
        _verify_authority(authority)
    if metadata is not None and not stat.S_ISREG(metadata.st_mode):
        raise _error(
            "session_sidecar_unsafe_target",
            f"{role} alias target is not a regular file",
            phase="alias",
        )
    return _AliasCandidate(
        role,
        normalized,
        _canonical_path_key(normalized),
        (int(metadata.st_dev), int(metadata.st_ino)) if metadata is not None else None,
        metadata,
    )


def assert_distinct_sidecars(paths: Mapping[str, Path]) -> None:
    _require_supported_platform()
    candidates = [_alias_candidate(role, path) for role, path in paths.items()]
    for index, left in enumerate(candidates):
        for right in candidates[index + 1 :]:
            if left.canonical_key == right.canonical_key or (
                left.identity is not None and left.identity == right.identity
            ):
                raise _error(
                    "session_sidecar_alias",
                    "session sidecar paths must resolve to distinct authorities",
                    phase="alias",
                )
    for candidate in candidates:
        if candidate.metadata is None:
            continue
        if (
            candidate.metadata.st_uid != os.geteuid()
            or candidate.metadata.st_nlink != 1
        ):
            raise _error(
                "session_sidecar_unsafe_target",
                f"{candidate.role} alias target is unsafe",
                phase="alias",
            )


@contextmanager
def _secure_sidecar_file_lock(
    path: Path,
    *,
    timeout_seconds: float = 5.0,
) -> Iterator[None]:
    _require_supported_platform()
    try:
        import fcntl
    except (ImportError, AttributeError) as exc:
        raise _error(
            "session_sidecar_unsupported_platform",
            "secure session sidecar locking is unavailable",
            phase="capability",
        ) from exc
    if not hasattr(fcntl, "flock"):
        raise _error(
            "session_sidecar_unsupported_platform",
            "secure session sidecar locking is unavailable",
            phase="capability",
        )
    if timeout_seconds < 0:
        raise ValueError("timeout_seconds must be non-negative")
    normalized = _absolute(path)
    with _sidecar_authority(normalized, create_parent=True) as authority:
        assert authority is not None
        before = _raw_target_stat(authority)
        if before is not None:
            _validate_target(before, require_private=False)
            mode = stat.S_IMODE(before.st_mode)
            if PRIVATE_FILE_MODE & ~mode:
                raise _error(
                    "session_sidecar_insecure_permissions",
                    "legacy sidecar lock lacks owner read/write permissions",
                    phase="lock",
                )
            flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
            create_mode: int | None = None
        else:
            flags = (
                os.O_RDWR
                | os.O_CREAT
                | os.O_EXCL
                | os.O_NOFOLLOW
                | os.O_NONBLOCK
                | os.O_CLOEXEC
            )
            create_mode = PRIVATE_FILE_MODE
        try:
            if create_mode is None:
                descriptor = os.open(
                    authority.name,
                    flags,
                    dir_fd=authority.parent_fd,
                )
            else:
                descriptor = os.open(
                    authority.name,
                    flags,
                    create_mode,
                    dir_fd=authority.parent_fd,
                )
        except FileExistsError:
            before = _raw_target_stat(authority)
            if before is None:
                raise _error(
                    "session_sidecar_snapshot_changed",
                    "sidecar lock disappeared during creation",
                    phase="lock",
                )
            _validate_target(before, require_private=False)
            if PRIVATE_FILE_MODE & ~stat.S_IMODE(before.st_mode):
                raise _error(
                    "session_sidecar_insecure_permissions",
                    "concurrent sidecar lock lacks owner read/write permissions",
                    phase="lock",
                )
            try:
                descriptor = os.open(
                    authority.name,
                    os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                    dir_fd=authority.parent_fd,
                )
            except OSError as exc:
                raise _error(
                    "session_sidecar_unsafe_target",
                    "concurrent sidecar lock could not be opened safely",
                    phase="lock",
                ) from exc
        except OSError as exc:
            raise _error(
                "session_sidecar_unsafe_target",
                "sidecar lock could not be opened safely",
                phase="lock",
            ) from exc
        try:
            opened = os.fstat(descriptor)
            _validate_target(opened, require_private=False)
            if before is not None and _stat_signature(opened) != _stat_signature(before):
                raise _error(
                    "session_sidecar_snapshot_changed",
                    "sidecar lock changed while opening",
                    phase="lock",
                )
            if stat.S_IMODE(opened.st_mode) != PRIVATE_FILE_MODE:
                os.fchmod(descriptor, PRIVATE_FILE_MODE)
                os.fsync(descriptor)
                opened = os.fstat(descriptor)
            current = _raw_target_stat(authority)
            if current is None or _stat_signature(current) != _stat_signature(opened):
                raise _error(
                    "session_sidecar_snapshot_changed",
                    "sidecar lock path changed while opening",
                    phase="lock",
                )
            _verify_authority(authority)

            deadline = time.monotonic() + timeout_seconds
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                        raise _error(
                            "session_sidecar_unsafe_target",
                            "sidecar lock acquisition failed",
                            phase="lock",
                        ) from exc
                    if time.monotonic() >= deadline:
                        raise _error(
                            "session_sidecar_lock_timeout",
                            "sidecar lock acquisition timed out",
                            phase="lock",
                        )
                    time.sleep(min(0.05, max(0.001, deadline - time.monotonic())))
            try:
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


@contextmanager
def secure_sidecar_lock(
    path: Path,
    *,
    timeout_seconds: float = 5.0,
) -> Iterator[None]:
    _require_supported_platform()
    if timeout_seconds < 0:
        raise ValueError("timeout_seconds must be non-negative")
    normalized = _absolute(path)
    key = _canonical_path_key(_parent_plan(normalized).target)
    with _PROCESS_LOCKS_GUARD:
        process_lock = _PROCESS_LOCKS.setdefault(key, threading.Lock())
    deadline = time.monotonic() + timeout_seconds
    if not process_lock.acquire(timeout=timeout_seconds):
        raise _error(
            "session_sidecar_lock_timeout",
            "sidecar lock acquisition timed out",
            phase="lock",
        )
    try:
        remaining = max(0.0, deadline - time.monotonic())
        with _secure_sidecar_file_lock(path, timeout_seconds=remaining):
            yield
    finally:
        process_lock.release()
