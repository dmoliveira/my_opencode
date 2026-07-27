#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import secrets
import stat
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

MAX_CONFIG_BYTES = 4 * 1024 * 1024
MAX_SAFE_INTEGER = 9_007_199_254_740_991
LOCK_TIMEOUT_MS = 2000
LOCK_POLL_MS = 20
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
LOCK_OWNER_TOKEN = "owner-token"
STAGE_PREFIX = ".my-opencode-config.stage-"
_ACTIVE_LOCKS = threading.local()

Durability = Literal["not_committed", "synced", "uncertain", "partial"]


class ConfigTransactionError(RuntimeError):
    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        phase: str,
        committed: bool = False,
        durability: Durability = "not_committed",
        lock_released: bool = False,
        cause: BaseException | None = None,
        secondary_reason_code: str | None = None,
        file_results: Sequence["ConfigFileCommitResult"] = (),
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.phase = phase
        self.committed = committed
        self.durability = durability
        self.lock_released = lock_released
        self.cause_code = (
            str(getattr(cause, "errno"))
            if cause is not None and getattr(cause, "errno", None) is not None
            else type(cause).__name__ if cause is not None else None
        )
        self.secondary_reason_code = secondary_reason_code
        self.file_results = tuple(file_results)

    def as_dict(self) -> dict[str, Any]:
        return {
            "reason_code": self.reason_code,
            "message": str(self),
            "phase": self.phase,
            "committed": self.committed,
            "durability": self.durability,
            "lock_released": self.lock_released,
            "cause_code": self.cause_code,
            "secondary_reason_code": self.secondary_reason_code,
            "files": [result.as_dict() for result in self.file_results],
        }


class _NoProvisionChange(Exception):
    pass


@dataclass(frozen=True)
class ConfigFileCommitResult:
    path: Path
    canonical_path: Path
    changed: bool
    committed: bool
    durability: Durability

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "canonical_path": str(self.canonical_path),
            "changed": self.changed,
            "committed": self.committed,
            "durability": self.durability,
        }


@dataclass(frozen=True)
class ConfigTransactionResult:
    changed: bool
    committed: bool
    durability: Durability
    lock_released: bool
    files: tuple[ConfigFileCommitResult, ...]


@dataclass(frozen=True)
class ConfigFileParticipant:
    path: Path
    mutator: Callable[[dict[str, Any]], None]


def _transaction_error(
    reason_code: str,
    message: str,
    *,
    phase: str,
    cause: BaseException | None = None,
) -> ConfigTransactionError:
    return ConfigTransactionError(
        reason_code,
        message,
        phase=phase,
        cause=cause,
    )


def _strip_jsonc(content: str) -> str:
    out: list[str] = []
    i = 0
    in_string = False
    escape = False
    while i < len(content):
        ch = content[i]
        nxt = content[i + 1] if i + 1 < len(content) else ""

        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue

        if ch == "/" and nxt == "/":
            out.extend((" ", " "))
            i += 2
            while i < len(content) and content[i] not in "\r\n":
                out.append(" ")
                i += 1
            continue

        if ch == "/" and nxt == "*":
            out.extend((" ", " "))
            i += 2
            terminated = False
            while i + 1 < len(content) and not (
                content[i] == "*" and content[i + 1] == "/"
            ):
                out.append(content[i] if content[i] in "\r\n" else " ")
                i += 1
            if i + 1 >= len(content):
                raise ValueError("Unterminated JSONC block comment")
            terminated = True
            if terminated:
                out.extend((" ", " "))
            i += 2
            continue

        out.append(ch)
        i += 1

    stripped = "".join(out)
    # Remove trailing commas before object/array close.
    result: list[str] = []
    i = 0
    in_string = False
    escape = False
    while i < len(stripped):
        ch = stripped[i]
        if in_string:
            result.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            result.append(ch)
            i += 1
            continue

        if ch == ",":
            j = i + 1
            while j < len(stripped) and stripped[j].isspace():
                j += 1
            k = i - 1
            while k >= 0 and stripped[k].isspace():
                k -= 1
            if (
                j < len(stripped)
                and stripped[j] in "]}"
                and k >= 0
                and stripped[k] not in "[{,:"
            ):
                i += 1
                continue

        result.append(ch)
        i += 1

    return "".join(result)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _safe_parse_int(value: str) -> int:
    parsed = int(value)
    if abs(parsed) > MAX_SAFE_INTEGER:
        raise ValueError("Integer exceeds cross-runtime safe range")
    return parsed


def _reject_nonfinite(_value: str) -> None:
    raise ValueError("Non-finite JSON number")


def _validate_json_value(value: Any) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise ValueError("Integer exceeds cross-runtime safe range")
        return
    if isinstance(value, float):
        if not math.isfinite(value) or (
            value.is_integer() and abs(value) > MAX_SAFE_INTEGER
        ):
            raise ValueError("Number exceeds cross-runtime safe range")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            _validate_json_value(item)
        return
    raise ValueError("Value is not JSON-compatible")


def _parse_config_text(content: str, path: Path) -> dict[str, Any]:
    parsed = json.loads(
        _strip_jsonc(content),
        object_pairs_hook=_reject_duplicate_keys,
        parse_int=_safe_parse_int,
        parse_constant=_reject_nonfinite,
    )
    _validate_json_value(parsed)
    if not isinstance(parsed, dict):
        raise ValueError(f"Config root must be object: {path}")
    return parsed


def _load_json_or_jsonc(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) > MAX_CONFIG_BYTES:
        raise ValueError(f"Config exceeds {MAX_CONFIG_BYTES} bytes: {path}")
    return _parse_config_text(raw.decode("utf-8", errors="strict"), path)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def _json_values_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _json_values_equal(value, right[key]) for key, value in left.items()
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _json_values_equal(first, second)
            for first, second in zip(left, right, strict=True)
        )
    return bool(left == right)


@dataclass(frozen=True)
class _FileIdentity:
    dev: int
    ino: int
    mode: int
    nlink: int
    uid: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True)
class _LinkSnapshot:
    path: Path
    identity: _FileIdentity
    target: str


@dataclass(frozen=True)
class _PathSnapshot:
    logical_path: Path
    canonical_path: Path
    links: tuple[_LinkSnapshot, ...]
    directories: tuple[tuple[Path, _FileIdentity], ...]
    target: _FileIdentity | None


@dataclass(frozen=True)
class _OwnedLock:
    path: Path
    token: bytes
    identity: tuple[int, int]


@dataclass
class _StagedConfig:
    logical_path: Path
    snapshot: _PathSnapshot
    before: dict[str, Any]
    after: dict[str, Any]
    payload: bytes | None = None
    stage_name: str | None = None
    stage_identity: _FileIdentity | None = None
    parent_fd: int = -1
    committed: bool = False
    durability: Durability = "not_committed"


def _identity(metadata: os.stat_result) -> _FileIdentity:
    return _FileIdentity(
        dev=metadata.st_dev,
        ino=metadata.st_ino,
        mode=metadata.st_mode,
        nlink=metadata.st_nlink,
        uid=metadata.st_uid,
        size=metadata.st_size,
        mtime_ns=metadata.st_mtime_ns,
        ctime_ns=metadata.st_ctime_ns,
    )


def _same_object(left: _FileIdentity, right: _FileIdentity) -> bool:
    return (left.dev, left.ino) == (right.dev, right.ino)


def _same_directory_identity(left: _FileIdentity, right: _FileIdentity) -> bool:
    return (
        _same_object(left, right)
        and left.mode == right.mode
        and left.uid == right.uid
    )


def _same_path_snapshot(left: _PathSnapshot, right: _PathSnapshot) -> bool:
    if (
        left.logical_path != right.logical_path
        or left.canonical_path != right.canonical_path
        or left.target != right.target
        or len(left.links) != len(right.links)
    ):
        return False
    if any(
        first.path != second.path
        or first.target != second.target
        or first.identity != second.identity
        for first, second in zip(left.links, right.links, strict=True)
    ):
        return False
    left_directories = dict(left.directories)
    right_directories = dict(right.directories)
    return left_directories.keys() == right_directories.keys() and all(
        _same_directory_identity(identity, right_directories[path])
        for path, identity in left_directories.items()
    )


def _validate_ancestor_namespace(path: Path) -> None:
    child = path
    while True:
        parent = child.parent
        if parent == child:
            return
        try:
            parent_metadata = parent.lstat()
            child_metadata = child.lstat()
        except OSError as cause:
            raise _transaction_error(
                "config_unsafe_ancestor",
                "config ancestor namespace is unavailable",
                phase="authority",
                cause=cause,
            )
        if not stat.S_ISDIR(parent_metadata.st_mode) or not stat.S_ISDIR(
            child_metadata.st_mode
        ):
            raise _transaction_error(
                "config_unsafe_ancestor",
                "config ancestor namespace contains a non-directory",
                phase="authority",
            )
        if parent_metadata.st_uid not in {os.geteuid(), 0}:
            raise _transaction_error(
                "config_unsafe_ancestor",
                "config ancestor namespace has a foreign owner",
                phase="authority",
            )
        if stat.S_IMODE(parent_metadata.st_mode) & 0o022:
            sticky = bool(parent_metadata.st_mode & stat.S_ISVTX)
            protected_child = child_metadata.st_uid in {os.geteuid(), 0}
            if not sticky or not protected_child:
                raise _transaction_error(
                    "config_unsafe_ancestor",
                    "config ancestor namespace permits unsafe rename",
                    phase="authority",
                )
        child = parent


def _validate_write_parent(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise _transaction_error(
            "config_unsafe_parent",
            "config target parent must be current-user-owned and not group/world writable",
            phase="authority",
        )


def _validate_config_target(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise _transaction_error(
            "config_unsafe_target",
            "config target must be a current-user-owned single-link regular file",
            phase="read",
        )


def _absolute_lexical_path(path: Path) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded
    return expanded


def _snapshot_path(path: Path, *, allow_missing_final: bool) -> _PathSnapshot:
    logical = _absolute_lexical_path(path)
    pending = list(logical.parts[1:])
    current = Path(logical.anchor or os.sep)
    links: list[_LinkSnapshot] = []
    directories: dict[Path, _FileIdentity] = {}
    link_count = 0

    while pending:
        component = pending.pop(0)
        if component == "..":
            current = current.parent
            continue
        candidate = current / component
        try:
            metadata = candidate.lstat()
        except FileNotFoundError as cause:
            if not pending and allow_missing_final:
                parent_metadata = current.lstat()
                _validate_write_parent(parent_metadata)
                directories[current] = _identity(parent_metadata)
                _validate_ancestor_namespace(current)
                return _PathSnapshot(
                    logical,
                    candidate,
                    tuple(links),
                    tuple(directories.items()),
                    None,
                )
            raise _transaction_error(
                "config_path_unavailable",
                f"config path is unavailable: {logical}",
                phase="resolve",
                cause=cause,
            )
        except OSError as cause:
            raise _transaction_error(
                "config_path_unavailable",
                f"unable to inspect config path: {logical}",
                phase="resolve",
                cause=cause,
            )

        if stat.S_ISLNK(metadata.st_mode):
            link_count += 1
            identity = _identity(metadata)
            if link_count > 40:
                raise _transaction_error(
                    "config_symlink_loop",
                    "config symlink chain is cyclic or too deep",
                    phase="resolve",
                )
            try:
                raw_target = os.readlink(candidate)
            except OSError as cause:
                raise _transaction_error(
                    "config_symlink_changed",
                    "unable to read config symlink",
                    phase="resolve",
                    cause=cause,
                )
            links.append(_LinkSnapshot(candidate, identity, raw_target))
            target = Path(raw_target)
            if target.is_absolute():
                pending = list(target.parts[1:]) + pending
                current = Path(target.anchor or os.sep)
            else:
                pending = list(target.parts) + pending
            continue

        if pending:
            if not stat.S_ISDIR(metadata.st_mode):
                raise _transaction_error(
                    "config_unsafe_ancestor",
                    "config path contains a non-directory ancestor",
                    phase="resolve",
                )
            directories[candidate] = _identity(metadata)
            current = candidate
            continue

        _validate_config_target(metadata)
        parent_metadata = current.lstat()
        _validate_write_parent(parent_metadata)
        directories[current] = _identity(parent_metadata)
        _validate_ancestor_namespace(current)
        return _PathSnapshot(
            logical,
            candidate,
            tuple(links),
            tuple(directories.items()),
            _identity(metadata),
        )

    raise _transaction_error(
        "config_path_unavailable",
        "config path cannot resolve to a filesystem root",
        phase="resolve",
    )


def _ensure_write_parent(path: Path) -> None:
    logical_parent = _absolute_lexical_path(path).parent
    if logical_parent.exists():
        try:
            current = logical_parent.resolve(strict=True)
            _validate_write_parent(current.lstat())
            _validate_ancestor_namespace(current)
        except ConfigTransactionError:
            raise
        except OSError as cause:
            raise _transaction_error(
                "config_unsafe_parent",
                "unable to validate existing config target parent",
                phase="authority",
                cause=cause,
            )
        return
    nearest = logical_parent
    missing: list[str] = []
    while not nearest.exists():
        missing.append(nearest.name)
        nearest = nearest.parent
    try:
        current = nearest.resolve(strict=True)
    except OSError as cause:
        raise _transaction_error(
            "config_unsafe_parent",
            "unable to resolve existing config target ancestor",
            phase="authority",
            cause=cause,
        )
    metadata = current.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise _transaction_error(
            "config_unsafe_parent",
            "config target parent contains a non-directory",
            phase="authority",
        )
    _validate_ancestor_namespace(current)
    for component in reversed(missing):
        candidate = current / component
        created = False
        try:
            try:
                os.mkdir(candidate, PRIVATE_DIRECTORY_MODE)
                created = True
            except FileExistsError:
                pass
            if created:
                os.chmod(candidate, PRIVATE_DIRECTORY_MODE, follow_symlinks=False)
                parent_fd = os.open(current, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
            metadata = candidate.lstat()
        except OSError as cause:
            raise _transaction_error(
                "config_unsafe_parent",
                "unable to create config target parent",
                phase="authority",
                cause=cause,
            )
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise _transaction_error(
                "config_unsafe_parent",
                "created config target parent is unsafe",
                phase="authority",
            )
        current = candidate
    _validate_write_parent(current.lstat())
    _validate_ancestor_namespace(current)


def _read_snapshot_config(snapshot: _PathSnapshot) -> dict[str, Any]:
    if snapshot.target is None:
        return {}
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        descriptor = os.open(snapshot.canonical_path, flags)
    except OSError as cause:
        raise _transaction_error(
            "config_unsafe_target",
            "unable to open config target without following links",
            phase="read",
            cause=cause,
        )
    try:
        opened = os.fstat(descriptor)
        _validate_config_target(opened)
        if _identity(opened) != snapshot.target:
            raise _transaction_error(
                "config_snapshot_changed",
                "config target changed while opening",
                phase="read",
            )
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_CONFIG_BYTES:
            chunk = os.read(descriptor, min(64 * 1024, MAX_CONFIG_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > MAX_CONFIG_BYTES:
            raise _transaction_error(
                "config_too_large",
                "config exceeds its byte limit",
                phase="read",
            )
        if _identity(os.fstat(descriptor)) != snapshot.target:
            raise _transaction_error(
                "config_snapshot_changed",
                "config target changed while reading",
                phase="read",
            )
    finally:
        os.close(descriptor)
    raw = b"".join(chunks)
    if len(raw) != snapshot.target.size:
        raise _transaction_error(
            "config_snapshot_changed",
            "config target size changed while reading",
            phase="read",
        )
    try:
        text = raw.decode("utf-8", errors="strict")
        return _parse_config_text(text, snapshot.logical_path)
    except UnicodeDecodeError as cause:
        raise _transaction_error(
            "config_invalid_utf8",
            "config is not valid UTF-8",
            phase="parse",
            cause=cause,
        )
    except (json.JSONDecodeError, RecursionError, ValueError) as cause:
        raise _transaction_error(
            "config_malformed",
            f"config is malformed: {snapshot.logical_path}",
            phase="parse",
            cause=cause,
        )


def _serialize_config(data: dict[str, Any]) -> bytes:
    try:
        _validate_json_value(data)
        payload = (json.dumps(data, indent=2, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, RecursionError) as cause:
        raise _transaction_error(
            "config_invalid_value",
            "config mutation produced an unsupported JSON value",
            phase="serialize",
            cause=cause,
        )
    if len(payload) > MAX_CONFIG_BYTES:
        raise _transaction_error(
            "config_too_large",
            "serialized config exceeds its byte limit",
            phase="serialize",
        )
    return payload


def _active_lock_paths() -> set[str]:
    paths = getattr(_ACTIVE_LOCKS, "paths", None)
    if paths is None:
        paths = set()
        _ACTIVE_LOCKS.paths = paths
    return paths


def _lock_registry() -> Path:
    root = Path("/tmp") / f"my-opencode-config-locks-{os.geteuid()}"
    _ensure_write_parent(root / "placeholder")
    try:
        metadata = root.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise _transaction_error(
                "config_lock_unsafe",
                "config lock registry is not a directory",
                phase="lock_acquire",
            )
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o022:
            raise _transaction_error(
                "config_lock_unsafe",
                "config lock registry has unsafe ownership or permissions",
                phase="lock_acquire",
            )
        os.chmod(root, PRIVATE_DIRECTORY_MODE, follow_symlinks=False)
        _snapshot_path(root / "placeholder", allow_missing_final=True)
        return root
    except ConfigTransactionError:
        raise
    except OSError as cause:
        raise _transaction_error(
            "config_lock_unsafe",
            "unable to prepare config lock registry",
            phase="lock_acquire",
            cause=cause,
        )


def _lock_name(key: str) -> str:
    return f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}.lock"


def _inspect_lock(path: Path) -> str:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return "missing"
    except OSError as cause:
        raise _transaction_error(
            "config_lock_unsafe",
            "unable to inspect config lock",
            phase="lock_acquire",
            cause=cause,
        )
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise _transaction_error(
            "config_lock_unsafe",
            "config lock directory is unsafe",
            phase="lock_acquire",
        )
    if stat.S_IMODE(metadata.st_mode) != PRIVATE_DIRECTORY_MODE:
        return "initializing"
    lock_fd = -1
    try:
        lock_fd = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except FileNotFoundError:
        return "missing"
    except OSError as cause:
        raise _transaction_error(
            "config_lock_unsafe",
            "unable to open config lock directory",
            phase="lock_acquire",
            cause=cause,
        )
    try:
        opened = os.fstat(lock_fd)
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            return "initializing"
        token_fd = -1
        try:
            token_fd = os.open(
                LOCK_OWNER_TOKEN,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=lock_fd,
            )
        except FileNotFoundError:
            return "initializing"
        except OSError as cause:
            raise _transaction_error(
                "config_lock_unsafe",
                "unable to open config lock token",
                phase="lock_acquire",
                cause=cause,
            )
        try:
            token_metadata = os.fstat(token_fd)
            if (
                not stat.S_ISREG(token_metadata.st_mode)
                or token_metadata.st_uid != os.geteuid()
                or token_metadata.st_nlink != 1
                or stat.S_IMODE(token_metadata.st_mode) != PRIVATE_FILE_MODE
                or token_metadata.st_size != 65
            ):
                raise _transaction_error(
                    "config_lock_unsafe",
                    "config lock token is unsafe",
                    phase="lock_acquire",
                )
            token = os.read(token_fd, 66)
            if _identity(os.fstat(token_fd)) != _identity(token_metadata):
                return "initializing"
        finally:
            if token_fd >= 0:
                os.close(token_fd)
        if len(token) != 65 or token[-1:] != b"\n":
            raise _transaction_error(
                "config_lock_unsafe",
                "config lock token is malformed",
                phase="lock_acquire",
            )
        try:
            int(token[:-1], 16)
        except ValueError as cause:
            raise _transaction_error(
                "config_lock_unsafe",
                "config lock token is malformed",
                phase="lock_acquire",
                cause=cause,
            )
        try:
            current = path.lstat()
        except FileNotFoundError:
            return "missing"
        if (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino):
            return "initializing"
        return "locked"
    finally:
        if lock_fd >= 0:
            os.close(lock_fd)


def _cleanup_partial_lock(path: Path, identity: tuple[int, int]) -> None:
    try:
        metadata = path.lstat()
        if (metadata.st_dev, metadata.st_ino) != identity:
            return
        token = path / LOCK_OWNER_TOKEN
        try:
            token.unlink()
        except FileNotFoundError:
            pass
        if (path.lstat().st_dev, path.lstat().st_ino) == identity:
            path.rmdir()
    except OSError:
        return


def _acquire_lock(path: Path, deadline: float) -> _OwnedLock:
    key = str(path)
    active = _active_lock_paths()
    if key in active:
        raise _transaction_error(
            "config_lock_reentrant",
            "config transactions are not reentrant",
            phase="lock_acquire",
        )
    while True:
        try:
            os.mkdir(path, PRIVATE_DIRECTORY_MODE)
            break
        except FileExistsError:
            state = _inspect_lock(path)
            if time.monotonic() >= deadline:
                raise _transaction_error(
                    "config_lock_timeout",
                    "config lock acquisition timed out",
                    phase="lock_acquire",
                )
            if state != "missing":
                time.sleep(
                    min(
                        LOCK_POLL_MS / 1000.0,
                        max(0.0, deadline - time.monotonic()),
                    )
                )
        except OSError as cause:
            raise _transaction_error(
                "config_lock_failed",
                "unable to create config lock",
                phase="lock_acquire",
                cause=cause,
            )

    identity = (-1, -1)
    try:
        os.chmod(path, PRIVATE_DIRECTORY_MODE, follow_symlinks=False)
        metadata = path.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != PRIVATE_DIRECTORY_MODE
        ):
            raise _transaction_error(
                "config_lock_unsafe",
                "created config lock is unsafe",
                phase="lock_acquire",
            )
        identity = (metadata.st_dev, metadata.st_ino)
        active.add(key)
        token = (secrets.token_hex(32) + "\n").encode("ascii")
        token_fd = os.open(
            path / LOCK_OWNER_TOKEN,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            PRIVATE_FILE_MODE,
        )
        try:
            os.fchmod(token_fd, PRIVATE_FILE_MODE)
            view = memoryview(token)
            while view:
                written = os.write(token_fd, view)
                if written <= 0:
                    raise OSError("short config lock token write")
                view = view[written:]
            os.fsync(token_fd)
        finally:
            os.close(token_fd)
        lock_fd = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            os.fsync(lock_fd)
        finally:
            os.close(lock_fd)
        return _OwnedLock(path, token, identity)
    except ConfigTransactionError:
        active.discard(key)
        if identity != (-1, -1):
            _cleanup_partial_lock(path, identity)
        raise
    except BaseException as cause:
        active.discard(key)
        if identity != (-1, -1):
            _cleanup_partial_lock(path, identity)
        raise _transaction_error(
            "config_lock_failed",
            "unable to publish config lock",
            phase="lock_acquire",
            cause=cause,
        )


def _release_lock(
    lock: _OwnedLock,
    failure_injector: Callable[[str], None] | None = None,
) -> bool:
    removed = False
    parent_fd = -1
    lock_fd = -1
    try:
        parent_fd = os.open(
            lock.path.parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        metadata = os.stat(
            lock.path.name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if (metadata.st_dev, metadata.st_ino) != lock.identity:
            raise _transaction_error(
                "config_lock_release_failed",
                "config lock identity changed before release",
                phase="lock_release",
            )
        lock_fd = os.open(
            lock.path.name,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        opened = os.fstat(lock_fd)
        if (opened.st_dev, opened.st_ino) != lock.identity:
            raise _transaction_error(
                "config_lock_release_failed",
                "config lock changed while opening for release",
                phase="lock_release",
            )
        token_fd = os.open(
            LOCK_OWNER_TOKEN,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=lock_fd,
        )
        try:
            token_metadata = os.fstat(token_fd)
            if (
                not stat.S_ISREG(token_metadata.st_mode)
                or token_metadata.st_uid != os.geteuid()
                or token_metadata.st_nlink != 1
                or stat.S_IMODE(token_metadata.st_mode) != PRIVATE_FILE_MODE
            ):
                raise _transaction_error(
                    "config_lock_release_failed",
                    "config lock token is unsafe during release",
                    phase="lock_release",
                )
            token = b""
            while len(token) <= 65:
                chunk = os.read(token_fd, 66 - len(token))
                if not chunk:
                    break
                token += chunk
        finally:
            os.close(token_fd)
        if token != lock.token:
            raise _transaction_error(
                "config_lock_release_failed",
                "config lock token changed before release",
                phase="lock_release",
            )
        os.unlink(LOCK_OWNER_TOKEN, dir_fd=lock_fd)
        current = os.stat(
            lock.path.name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if (current.st_dev, current.st_ino) != lock.identity:
            raise _transaction_error(
                "config_lock_release_failed",
                "config lock identity changed during release",
                phase="lock_release",
            )
        os.rmdir(lock.path.name, dir_fd=parent_fd)
        removed = True
        if failure_injector is not None:
            failure_injector("after_lock_remove")
        os.fsync(parent_fd)
        return True
    except ConfigTransactionError as error:
        error.lock_released = removed or error.lock_released
        raise
    except BaseException as cause:
        raise ConfigTransactionError(
            "config_lock_release_failed",
            "unable to release config lock",
            phase="lock_release",
            cause=cause,
            lock_released=removed,
        )
    finally:
        if lock_fd >= 0:
            os.close(lock_fd)
        if parent_fd >= 0:
            os.close(parent_fd)
        _active_lock_paths().discard(str(lock.path))


def _validated_deadline(timeout_ms: int | float) -> float:
    if (
        isinstance(timeout_ms, bool)
        or not isinstance(timeout_ms, (int, float))
        or not math.isfinite(float(timeout_ms))
    ):
        raise _transaction_error(
            "config_invalid_timeout",
            "config transaction timeout must be a finite number",
            phase="preflight",
        )
    return time.monotonic() + max(0.0, float(timeout_ms)) / 1000.0


@dataclass(frozen=True)
class _LayeredDiscovery:
    env_override: bool
    candidates: tuple[tuple[Path, _PathSnapshot | None], ...]
    base: _PathSnapshot | None
    layers: tuple[_PathSnapshot, ...]
    write: _PathSnapshot


def _same_optional_snapshot(
    left: _PathSnapshot | None,
    right: _PathSnapshot | None,
) -> bool:
    if left is None or right is None:
        return left is right
    return _same_path_snapshot(left, right)


def _same_layered_discovery(
    left: _LayeredDiscovery,
    right: _LayeredDiscovery,
) -> bool:
    if (
        left.env_override != right.env_override
        or len(left.candidates) != len(right.candidates)
        or len(left.layers) != len(right.layers)
        or not _same_optional_snapshot(left.base, right.base)
        or not _same_path_snapshot(left.write, right.write)
    ):
        return False
    for (left_path, left_snapshot), (right_path, right_snapshot) in zip(
        left.candidates,
        right.candidates,
        strict=True,
    ):
        if left_path != right_path or not _same_optional_snapshot(
            left_snapshot,
            right_snapshot,
        ):
            return False
    return all(
        _same_path_snapshot(left_layer, right_layer)
        for left_layer, right_layer in zip(left.layers, right.layers, strict=True)
    )


def _lexists(path: Path) -> bool:
    try:
        _absolute_lexical_path(path).lstat()
        return True
    except FileNotFoundError:
        return False
    except OSError as cause:
        raise _transaction_error(
            "config_path_unavailable",
            f"unable to inspect config candidate: {path}",
            phase="resolve",
            cause=cause,
        )


def _discover_layered_config(
    env_var: str,
    *,
    ensure_write_parent: bool,
) -> _LayeredDiscovery:
    env_path = os.environ.get(env_var, "").strip()
    if env_path:
        logical = Path(env_path).expanduser()
        if not _lexists(logical):
            raise _transaction_error(
                "config_path_unavailable",
                f"config file not found: {logical}",
                phase="resolve",
            )
        snapshot = _snapshot_path(logical, allow_missing_final=False)
        return _LayeredDiscovery(
            True,
            ((snapshot.logical_path, snapshot),),
            None,
            (snapshot,),
            snapshot,
        )

    base_path = _base_config_path()
    if not _lexists(base_path):
        raise _transaction_error(
            "config_path_unavailable",
            f"base config not found: {base_path}",
            phase="resolve",
        )
    base = _snapshot_path(base_path, allow_missing_final=False)
    candidate_rows: list[tuple[Path, _PathSnapshot | None]] = []
    for candidate in _candidate_paths():
        logical = _absolute_lexical_path(candidate)
        snapshot = (
            _snapshot_path(logical, allow_missing_final=False)
            if _lexists(logical)
            else None
        )
        candidate_rows.append((logical, snapshot))

    selected = next(
        (snapshot for _path, snapshot in candidate_rows if snapshot is not None),
        None,
    )
    if selected is None:
        default_path = Path("~/.config/opencode/opencode.json").expanduser()
        if ensure_write_parent:
            _ensure_write_parent(default_path)
        selected = _snapshot_path(default_path, allow_missing_final=True)

    merge_order = [base]
    merge_order.extend(
        snapshot
        for _path, snapshot in reversed(candidate_rows)
        if snapshot is not None
    )
    last_by_identity: dict[tuple[int, int], int] = {}
    for index, snapshot in enumerate(merge_order):
        assert snapshot.target is not None
        last_by_identity[(snapshot.target.dev, snapshot.target.ino)] = index
    layers = tuple(
        snapshot
        for index, snapshot in enumerate(merge_order)
        if snapshot.target is not None
        and last_by_identity[(snapshot.target.dev, snapshot.target.ino)] == index
    )
    return _LayeredDiscovery(
        False,
        tuple(candidate_rows),
        base,
        layers,
        selected,
    )


def _load_discovery(discovery: _LayeredDiscovery) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for layer in discovery.layers:
        merged = _deep_merge(merged, _read_snapshot_config(layer))
    return merged


def _canonical_path_key(path: Path) -> str:
    key = os.fspath(path)
    if sys.platform == "darwin":
        key = unicodedata.normalize("NFD", key).casefold()
    return key


def _same_target_authority(left: _PathSnapshot, right: _PathSnapshot) -> bool:
    if left.target is not None and right.target is not None:
        return _same_object(left.target, right.target)
    return left.canonical_path == right.canonical_path


def _ambiguous_missing_case_alias(
    left: _PathSnapshot,
    right: _PathSnapshot,
) -> bool:
    return (
        sys.platform == "darwin"
        and left.target is None
        and right.target is None
        and left.canonical_path != right.canonical_path
        and _canonical_path_key(left.canonical_path)
        == _canonical_path_key(right.canonical_path)
    )


def _target_authority_key(snapshot: _PathSnapshot) -> str:
    if snapshot.target is not None:
        return f"object:{snapshot.target.dev}:{snapshot.target.ino}"
    parent = dict(snapshot.directories).get(snapshot.canonical_path.parent)
    if parent is None:
        raise _transaction_error(
            "config_snapshot_changed",
            "missing config target has no verified parent authority",
            phase="resolve",
        )
    return (
        f"missing:{parent.dev}:{parent.ino}:"
        f"{_canonical_path_key(Path(snapshot.canonical_path.name))}"
    )


def _target_lock_keys(snapshot: _PathSnapshot) -> tuple[str, ...]:
    keys = {
        f"target-path:{_canonical_path_key(snapshot.canonical_path)}",
        f"target-authority:{_target_authority_key(snapshot)}",
    }
    return tuple(sorted(keys))


def _validate_participant_aliases(
    discovery: _LayeredDiscovery | None,
    direct_snapshots: Sequence[_PathSnapshot],
) -> None:
    if discovery is not None:
        protected = [*discovery.layers, discovery.write]
        if discovery.base is not None:
            protected.append(discovery.base)
        protected.extend(
            candidate
            for _path, candidate in discovery.candidates
            if candidate is not None
        )
        for snapshot in direct_snapshots:
            if any(
                _same_target_authority(candidate, snapshot)
                or _ambiguous_missing_case_alias(candidate, snapshot)
                for candidate in protected
            ):
                raise _transaction_error(
                    "config_alias_collision",
                    "a direct participant aliases a shared config candidate",
                    phase="resolve",
                )
            for candidate_path, candidate in discovery.candidates:
                if candidate is not None:
                    continue
                if _canonical_path_key(_absolute_lexical_path(candidate_path)) in {
                    _canonical_path_key(snapshot.logical_path),
                    _canonical_path_key(snapshot.canonical_path),
                }:
                    raise _transaction_error(
                        "config_alias_collision",
                        "a direct participant aliases a shared config candidate",
                        phase="resolve",
                    )
    for index, snapshot in enumerate(direct_snapshots):
        for other in direct_snapshots[index + 1 :]:
            if _ambiguous_missing_case_alias(snapshot, other):
                raise _transaction_error(
                    "config_alias_collision",
                    "direct participants have an ambiguous case-only target alias",
                    phase="resolve",
                )


def _target_lock_path(registry: Path, snapshot: _PathSnapshot) -> Path:
    return registry / _lock_name(_target_authority_key(snapshot))


def _remove_owned_stage(plan: _StagedConfig) -> None:
    if (
        plan.parent_fd < 0
        or plan.stage_name is None
        or plan.stage_identity is None
    ):
        return
    try:
        metadata = os.stat(
            plan.stage_name,
            dir_fd=plan.parent_fd,
            follow_symlinks=False,
        )
        if _same_object(_identity(metadata), plan.stage_identity):
            os.unlink(plan.stage_name, dir_fd=plan.parent_fd)
    except OSError:
        return


def _stage_configs(
    plans: Sequence[_StagedConfig],
    failure_injector: Callable[[str], None] | None,
) -> None:
    for plan in plans:
        if _json_values_equal(plan.before, plan.after):
            continue
        plan.payload = _serialize_config(plan.after)
        parent = plan.snapshot.canonical_path.parent
        try:
            plan.parent_fd = os.open(
                parent,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
            )
            parent_metadata = os.fstat(plan.parent_fd)
            _validate_write_parent(parent_metadata)
            expected_parent = dict(plan.snapshot.directories).get(parent)
            if expected_parent is None or not _same_object(
                _identity(parent_metadata), expected_parent
            ):
                raise _transaction_error(
                    "config_snapshot_changed",
                    "config target parent changed before staging",
                    phase="stage",
                )
            plan.stage_name = f"{STAGE_PREFIX}{secrets.token_hex(16)}"
            stage_fd = os.open(
                plan.stage_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                PRIVATE_FILE_MODE,
                dir_fd=plan.parent_fd,
            )
            try:
                os.fchmod(stage_fd, PRIVATE_FILE_MODE)
                stage_metadata = os.fstat(stage_fd)
                if (
                    not stat.S_ISREG(stage_metadata.st_mode)
                    or stage_metadata.st_uid != os.geteuid()
                    or stage_metadata.st_nlink != 1
                    or stat.S_IMODE(stage_metadata.st_mode) != PRIVATE_FILE_MODE
                ):
                    raise _transaction_error(
                        "config_stage_unsafe",
                        "config stage file is unsafe",
                        phase="stage",
                    )
                view = memoryview(plan.payload)
                while view:
                    written = os.write(stage_fd, view)
                    if written <= 0:
                        raise OSError("short config stage write")
                    view = view[written:]
                os.fsync(stage_fd)
                staged_metadata = os.fstat(stage_fd)
                if (
                    not stat.S_ISREG(staged_metadata.st_mode)
                    or staged_metadata.st_uid != os.geteuid()
                    or staged_metadata.st_nlink != 1
                    or stat.S_IMODE(staged_metadata.st_mode) != PRIVATE_FILE_MODE
                    or staged_metadata.st_size != len(plan.payload)
                ):
                    raise _transaction_error(
                        "config_stage_unsafe",
                        "config stage file changed while staging",
                        phase="stage",
                    )
                plan.stage_identity = _identity(staged_metadata)
            finally:
                os.close(stage_fd)
            if failure_injector is not None:
                failure_injector("after_stage_fsync")
                failure_injector(
                    f"after_stage_fsync:{plan.snapshot.canonical_path}"
                )
        except ConfigTransactionError:
            raise
        except BaseException as cause:
            raise _transaction_error(
                "config_stage_failed",
                "unable to stage config transaction",
                phase="stage",
                cause=cause,
            )


def _file_results(plans: Sequence[_StagedConfig]) -> tuple[ConfigFileCommitResult, ...]:
    return tuple(
        ConfigFileCommitResult(
            path=plan.logical_path,
            canonical_path=plan.snapshot.canonical_path,
            changed=not _json_values_equal(plan.before, plan.after),
            committed=plan.committed,
            durability=plan.durability,
        )
        for plan in plans
    )


def _validate_replace_inputs(plan: _StagedConfig) -> None:
    if plan.parent_fd < 0 or plan.stage_name is None or plan.stage_identity is None:
        raise _transaction_error(
            "config_stage_changed",
            "config stage is unavailable before replacement",
            phase="replace",
        )
    parent_metadata = os.fstat(plan.parent_fd)
    expected_parent = dict(plan.snapshot.directories).get(
        plan.snapshot.canonical_path.parent
    )
    if expected_parent is None or not _same_directory_identity(
        _identity(parent_metadata), expected_parent
    ):
        raise _transaction_error(
            "config_snapshot_changed",
            "config target parent changed before replacement",
            phase="replace",
        )
    try:
        stage_metadata = os.stat(
            plan.stage_name,
            dir_fd=plan.parent_fd,
            follow_symlinks=False,
        )
    except OSError as cause:
        raise _transaction_error(
            "config_stage_changed",
            "config stage changed before replacement",
            phase="replace",
            cause=cause,
        )
    if _identity(stage_metadata) != plan.stage_identity:
        raise _transaction_error(
            "config_stage_changed",
            "config stage identity changed before replacement",
            phase="replace",
        )

    try:
        target_metadata = os.stat(
            plan.snapshot.canonical_path.name,
            dir_fd=plan.parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        if plan.snapshot.target is not None:
            raise _transaction_error(
                "config_snapshot_changed",
                "config target disappeared before replacement",
                phase="replace",
            )
    except OSError as cause:
        raise _transaction_error(
            "config_snapshot_changed",
            "unable to inspect config target before replacement",
            phase="replace",
            cause=cause,
        )
    else:
        if plan.snapshot.target is None:
            raise _transaction_error(
                "config_snapshot_changed",
                "config target appeared before replacement",
                phase="replace",
            )
        _validate_config_target(target_metadata)
        if _identity(target_metadata) != plan.snapshot.target:
            raise _transaction_error(
                "config_snapshot_changed",
                "config target changed before replacement",
                phase="replace",
            )


def _commit_staged_configs(
    plans: Sequence[_StagedConfig],
    *,
    revalidate_all: Callable[[], None],
    revalidate_plan: Callable[[_StagedConfig], None],
    failure_injector: Callable[[str], None] | None,
) -> tuple[ConfigFileCommitResult, ...]:
    changed = [
        plan for plan in plans if not _json_values_equal(plan.before, plan.after)
    ]
    active_phase = "stage"
    try:
        _stage_configs(changed, failure_injector)
        active_phase = "pre_replace"
        revalidate_all()
        for plan in sorted(changed, key=lambda item: str(item.snapshot.canonical_path)):
            assert plan.parent_fd >= 0 and plan.stage_name is not None
            active_phase = "replace"
            if failure_injector is not None:
                failure_injector("before_replace")
                failure_injector(f"before_replace:{plan.snapshot.canonical_path}")
            revalidate_plan(plan)
            _validate_replace_inputs(plan)
            os.replace(
                plan.stage_name,
                plan.snapshot.canonical_path.name,
                src_dir_fd=plan.parent_fd,
                dst_dir_fd=plan.parent_fd,
            )
            plan.stage_name = None
            plan.committed = True
            plan.durability = "uncertain"
            if failure_injector is not None:
                failure_injector("after_replace")
                failure_injector(f"after_replace:{plan.snapshot.canonical_path}")

        active_phase = "directory_sync"
        parents: dict[Path, int] = {}
        for plan in changed:
            parents.setdefault(plan.snapshot.canonical_path.parent, plan.parent_fd)
        for parent, descriptor in sorted(parents.items(), key=lambda item: str(item[0])):
            if failure_injector is not None:
                failure_injector("before_directory_sync")
                failure_injector(f"before_directory_sync:{parent}")
            os.fsync(descriptor)
            for plan in changed:
                if plan.snapshot.canonical_path.parent == parent and plan.committed:
                    plan.durability = "synced"
        return _file_results(plans)
    except BaseException as cause:
        committed_count = sum(1 for plan in changed if plan.committed)
        all_committed = bool(changed) and committed_count == len(changed)
        results = _file_results(plans)
        if committed_count == 0:
            if isinstance(cause, ConfigTransactionError):
                cause.file_results = results
                raise
            raise ConfigTransactionError(
                "config_replace_failed"
                if active_phase == "replace"
                else "config_transaction_failed",
                "unable to replace config target"
                if active_phase == "replace"
                else "config transaction failed before replacement",
                phase=active_phase,
                cause=cause,
                file_results=results,
            )
        reason = (
            "committed_durability_uncertain" if all_committed else "partial_commit"
        )
        durability: Durability = "uncertain" if all_committed else "partial"
        raise ConfigTransactionError(
            reason,
            "config transaction failed after one or more replacements",
            phase=active_phase,
            committed=committed_count > 0,
            durability=durability,
            cause=cause,
            file_results=results,
        )
    finally:
        for plan in changed:
            _remove_owned_stage(plan)
            if plan.parent_fd >= 0:
                os.close(plan.parent_fd)
                plan.parent_fd = -1


def _candidate_paths() -> list[Path]:
    cwd = Path.cwd()
    home = Path("~").expanduser()
    return [
        cwd / ".opencode" / "my_opencode.jsonc",
        cwd / ".opencode" / "my_opencode.json",
        home / ".config" / "opencode" / "my_opencode.jsonc",
        home / ".config" / "opencode" / "my_opencode.json",
        home / ".config" / "opencode" / "opencode.jsonc",
        home / ".config" / "opencode" / "opencode.json",
    ]


def _base_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "opencode.json"


def layer_candidates(env_var: str = "OPENCODE_CONFIG_PATH") -> list[dict[str, Any]]:
    env_path = os.environ.get(env_var, "").strip()
    rows: list[dict[str, Any]] = []
    if env_path:
        path = Path(env_path).expanduser()
        rows.append(
            {
                "name": "env_override",
                "priority": 1,
                "path": str(path),
                "exists": path.exists(),
                "kind": "jsonc" if path.suffix == ".jsonc" else "json",
            }
        )
        return rows

    rows = [
        {
            "name": "project_jsonc",
            "priority": 2,
            "path": str(Path.cwd() / ".opencode" / "my_opencode.jsonc"),
            "exists": (Path.cwd() / ".opencode" / "my_opencode.jsonc").exists(),
            "kind": "jsonc",
        },
        {
            "name": "project_json",
            "priority": 3,
            "path": str(Path.cwd() / ".opencode" / "my_opencode.json"),
            "exists": (Path.cwd() / ".opencode" / "my_opencode.json").exists(),
            "kind": "json",
        },
        {
            "name": "user_jsonc",
            "priority": 4,
            "path": str(Path("~/.config/opencode/my_opencode.jsonc").expanduser()),
            "exists": Path("~/.config/opencode/my_opencode.jsonc")
            .expanduser()
            .exists(),
            "kind": "jsonc",
        },
        {
            "name": "user_json",
            "priority": 5,
            "path": str(Path("~/.config/opencode/my_opencode.json").expanduser()),
            "exists": Path("~/.config/opencode/my_opencode.json").expanduser().exists(),
            "kind": "json",
        },
        {
            "name": "legacy_jsonc",
            "priority": 6,
            "path": str(Path("~/.config/opencode/opencode.jsonc").expanduser()),
            "exists": Path("~/.config/opencode/opencode.jsonc").expanduser().exists(),
            "kind": "jsonc",
        },
        {
            "name": "legacy_json",
            "priority": 7,
            "path": str(Path("~/.config/opencode/opencode.json").expanduser()),
            "exists": Path("~/.config/opencode/opencode.json").expanduser().exists(),
            "kind": "json",
        },
        {
            "name": "bundled_base",
            "priority": 8,
            "path": str(_base_config_path()),
            "exists": _base_config_path().exists(),
            "kind": "json",
        },
    ]
    return rows


def resolve_write_path(env_var: str = "OPENCODE_CONFIG_PATH") -> Path:
    env_path = os.environ.get(env_var, "").strip()
    if env_path:
        return Path(env_path).expanduser()

    for path in _candidate_paths():
        if path.exists():
            return path

    return Path("~/.config/opencode/opencode.json").expanduser()


def load_layered_config(
    env_var: str = "OPENCODE_CONFIG_PATH",
) -> tuple[dict[str, Any], Path]:
    env_path = os.environ.get(env_var, "").strip()
    if env_path:
        path = Path(env_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        return _load_json_or_jsonc(path), path

    if not _base_config_path().exists():
        raise FileNotFoundError(f"Base config not found: {_base_config_path()}")

    merged = _load_json_or_jsonc(_base_config_path())
    for path in reversed(_candidate_paths()):
        if path.exists():
            merged = _deep_merge(merged, _load_json_or_jsonc(path))

    return merged, resolve_write_path(env_var=env_var)


def layering_report(env_var: str = "OPENCODE_CONFIG_PATH") -> dict[str, Any]:
    layers = layer_candidates(env_var=env_var)
    active = [layer for layer in layers if layer["exists"]]
    return {
        "env_override": os.environ.get(env_var, "").strip() or None,
        "layers": layers,
        "active_layers": active,
        "write_path": str(resolve_write_path(env_var=env_var)),
    }


def _snapshot_direct_participants(
    participants: Sequence[ConfigFileParticipant],
) -> list[_PathSnapshot]:
    snapshots: list[_PathSnapshot] = []
    for participant in participants:
        if not _lexists(participant.path):
            _ensure_write_parent(participant.path)
        snapshots.append(
            _snapshot_path(
                participant.path,
                allow_missing_final=not _lexists(participant.path),
            )
        )
    return snapshots


def _run_config_transaction(
    *,
    layered_mutator: Callable[[dict[str, Any]], None] | None,
    direct_participants: Sequence[ConfigFileParticipant],
    env_var: str,
    timeout_ms: int | float,
    failure_injector: Callable[[str], None] | None,
) -> ConfigTransactionResult:
    if layered_mutator is None and not direct_participants:
        raise _transaction_error(
            "config_invalid_transaction",
            "config transaction requires at least one participant",
            phase="preflight",
        )
    deadline = _validated_deadline(timeout_ms)
    registry = _lock_registry()
    namespace_lock = _acquire_lock(
        registry / _lock_name("namespace:layered-config"), deadline
    )
    target_locks: list[_OwnedLock] = []
    primary_error: ConfigTransactionError | None = None
    result: ConfigTransactionResult | None = None
    release_disposed = True
    release_failed = False
    try:
        while True:
            discovery = (
                _discover_layered_config(env_var, ensure_write_parent=True)
                if layered_mutator is not None
                else None
            )
            direct_snapshots = _snapshot_direct_participants(direct_participants)
            _validate_participant_aliases(discovery, direct_snapshots)
            all_snapshots = [*direct_snapshots]
            if discovery is not None:
                all_snapshots.append(discovery.write)
            lock_keys = {
                key for snapshot in all_snapshots for key in _target_lock_keys(snapshot)
            }
            target_locks = []
            for lock_key in sorted(lock_keys):
                target_locks.append(
                    _acquire_lock(
                        registry / _lock_name(lock_key),
                        deadline,
                    )
                )
            if failure_injector is not None:
                failure_injector("after_target_locks")

            confirmed_discovery = (
                _discover_layered_config(env_var, ensure_write_parent=False)
                if layered_mutator is not None
                else None
            )
            confirmed_direct = _snapshot_direct_participants(direct_participants)
            mappings_changed = len(confirmed_direct) != len(direct_snapshots) or any(
                not _same_path_snapshot(before, after)
                for before, after in zip(
                    direct_snapshots,
                    confirmed_direct,
                    strict=True,
                )
            )
            if discovery is None or confirmed_discovery is None:
                mappings_changed = mappings_changed or discovery is not confirmed_discovery
            else:
                mappings_changed = mappings_changed or not _same_layered_discovery(
                    discovery,
                    confirmed_discovery,
                )
            if mappings_changed:
                for lock in reversed(target_locks):
                    _release_lock(lock)
                target_locks = []
                if time.monotonic() >= deadline:
                    raise _transaction_error(
                        "config_lock_timeout",
                        "config target changed until the transaction deadline",
                        phase="resolve",
                    )
                continue
            _validate_participant_aliases(confirmed_discovery, confirmed_direct)
            discovery = confirmed_discovery
            direct_snapshots = confirmed_direct
            break

        plans: list[_StagedConfig] = []
        if layered_mutator is not None:
            assert discovery is not None
            before = _load_discovery(discovery)
            after = copy.deepcopy(before)
            returned = layered_mutator(after)
            if returned is not None:
                raise _transaction_error(
                    "config_invalid_mutator",
                    "layered config mutator must mutate in place and return None",
                    phase="mutate",
                )
            _validate_json_value(after)
            plans.append(
                _StagedConfig(
                    discovery.write.logical_path,
                    discovery.write,
                    before,
                    after,
                )
            )

        direct_groups: dict[
            str,
            tuple[_PathSnapshot, dict[str, Any], dict[str, Any]],
        ] = {}
        for participant, snapshot in zip(direct_participants, direct_snapshots, strict=True):
            authority = _target_authority_key(snapshot)
            if authority not in direct_groups:
                before = _read_snapshot_config(snapshot)
                direct_groups[authority] = (
                    snapshot,
                    before,
                    copy.deepcopy(before),
                )
            group_snapshot, before, after = direct_groups[authority]
            returned = participant.mutator(after)
            if returned is not None:
                raise _transaction_error(
                    "config_invalid_mutator",
                    "direct config mutator must mutate in place and return None",
                    phase="mutate",
                )
            _validate_json_value(after)
            direct_groups[authority] = (group_snapshot, before, after)
        for snapshot, before, after in direct_groups.values():
            plans.append(
                _StagedConfig(snapshot.logical_path, snapshot, before, after)
            )

        layered_plan = plans[0] if layered_mutator is not None else None

        def revalidate_all() -> None:
            if discovery is not None:
                current = _discover_layered_config(
                    env_var,
                    ensure_write_parent=False,
                )
                if not _same_layered_discovery(current, discovery):
                    raise _transaction_error(
                        "config_snapshot_changed",
                        "layered config changed after mutation",
                        phase="pre_replace",
                    )
            for expected in direct_snapshots:
                current = _snapshot_path(
                    expected.logical_path,
                    allow_missing_final=expected.target is None,
                )
                if not _same_path_snapshot(current, expected):
                    raise _transaction_error(
                        "config_snapshot_changed",
                        "direct config participant changed after mutation",
                        phase="pre_replace",
                    )

        def revalidate_plan(plan: _StagedConfig) -> None:
            if plan is layered_plan:
                assert discovery is not None
                current = _discover_layered_config(
                    env_var,
                    ensure_write_parent=False,
                )
                if not _same_layered_discovery(current, discovery):
                    raise _transaction_error(
                        "config_snapshot_changed",
                        "layered config changed immediately before replacement",
                        phase="replace",
                    )
                return
            current = _snapshot_path(
                plan.snapshot.logical_path,
                allow_missing_final=plan.snapshot.target is None,
            )
            if not _same_path_snapshot(current, plan.snapshot):
                raise _transaction_error(
                    "config_snapshot_changed",
                    "direct config participant changed immediately before replacement",
                    phase="replace",
                )

        file_results = _commit_staged_configs(
            plans,
            revalidate_all=revalidate_all,
            revalidate_plan=revalidate_plan,
            failure_injector=failure_injector,
        )
        changed = any(item.changed for item in file_results)
        committed = any(item.committed for item in file_results)
        durability: Durability = "not_committed"
        if committed:
            durability = (
                "synced"
                if all(
                    not item.changed or item.durability == "synced"
                    for item in file_results
                )
                else "uncertain"
            )
        result = ConfigTransactionResult(
            changed=changed,
            committed=committed,
            durability=durability,
            lock_released=False,
            files=file_results,
        )
    except ConfigTransactionError as error:
        primary_error = error
    except BaseException as cause:
        primary_error = _transaction_error(
            "config_transaction_failed",
            "config transaction failed",
            phase="transaction",
            cause=cause,
        )
    finally:
        locks = [*reversed(target_locks), namespace_lock]
        if failure_injector is not None:
            try:
                failure_injector("before_lock_release")
            except BaseException as cause:
                primary_error = primary_error or _transaction_error(
                    "config_lock_release_failed",
                    "config transaction lock release was interrupted",
                    phase="lock_release",
                    cause=cause,
                )
                release_failed = True
        for lock in locks:
            try:
                _release_lock(lock, failure_injector)
            except ConfigTransactionError as release_error:
                release_failed = True
                release_disposed = release_disposed and release_error.lock_released
                if primary_error is not None:
                    primary_error.secondary_reason_code = release_error.reason_code
                else:
                    committed = bool(result and result.committed)
                    primary_error = ConfigTransactionError(
                        "committed_lock_release_failed"
                        if committed
                        else "config_lock_release_failed",
                        "config lock release failed after transaction",
                        phase="lock_release",
                        committed=committed,
                        durability=result.durability if result else "not_committed",
                        lock_released=release_disposed,
                        cause=release_error,
                        file_results=result.files if result else (),
                    )

    if primary_error is not None:
        primary_error.lock_released = release_disposed
        raise primary_error
    if result is None:
        raise _transaction_error(
            "config_transaction_failed",
            "config transaction produced no result",
            phase="transaction",
        )
    return ConfigTransactionResult(
        changed=result.changed,
        committed=result.committed,
        durability=result.durability,
        lock_released=not release_failed,
        files=result.files,
    )


def edit_layered_config(
    mutator: Callable[[dict[str, Any]], None],
    *,
    env_var: str = "OPENCODE_CONFIG_PATH",
    direct_participants: Sequence[ConfigFileParticipant] = (),
    timeout_ms: int | float = LOCK_TIMEOUT_MS,
    _failure_injector: Callable[[str], None] | None = None,
) -> ConfigTransactionResult:
    return _run_config_transaction(
        layered_mutator=mutator,
        direct_participants=direct_participants,
        env_var=env_var,
        timeout_ms=timeout_ms,
        failure_injector=_failure_injector,
    )


def edit_config_batch(
    participants: Sequence[ConfigFileParticipant],
    *,
    timeout_ms: int | float = LOCK_TIMEOUT_MS,
    _failure_injector: Callable[[str], None] | None = None,
) -> ConfigTransactionResult:
    return _run_config_transaction(
        layered_mutator=None,
        direct_participants=participants,
        env_var="OPENCODE_CONFIG_PATH",
        timeout_ms=timeout_ms,
        failure_injector=_failure_injector,
    )


def save_config(data: dict[str, Any], path: Path) -> None:
    replacement = copy.deepcopy(data)

    def replace(current: dict[str, Any]) -> None:
        current.clear()
        current.update(copy.deepcopy(replacement))

    edit_config_batch((ConfigFileParticipant(path, replace),))


def provision_config_json(path: Path, data: dict[str, Any]) -> bool:
    replacement = copy.deepcopy(data)

    def replace(current: dict[str, Any]) -> None:
        current.clear()
        current.update(copy.deepcopy(replacement))

    result = edit_layered_config(
        lambda _config: None,
        direct_participants=(ConfigFileParticipant(path, replace),),
    )
    return result.changed


def _reject_exempt_candidate_alias(
    snapshot: _PathSnapshot,
    discovery: _LayeredDiscovery,
) -> None:
    protected = [*discovery.layers]
    protected.append(discovery.write)
    if discovery.base is not None:
        protected.append(discovery.base)
    protected.extend(
        candidate
        for _path, candidate in discovery.candidates
        if candidate is not None
    )
    if any(
        _same_target_authority(snapshot, candidate)
        or _ambiguous_missing_case_alias(snapshot, candidate)
        for candidate in protected
    ):
        raise _transaction_error(
            "config_alias_collision",
            "a provision path aliases a shared config candidate",
            phase="provision",
        )
    for candidate_path, candidate in discovery.candidates:
        if candidate is not None:
            continue
        if _canonical_path_key(_absolute_lexical_path(candidate_path)) in {
            _canonical_path_key(snapshot.logical_path),
            _canonical_path_key(snapshot.canonical_path),
        }:
            raise _transaction_error(
                "config_alias_collision",
                "a provision path aliases a shared config candidate",
                phase="provision",
            )


def append_exempt_text_line(
    path: Path,
    line: str,
    *,
    if_missing: bool = False,
    timeout_ms: int | float = LOCK_TIMEOUT_MS,
    _failure_injector: Callable[[str], None] | None = None,
) -> bool:
    payload = (line.rstrip("\r\n") + "\n").encode("utf-8", errors="strict")
    if len(payload) > 64 * 1024 or b"\x00" in payload:
        raise _transaction_error(
            "config_invalid_value",
            "exempt text line is unsafe or exceeds its byte limit",
            phase="preflight",
        )
    deadline = _validated_deadline(timeout_ms)
    registry = _lock_registry()
    lock = _acquire_lock(
        registry / _lock_name("namespace:layered-config"),
        deadline,
    )
    descriptor = -1
    parent_fd = -1
    primary_error: ConfigTransactionError | None = None
    changed = False
    committed = False
    durability: Durability = "not_committed"
    try:
        logical = _absolute_lexical_path(path)
        if not _lexists(logical):
            _ensure_write_parent(logical)
        snapshot = _snapshot_path(
            logical,
            allow_missing_final=not _lexists(logical),
        )
        discovery = _discover_layered_config(
            "OPENCODE_CONFIG_PATH",
            ensure_write_parent=True,
        )
        _reject_exempt_candidate_alias(snapshot, discovery)
        parent_fd = os.open(
            snapshot.canonical_path.parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        current = _snapshot_path(
            logical,
            allow_missing_final=snapshot.target is None,
        )
        confirmed_discovery = _discover_layered_config(
            "OPENCODE_CONFIG_PATH",
            ensure_write_parent=False,
        )
        if not _same_path_snapshot(current, snapshot) or not _same_layered_discovery(
            confirmed_discovery,
            discovery,
        ):
            raise _transaction_error(
                "config_snapshot_changed",
                "exempt text destination changed before append",
                phase="provision",
            )
        flags = (
            os.O_RDWR
            | os.O_APPEND
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        created = snapshot.target is None
        if created:
            flags |= os.O_CREAT | os.O_EXCL
        descriptor = os.open(
            snapshot.canonical_path.name,
            flags,
            PRIVATE_FILE_MODE,
            dir_fd=parent_fd,
        )
        metadata = os.fstat(descriptor)
        _validate_config_target(metadata)
        if snapshot.target is not None and _identity(metadata) != snapshot.target:
            raise _transaction_error(
                "config_snapshot_changed",
                "exempt text destination changed while opening",
                phase="provision",
            )
        if if_missing:
            if metadata.st_size > MAX_CONFIG_BYTES:
                raise _transaction_error(
                    "config_too_large",
                    "exempt text file exceeds its byte limit",
                    phase="provision",
                )
            os.lseek(descriptor, 0, os.SEEK_SET)
            existing = b""
            while len(existing) <= MAX_CONFIG_BYTES:
                chunk = os.read(
                    descriptor,
                    min(64 * 1024, MAX_CONFIG_BYTES + 1 - len(existing)),
                )
                if not chunk:
                    break
                existing += chunk
            if payload.rstrip(b"\n") in {
                item.rstrip(b"\r") for item in existing.splitlines()
            }:
                raise _NoProvisionChange
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short exempt text append")
            committed = True
            changed = True
            durability = "uncertain"
            view = view[written:]
        os.fsync(descriptor)
        if created:
            os.fsync(parent_fd)
        durability = "synced"
        if _failure_injector is not None:
            _failure_injector("after_append_sync")
    except _NoProvisionChange:
        pass
    except ConfigTransactionError as error:
        if committed:
            error.committed = True
            error.durability = durability
        primary_error = error
    except BaseException as cause:
        primary_error = ConfigTransactionError(
            "committed_durability_uncertain"
            if committed
            else "config_provision_failed",
            "exempt text append failed after writing bytes"
            if committed
            else "unable to append exempt text safely",
            phase="provision",
            committed=committed,
            durability=durability,
            cause=cause,
        )
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_fd >= 0:
            os.close(parent_fd)
        try:
            _release_lock(lock, _failure_injector)
        except ConfigTransactionError as release_error:
            if primary_error is not None:
                primary_error.secondary_reason_code = release_error.reason_code
                primary_error.lock_released = release_error.lock_released
            else:
                primary_error = ConfigTransactionError(
                    "committed_lock_release_failed"
                    if committed
                    else "config_lock_release_failed",
                    "config namespace lock release failed after exempt append",
                    phase="lock_release",
                    committed=committed,
                    durability=durability,
                    lock_released=release_error.lock_released,
                    cause=release_error,
                )
    if primary_error is not None:
        raise primary_error
    return changed


def provision_config_symlink(
    link_path: Path,
    target_path: Path,
    *,
    timeout_ms: int | float = LOCK_TIMEOUT_MS,
    _failure_injector: Callable[[str], None] | None = None,
) -> bool:
    deadline = _validated_deadline(timeout_ms)
    registry = _lock_registry()
    lock = _acquire_lock(
        registry / _lock_name("namespace:layered-config"),
        deadline,
    )
    changed = False
    committed = False
    primary_error: ConfigTransactionError | None = None
    try:
        logical_link = _absolute_lexical_path(link_path)
        _ensure_write_parent(logical_link)
        parent = logical_link.parent.resolve(strict=True)
        parent_metadata = parent.lstat()
        _validate_write_parent(parent_metadata)
        _validate_ancestor_namespace(parent)
        try:
            target_path.expanduser().resolve(strict=True)
        except OSError as cause:
            raise _transaction_error(
                "config_path_unavailable",
                "config symlink target is unavailable",
                phase="provision",
                cause=cause,
            )
        raw_target = os.fspath(target_path.expanduser())
        try:
            existing = logical_link.lstat()
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if not stat.S_ISLNK(existing.st_mode):
                raise _transaction_error(
                    "config_provision_refused",
                    "config provisioner refuses to replace a non-symlink",
                    phase="provision",
                )
            if os.readlink(logical_link) == raw_target:
                raise _NoProvisionChange

        parent_fd = os.open(
            parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        stage_name = f".my-opencode-link.stage-{secrets.token_hex(16)}"
        try:
            os.symlink(raw_target, stage_name, dir_fd=parent_fd)
            changed = True
            if _failure_injector is not None:
                _failure_injector("before_symlink_replace")
            os.replace(
                stage_name,
                logical_link.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            stage_name = ""
            committed = True
            if _failure_injector is not None:
                _failure_injector("after_symlink_replace")
            os.fsync(parent_fd)
        except BaseException as cause:
            if stage_name:
                try:
                    os.unlink(stage_name, dir_fd=parent_fd)
                except OSError:
                    pass
            if committed:
                raise ConfigTransactionError(
                    "committed_durability_uncertain",
                    "config symlink was replaced but parent durability is uncertain",
                    phase="directory_sync",
                    committed=True,
                    durability="uncertain",
                    cause=cause,
                )
            if isinstance(cause, ConfigTransactionError):
                raise
            raise _transaction_error(
                "config_provision_failed",
                "unable to provision config symlink",
                phase="provision",
                cause=cause,
            )
        finally:
            os.close(parent_fd)
    except _NoProvisionChange:
        pass
    except ConfigTransactionError as error:
        primary_error = error
    finally:
        try:
            _release_lock(lock, _failure_injector)
        except ConfigTransactionError as release_error:
            if primary_error is not None:
                primary_error.secondary_reason_code = release_error.reason_code
                primary_error.lock_released = release_error.lock_released
            else:
                primary_error = ConfigTransactionError(
                    "committed_lock_release_failed"
                    if committed
                    else "config_lock_release_failed",
                    "config namespace lock release failed after provisioning",
                    phase="lock_release",
                    committed=committed,
                    durability="synced" if committed else "not_committed",
                    lock_released=release_error.lock_released,
                    cause=release_error,
                )
    if primary_error is not None:
        raise primary_error
    return changed


def provision_config_move(
    source_path: Path,
    target_path: Path,
    *,
    timeout_ms: int | float = LOCK_TIMEOUT_MS,
    _failure_injector: Callable[[str], None] | None = None,
) -> bool:
    deadline = _validated_deadline(timeout_ms)
    registry = _lock_registry()
    lock = _acquire_lock(
        registry / _lock_name("namespace:layered-config"),
        deadline,
    )
    committed = False
    durability: Durability = "not_committed"
    primary_error: ConfigTransactionError | None = None
    changed = False
    source_fd = -1
    target_fd = -1
    try:
        source_logical = _absolute_lexical_path(source_path)
        target_logical = _absolute_lexical_path(target_path)
        if not _lexists(source_logical):
            raise _NoProvisionChange
        if source_logical.is_symlink():
            raise _transaction_error(
                "config_provision_refused",
                "config migration refuses a final source symlink",
                phase="provision",
            )
        _ensure_write_parent(target_logical)
        source = _snapshot_path(source_logical, allow_missing_final=False)
        target = _snapshot_path(
            target_logical,
            allow_missing_final=not _lexists(target_logical),
        )
        if _same_target_authority(source, target):
            raise _NoProvisionChange
        discovery = _discover_layered_config(
            "OPENCODE_CONFIG_PATH",
            ensure_write_parent=True,
        )
        _reject_exempt_candidate_alias(source, discovery)
        _reject_exempt_candidate_alias(target, discovery)

        source_parent = source.canonical_path.parent
        target_parent = target.canonical_path.parent
        source_fd = os.open(
            source_parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        target_fd = os.open(
            target_parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        if _failure_injector is not None:
            _failure_injector("before_provision_move")
        current_source = _snapshot_path(source_logical, allow_missing_final=False)
        current_target = _snapshot_path(
            target_logical,
            allow_missing_final=target.target is None,
        )
        current_discovery = _discover_layered_config(
            "OPENCODE_CONFIG_PATH",
            ensure_write_parent=False,
        )
        if (
            not _same_path_snapshot(current_source, source)
            or not _same_path_snapshot(current_target, target)
            or not _same_layered_discovery(current_discovery, discovery)
        ):
            raise _transaction_error(
                "config_snapshot_changed",
                "config migration path changed before replacement",
                phase="provision",
            )
        _reject_exempt_candidate_alias(current_source, current_discovery)
        _reject_exempt_candidate_alias(current_target, current_discovery)
        expected_source_parent = dict(source.directories).get(source_parent)
        expected_target_parent = dict(target.directories).get(target_parent)
        if (
            expected_source_parent is None
            or expected_target_parent is None
            or not _same_directory_identity(
                _identity(os.fstat(source_fd)), expected_source_parent
            )
            or not _same_directory_identity(
                _identity(os.fstat(target_fd)), expected_target_parent
            )
        ):
            raise _transaction_error(
                "config_snapshot_changed",
                "config migration parent changed before replacement",
                phase="provision",
            )
        source_metadata = os.stat(
            source.canonical_path.name,
            dir_fd=source_fd,
            follow_symlinks=False,
        )
        if source.target is None or _identity(source_metadata) != source.target:
            raise _transaction_error(
                "config_snapshot_changed",
                "config migration source changed before replacement",
                phase="provision",
            )
        try:
            target_metadata = os.stat(
                target.canonical_path.name,
                dir_fd=target_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            if target.target is not None:
                raise _transaction_error(
                    "config_snapshot_changed",
                    "config migration target disappeared before replacement",
                    phase="provision",
                )
        else:
            if target.target is None or _identity(target_metadata) != target.target:
                raise _transaction_error(
                    "config_snapshot_changed",
                    "config migration target changed before replacement",
                    phase="provision",
                )
        os.replace(
            source.canonical_path.name,
            target.canonical_path.name,
            src_dir_fd=source_fd,
            dst_dir_fd=target_fd,
        )
        committed = True
        changed = True
        durability = "uncertain"
        if _failure_injector is not None:
            _failure_injector("after_provision_move")
        os.fsync(target_fd)
        if source_parent != target_parent:
            os.fsync(source_fd)
        durability = "synced"
    except _NoProvisionChange:
        pass
    except ConfigTransactionError as error:
        primary_error = error
    except BaseException as cause:
        primary_error = ConfigTransactionError(
            "committed_durability_uncertain"
            if committed
            else "config_provision_failed",
            "config migration failed after replacement"
            if committed
            else "unable to migrate config state",
            phase="directory_sync" if committed else "provision",
            committed=committed,
            durability=durability,
            cause=cause,
        )
    finally:
        if target_fd >= 0:
            os.close(target_fd)
        if source_fd >= 0:
            os.close(source_fd)
        try:
            _release_lock(lock, _failure_injector)
        except ConfigTransactionError as release_error:
            if primary_error is not None:
                primary_error.secondary_reason_code = release_error.reason_code
                primary_error.lock_released = release_error.lock_released
            else:
                primary_error = ConfigTransactionError(
                    "committed_lock_release_failed"
                    if committed
                    else "config_lock_release_failed",
                    "config namespace lock release failed after migration",
                    phase="lock_release",
                    committed=committed,
                    durability=durability,
                    lock_released=release_error.lock_released,
                    cause=release_error,
                )
    if primary_error is not None:
        raise primary_error
    return changed


def _main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="config_layering.py")
    subparsers = parser.add_subparsers(dest="command", required=True)
    provision = subparsers.add_parser("provision-link")
    provision.add_argument("--link", required=True)
    provision.add_argument("--target", required=True)
    provision.add_argument("--json", action="store_true")
    migrate = subparsers.add_parser("provision-move")
    migrate.add_argument("--source", required=True)
    migrate.add_argument("--target", required=True)
    migrate.add_argument("--json", action="store_true")
    provision_json = subparsers.add_parser("provision-json")
    provision_json.add_argument("--path", required=True)
    json_source = provision_json.add_mutually_exclusive_group(required=True)
    json_source.add_argument("--content")
    json_source.add_argument("--source")
    provision_json.add_argument("--json", action="store_true")
    provision_line = subparsers.add_parser("provision-line")
    provision_line.add_argument("--path", required=True)
    provision_line.add_argument("--line", required=True)
    provision_line.add_argument("--if-missing", action="store_true")
    provision_line.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv))
    if args.command == "provision-link":
        changed = provision_config_symlink(Path(args.link), Path(args.target))
        payload = {
            "result": "PASS",
            "changed": changed,
            "link": str(_absolute_lexical_path(Path(args.link))),
            "target": str(Path(args.target).expanduser()),
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"link: {payload['link']}")
            print(f"target: {payload['target']}")
            print(f"changed: {'yes' if changed else 'no'}")
        return 0
    if args.command == "provision-move":
        changed = provision_config_move(Path(args.source), Path(args.target))
        payload = {
            "result": "PASS",
            "changed": changed,
            "source": str(_absolute_lexical_path(Path(args.source))),
            "target": str(_absolute_lexical_path(Path(args.target))),
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"source: {payload['source']}")
            print(f"target: {payload['target']}")
            print(f"changed: {'yes' if changed else 'no'}")
        return 0
    if args.command == "provision-json":
        if args.source:
            data = _load_json_or_jsonc(Path(args.source).expanduser())
        else:
            data = _parse_config_text(str(args.content), Path("<content>"))
        changed = provision_config_json(Path(args.path), data)
        payload = {
            "result": "PASS",
            "changed": changed,
            "path": str(_absolute_lexical_path(Path(args.path))),
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"path: {payload['path']}")
            print(f"changed: {'yes' if changed else 'no'}")
        return 0
    if args.command == "provision-line":
        changed = append_exempt_text_line(
            Path(args.path),
            args.line,
            if_missing=args.if_missing,
        )
        payload = {
            "result": "PASS",
            "changed": changed,
            "path": str(_absolute_lexical_path(Path(args.path))),
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"path: {payload['path']}")
            print(f"changed: {'yes' if changed else 'no'}")
        return 0
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(_main(sys.argv[1:]))
    except ConfigTransactionError as error:
        print(json.dumps(error.as_dict(), indent=2), file=sys.stderr)
        raise SystemExit(1)
