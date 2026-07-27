#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import math
import os
import re
import secrets
import stat
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Literal

STATE_RELATIVE_PATH = Path(".opencode") / "gateway-core.state.json"
STATE_DIRECTORY_NAME = ".opencode"
STATE_FILE_NAME = "gateway-core.state.json"
LOCK_DIRECTORY_NAME = "gateway-core.state.json.lock"
OWNER_TOKEN_NAME = "owner-token"
STAGE_PREFIX = ".gateway-core.state.json.stage-"
LOCK_TIMEOUT_MS = 2000
LOCK_POLL_MS = 20
MAX_STATE_BYTES = 4 * 1024 * 1024
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
TOKEN_RANDOM_BYTES = 32
TOKEN_TEXT_BYTES = 65
SUPPORTED_PLATFORMS = {"darwin", "linux"}
JSON_INDENT = 2
MAX_SAFE_INTEGER = 9_007_199_254_740_991
LOCK_RECOVERY_GUIDANCE = (
    "stop the gateway state owner, then manually remove the lock directory"
)

DomainName = Literal["activeLoop", "conciseMode"]
MutationMode = Literal["replace", "patch"]
FailureInjector = Callable[[str], None]
_TOKEN_RE = re.compile(rb"^[0-9a-f]{64}\n$")
_DOMAIN_KEYS: dict[DomainName, set[str]] = {
    "activeLoop": {
        "active",
        "sessionId",
        "objective",
        "doneCriteria",
        "ignoredCompletionCycles",
        "completionMode",
        "completionPromise",
        "iteration",
        "maxIterations",
        "startedAt",
    },
    "conciseMode": {
        "mode",
        "source",
        "sessionId",
        "activatedAt",
        "updatedAt",
    },
}
_ROOT_UPDATE_KEYS = {"lastUpdatedAt", "source"}
_ACTIVE_LOCKS = threading.local()


class GatewayStateProtocolError(RuntimeError):
    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        phase: str,
        committed: bool = False,
        durability: str = "not_committed",
        lock_released: bool = False,
        cause: BaseException | None = None,
        secondary_reason_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.phase = phase
        self.committed = committed
        self.durability = durability
        self.lock_released = lock_released
        self.cause_code = _cause_code(cause)
        self.secondary_reason_code = secondary_reason_code

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
        }


@dataclass(frozen=True)
class DomainMutation:
    value: Any
    mode: MutationMode = "replace"
    root_updates: dict[str, Any] | None = None


@dataclass(frozen=True)
class GatewayStateCommitResult:
    path: Path
    committed: bool
    durability: str
    lock_released: bool


@dataclass(frozen=True)
class GatewayStateTransactionResult:
    state: dict[str, Any]
    changed: bool
    commit: GatewayStateCommitResult | None


@dataclass
class _StateAuthority:
    root: Path
    directory: Path
    root_fd: int
    directory_fd: int | None


@dataclass(frozen=True)
class _FileSnapshot:
    dev: int
    ino: int
    mode: int
    nlink: int
    uid: int
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class _StateLock:
    key: str
    token: bytes
    dev: int
    ino: int


def _cause_code(cause: BaseException | None) -> str | None:
    if cause is None:
        return None
    value = getattr(cause, "errno", None)
    if value is not None:
        return str(value)
    return type(cause).__name__


def _error(
    reason_code: str,
    message: str,
    *,
    phase: str,
    cause: BaseException | None = None,
    committed: bool = False,
    durability: str = "not_committed",
) -> GatewayStateProtocolError:
    return GatewayStateProtocolError(
        reason_code,
        message,
        phase=phase,
        cause=cause,
        committed=committed,
        durability=durability,
    )


def _require_supported_platform() -> None:
    if sys.platform not in SUPPORTED_PLATFORMS:
        raise _error(
            "gateway_state_unsupported_platform",
            "gateway state persistence supports only Darwin and Linux",
            phase="preflight",
        )


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _file_read_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _validate_directory(metadata: os.stat_result, reason_code: str, label: str) -> None:
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise _error(
            reason_code,
            f"{label} must be current-user-owned and not group/world writable",
            phase="authority",
        )


def _open_verified_directory(
    path: Path, reason_code: str, label: str
) -> tuple[int, os.stat_result]:
    try:
        before = path.lstat()
        _validate_directory(before, reason_code, label)
        descriptor = os.open(path, _directory_flags())
    except GatewayStateProtocolError:
        raise
    except OSError as cause:
        raise _error(reason_code, f"unable to open {label}", phase="authority", cause=cause)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise _error(
                reason_code,
                f"{label} changed while opening",
                phase="authority",
            )
        _validate_directory(opened, reason_code, label)
        return descriptor, opened
    except BaseException:
        os.close(descriptor)
        raise


def _validate_ancestor_namespace(root: Path) -> None:
    child = root
    while True:
        parent = child.parent
        if parent == child:
            return
        try:
            parent_metadata = parent.lstat()
            child_metadata = child.lstat()
        except OSError as cause:
            raise _error(
                "gateway_state_unsafe_project_root",
                "gateway state ancestor namespace is unavailable",
                phase="authority",
                cause=cause,
            )
        if not stat.S_ISDIR(parent_metadata.st_mode) or not stat.S_ISDIR(
            child_metadata.st_mode
        ):
            raise _error(
                "gateway_state_unsafe_project_root",
                "gateway state ancestor namespace contains a non-directory",
                phase="authority",
            )
        if parent_metadata.st_uid not in {os.geteuid(), 0}:
            raise _error(
                "gateway_state_unsafe_project_root",
                "gateway state ancestor namespace has a foreign owner",
                phase="authority",
            )
        if stat.S_IMODE(parent_metadata.st_mode) & 0o022:
            sticky = bool(parent_metadata.st_mode & stat.S_ISVTX)
            protected_child = child_metadata.st_uid in {os.geteuid(), 0}
            if not sticky or not protected_child:
                raise _error(
                    "gateway_state_unsafe_project_root",
                    "gateway state ancestor namespace permits unsafe rename",
                    phase="authority",
                )
        child = parent


@contextmanager
def _state_authority(cwd: Path, *, create_directory: bool) -> Iterator[_StateAuthority]:
    _require_supported_platform()
    try:
        root = cwd.expanduser().resolve(strict=True)
    except OSError as cause:
        raise _error(
            "gateway_state_unsafe_project_root",
            "gateway state project root is unavailable",
            phase="authority",
            cause=cause,
        )
    _validate_ancestor_namespace(root)
    root_fd, _root_metadata = _open_verified_directory(
        root, "gateway_state_unsafe_project_root", "gateway state project root"
    )
    directory_fd: int | None = None
    directory = root / STATE_DIRECTORY_NAME
    try:
        try:
            metadata = os.stat(
                STATE_DIRECTORY_NAME, dir_fd=root_fd, follow_symlinks=False
            )
        except FileNotFoundError:
            if not create_directory:
                yield _StateAuthority(root, directory, root_fd, None)
                return
            try:
                try:
                    os.mkdir(
                        STATE_DIRECTORY_NAME,
                        PRIVATE_DIRECTORY_MODE,
                        dir_fd=root_fd,
                    )
                except FileExistsError:
                    pass
                else:
                    os.fsync(root_fd)
                metadata = os.stat(
                    STATE_DIRECTORY_NAME,
                    dir_fd=root_fd,
                    follow_symlinks=False,
                )
            except OSError as cause:
                raise _error(
                    "gateway_state_unsafe_directory",
                    "unable to create private gateway state directory",
                    phase="authority",
                    cause=cause,
                )
        _validate_directory(
            metadata, "gateway_state_unsafe_directory", "gateway state directory"
        )
        try:
            directory_fd = os.open(
                STATE_DIRECTORY_NAME, _directory_flags(), dir_fd=root_fd
            )
            opened = os.fstat(directory_fd)
        except OSError as cause:
            raise _error(
                "gateway_state_unsafe_directory",
                "unable to open gateway state directory",
                phase="authority",
                cause=cause,
            )
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise _error(
                "gateway_state_unsafe_directory",
                "gateway state directory changed while opening",
                phase="authority",
            )
        _validate_directory(
            opened, "gateway_state_unsafe_directory", "gateway state directory"
        )
        yield _StateAuthority(root, directory, root_fd, directory_fd)
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
        os.close(root_fd)


def gateway_state_path(cwd: Path) -> Path:
    return cwd / STATE_RELATIVE_PATH


def gateway_state_lock_path(cwd: Path) -> Path:
    return cwd / STATE_DIRECTORY_NAME / LOCK_DIRECTORY_NAME


def _snapshot(metadata: os.stat_result) -> _FileSnapshot:
    return _FileSnapshot(
        dev=metadata.st_dev,
        ino=metadata.st_ino,
        mode=metadata.st_mode,
        nlink=metadata.st_nlink,
        uid=metadata.st_uid,
        size=metadata.st_size,
        mtime_ns=metadata.st_mtime_ns,
    )


def _same_read_snapshot(before: _FileSnapshot, after: _FileSnapshot) -> bool:
    return (
        before.dev == after.dev
        and before.ino == after.ino
        and before.mode == after.mode
        and before.uid == after.uid
        and before.size == after.size
        and before.mtime_ns == after.mtime_ns
    )


def _validate_target(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != os.geteuid()
    ):
        raise _error(
            "gateway_state_unsafe_target",
            "gateway state target must be a current-user-owned single-link regular file",
            phase="read",
        )


def _validate_opened_target(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink not in {0, 1}
        or metadata.st_uid != os.geteuid()
    ):
        raise _error(
            "gateway_state_unsafe_target",
            "opened gateway state must be a current-user-owned regular file",
            phase="read",
        )


def _safe_parse_int(value: str) -> int:
    parsed = int(value)
    if abs(parsed) > MAX_SAFE_INTEGER:
        raise ValueError("integer exceeds cross-runtime safe range")
    return parsed


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _validate_json_value(value: Any) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise ValueError("integer exceeds cross-runtime safe range")
        return
    if isinstance(value, float):
        if not math.isfinite(value) or (value.is_integer() and abs(value) > MAX_SAFE_INTEGER):
            raise ValueError("number exceeds cross-runtime range")
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
    raise ValueError("value is not JSON-compatible")


def _read_all(descriptor: int, maximum_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while total <= maximum_bytes:
        chunk = os.read(descriptor, min(64 * 1024, maximum_bytes + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    if total > maximum_bytes:
        raise _error(
            "gateway_state_too_large",
            "gateway state exceeds its byte limit",
            phase="read",
        )
    return b"".join(chunks)


def _read_state(
    authority: _StateAuthority,
    failure_injector: FailureInjector | None = None,
) -> tuple[dict[str, Any], _FileSnapshot | None]:
    if authority.directory_fd is None:
        return {}, None
    try:
        descriptor = os.open(
            STATE_FILE_NAME,
            _file_read_flags(),
            dir_fd=authority.directory_fd,
        )
    except FileNotFoundError:
        return {}, None
    except OSError as cause:
        raise _error(
            "gateway_state_unsafe_target",
            "unable to open gateway state without following links",
            phase="read",
            cause=cause,
        )
    try:
        if failure_injector is not None:
            failure_injector("after_state_open")
        opened = os.fstat(descriptor)
        _validate_opened_target(opened)
        before = _snapshot(opened)
        if before.size > MAX_STATE_BYTES:
            raise _error(
                "gateway_state_too_large",
                "gateway state exceeds its byte limit",
                phase="read",
            )
        raw = _read_all(descriptor, MAX_STATE_BYTES)
        after = os.fstat(descriptor)
        if not _same_read_snapshot(before, _snapshot(after)) or len(raw) != before.size:
            raise _error(
                "gateway_state_target_changed",
                "gateway state changed while reading",
                phase="read",
            )
    finally:
        os.close(descriptor)
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as cause:
        raise _error(
            "gateway_state_invalid_utf8",
            "gateway state is not valid UTF-8",
            phase="parse",
            cause=cause,
        )
    try:
        payload = json.loads(
            text,
            parse_int=_safe_parse_int,
            parse_constant=_reject_constant,
        )
        _validate_json_value(payload)
    except (json.JSONDecodeError, RecursionError, ValueError) as cause:
        reason = (
            "gateway_state_number_unsupported"
            if "range" in str(cause) or "number" in str(cause)
            else "gateway_state_malformed_json"
        )
        raise _error(
            reason,
            "gateway state contains invalid cross-runtime JSON",
            phase="parse",
            cause=cause,
        )
    if not isinstance(payload, dict):
        raise _error(
            "gateway_state_root_not_object",
            "gateway state root must be a JSON object",
            phase="parse",
        )
    return payload, before


def load_gateway_state(
    cwd: Path, *, _failure_injector: FailureInjector | None = None
) -> dict[str, Any]:
    with _state_authority(cwd, create_directory=False) as authority:
        state, _snapshot_value = _read_state(authority, _failure_injector)
        return copy.deepcopy(state)


def _active_lock_set() -> set[str]:
    active = getattr(_ACTIVE_LOCKS, "paths", None)
    if active is None:
        active = set()
        _ACTIVE_LOCKS.paths = active
    return active


def _validate_lock_directory(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != PRIVATE_DIRECTORY_MODE
    ):
        raise _error(
            "gateway_state_lock_unsafe",
            "gateway state lock directory is unsafe",
            phase="lock_acquire",
        )


def _inspect_existing_lock(authority: _StateAuthority) -> str:
    assert authority.directory_fd is not None
    try:
        metadata = os.stat(
            LOCK_DIRECTORY_NAME,
            dir_fd=authority.directory_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return "missing"
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise _error(
            "gateway_state_lock_unsafe",
            "gateway state lock directory is unsafe",
            phase="lock_acquire",
        )
    if stat.S_IMODE(metadata.st_mode) != PRIVATE_DIRECTORY_MODE:
        return "initializing"
    try:
        lock_fd = os.open(
            LOCK_DIRECTORY_NAME,
            _directory_flags(),
            dir_fd=authority.directory_fd,
        )
    except FileNotFoundError:
        return "missing"
    except OSError as cause:
        raise _error(
            "gateway_state_lock_unsafe",
            "unable to open gateway state lock",
            phase="lock_acquire",
            cause=cause,
        )
    try:
        opened = os.fstat(lock_fd)
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            return "initializing"
        _validate_lock_directory(opened)
        try:
            token_metadata = os.stat(
                OWNER_TOKEN_NAME, dir_fd=lock_fd, follow_symlinks=False
            )
        except FileNotFoundError:
            return "initializing"
        if (
            not stat.S_ISREG(token_metadata.st_mode)
            or token_metadata.st_uid != os.geteuid()
            or token_metadata.st_nlink != 1
            or stat.S_IMODE(token_metadata.st_mode) & 0o077
            or token_metadata.st_size > TOKEN_TEXT_BYTES
        ):
            raise _error(
                "gateway_state_lock_unsafe",
                "gateway state lock token is unsafe",
                phase="lock_acquire",
            )
        if (
            stat.S_IMODE(token_metadata.st_mode) != PRIVATE_FILE_MODE
            or token_metadata.st_size < TOKEN_TEXT_BYTES
        ):
            return "initializing"
        try:
            token_fd = os.open(
                OWNER_TOKEN_NAME,
                _file_read_flags(),
                dir_fd=lock_fd,
            )
        except FileNotFoundError:
            return "initializing"
        try:
            opened_token = os.fstat(token_fd)
            if _snapshot(opened_token) != _snapshot(token_metadata):
                return "initializing"
            token = _read_all(token_fd, TOKEN_TEXT_BYTES)
            if _snapshot(os.fstat(token_fd)) != _snapshot(token_metadata):
                return "initializing"
        finally:
            os.close(token_fd)
        if not _TOKEN_RE.fullmatch(token):
            raise _error(
                "gateway_state_lock_unsafe",
                "gateway state lock token is malformed",
                phase="lock_acquire",
            )
        return "locked"
    finally:
        os.close(lock_fd)


def _cleanup_partial_owned_lock(
    authority: _StateAuthority, identity: tuple[int, int]
) -> None:
    assert authority.directory_fd is not None
    try:
        current = os.stat(
            LOCK_DIRECTORY_NAME,
            dir_fd=authority.directory_fd,
            follow_symlinks=False,
        )
        if (current.st_dev, current.st_ino) != identity:
            return
        lock_fd = os.open(
            LOCK_DIRECTORY_NAME,
            _directory_flags(),
            dir_fd=authority.directory_fd,
        )
        try:
            try:
                os.unlink(OWNER_TOKEN_NAME, dir_fd=lock_fd)
            except FileNotFoundError:
                pass
        finally:
            os.close(lock_fd)
        current = os.stat(
            LOCK_DIRECTORY_NAME,
            dir_fd=authority.directory_fd,
            follow_symlinks=False,
        )
        if (current.st_dev, current.st_ino) == identity:
            os.rmdir(LOCK_DIRECTORY_NAME, dir_fd=authority.directory_fd)
    except OSError:
        return


def _acquire_lock(
    authority: _StateAuthority,
    *,
    timeout_ms: int,
    failure_injector: FailureInjector | None,
) -> _StateLock:
    assert authority.directory_fd is not None
    key = str(authority.directory / LOCK_DIRECTORY_NAME)
    active = _active_lock_set()
    if key in active:
        raise _error(
            "gateway_state_lock_reentrant",
            "gateway state transaction is not reentrant",
            phase="lock_acquire",
        )
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, (int, float)):
        raise _error(
            "gateway_state_invalid_timeout",
            "gateway state lock timeout must be a finite number",
            phase="lock_acquire",
        )
    numeric_timeout = float(timeout_ms)
    if not math.isfinite(numeric_timeout):
        raise _error(
            "gateway_state_invalid_timeout",
            "gateway state lock timeout must be a finite number",
            phase="lock_acquire",
        )
    deadline = time.monotonic() + max(0.0, numeric_timeout) / 1000.0
    while True:
        try:
            os.mkdir(
                LOCK_DIRECTORY_NAME,
                PRIVATE_DIRECTORY_MODE,
                dir_fd=authority.directory_fd,
            )
        except FileExistsError:
            state = _inspect_existing_lock(authority)
            if time.monotonic() >= deadline:
                raise _error(
                    "gateway_state_lock_timeout",
                    "gateway state lock acquisition timed out",
                    phase="lock_acquire",
                )
            if state == "missing":
                continue
            time.sleep(
                min(LOCK_POLL_MS / 1000.0, max(0.0, deadline - time.monotonic()))
            )
            continue
        except OSError as cause:
            raise _error(
                "gateway_state_io_failed",
                "unable to create gateway state lock",
                phase="lock_acquire",
                cause=cause,
            )
        break

    lock_fd = -1
    identity = (-1, -1)
    try:
        lock_fd = os.open(
            LOCK_DIRECTORY_NAME,
            _directory_flags(),
            dir_fd=authority.directory_fd,
        )
        os.fchmod(lock_fd, PRIVATE_DIRECTORY_MODE)
        metadata = os.fstat(lock_fd)
        _validate_lock_directory(metadata)
        identity = (metadata.st_dev, metadata.st_ino)
        active.add(key)
        token = (secrets.token_hex(TOKEN_RANDOM_BYTES) + "\n").encode("ascii")
        token_fd = os.open(
            OWNER_TOKEN_NAME,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            PRIVATE_FILE_MODE,
            dir_fd=lock_fd,
        )
        try:
            os.fchmod(token_fd, PRIVATE_FILE_MODE)
            view = memoryview(token)
            while view:
                view = view[os.write(token_fd, view) :]
            os.fsync(token_fd)
        finally:
            os.close(token_fd)
        os.fsync(lock_fd)
        if failure_injector is not None:
            failure_injector("after_lock_publish")
        current = os.stat(
            LOCK_DIRECTORY_NAME,
            dir_fd=authority.directory_fd,
            follow_symlinks=False,
        )
        if (current.st_dev, current.st_ino) != identity:
            raise _error(
                "gateway_state_lock_unsafe",
                "gateway state lock changed during publication",
                phase="lock_acquire",
            )
        return _StateLock(key, token, *identity)
    except GatewayStateProtocolError:
        active.discard(key)
        if identity != (-1, -1):
            _cleanup_partial_owned_lock(authority, identity)
        raise
    except BaseException as cause:
        active.discard(key)
        if identity != (-1, -1):
            _cleanup_partial_owned_lock(authority, identity)
        raise _error(
            "gateway_state_io_failed",
            "unable to publish gateway state lock",
            phase="lock_acquire",
            cause=cause,
        )
    finally:
        if lock_fd >= 0:
            os.close(lock_fd)


def _release_lock(
    authority: _StateAuthority,
    lock: _StateLock,
    failure_injector: FailureInjector | None = None,
) -> None:
    assert authority.directory_fd is not None
    removed = False
    try:
        metadata = os.stat(
            LOCK_DIRECTORY_NAME,
            dir_fd=authority.directory_fd,
            follow_symlinks=False,
        )
        if (metadata.st_dev, metadata.st_ino) != (lock.dev, lock.ino):
            raise _error(
                "gateway_state_lock_release_failed",
                "gateway state lock identity changed before release",
                phase="lock_release",
            )
        lock_fd = os.open(
            LOCK_DIRECTORY_NAME,
            _directory_flags(),
            dir_fd=authority.directory_fd,
        )
        try:
            opened = os.fstat(lock_fd)
            if (opened.st_dev, opened.st_ino) != (lock.dev, lock.ino):
                raise _error(
                    "gateway_state_lock_release_failed",
                    "gateway state lock changed while opening for release",
                    phase="lock_release",
                )
            token_fd = os.open(
                OWNER_TOKEN_NAME,
                _file_read_flags(),
                dir_fd=lock_fd,
            )
            try:
                token = _read_all(token_fd, TOKEN_TEXT_BYTES)
            finally:
                os.close(token_fd)
            if token != lock.token:
                raise _error(
                    "gateway_state_lock_release_failed",
                    "gateway state lock token changed before release",
                    phase="lock_release",
                )
            os.unlink(OWNER_TOKEN_NAME, dir_fd=lock_fd)
        finally:
            os.close(lock_fd)
        current = os.stat(
            LOCK_DIRECTORY_NAME,
            dir_fd=authority.directory_fd,
            follow_symlinks=False,
        )
        if (current.st_dev, current.st_ino) != (lock.dev, lock.ino):
            raise _error(
                "gateway_state_lock_release_failed",
                "gateway state lock identity changed during release",
                phase="lock_release",
            )
        os.rmdir(LOCK_DIRECTORY_NAME, dir_fd=authority.directory_fd)
        removed = True
        if failure_injector is not None:
            failure_injector("after_lock_remove")
        os.fsync(authority.directory_fd)
    except GatewayStateProtocolError:
        raise
    except OSError as cause:
        raise GatewayStateProtocolError(
            "gateway_state_lock_release_failed",
            "unable to release gateway state lock",
            phase="lock_release",
            cause=cause,
            lock_released=removed,
        )
    except BaseException as cause:
        raise GatewayStateProtocolError(
            "gateway_state_lock_release_failed",
            "unable to release gateway state lock",
            phase="lock_release",
            cause=cause,
            lock_released=removed,
        )
    finally:
        _active_lock_set().discard(lock.key)


def _snapshot_matches(authority: _StateAuthority, expected: _FileSnapshot | None) -> bool:
    assert authority.directory_fd is not None
    try:
        metadata = os.stat(
            STATE_FILE_NAME,
            dir_fd=authority.directory_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return expected is None
    if expected is None:
        return False
    try:
        _validate_target(metadata)
    except GatewayStateProtocolError:
        return False
    return _snapshot(metadata) == expected


def _remove_owned_stage(
    authority: _StateAuthority, name: str, identity: tuple[int, int]
) -> None:
    assert authority.directory_fd is not None
    try:
        current = os.stat(name, dir_fd=authority.directory_fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) == identity:
            os.unlink(name, dir_fd=authority.directory_fd)
    except OSError:
        return


def _serialize_state(state: dict[str, Any]) -> bytes:
    try:
        _validate_json_value(state)
        payload = (
            json.dumps(
                state,
                indent=JSON_INDENT,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as cause:
        raise _error(
            "gateway_state_number_unsupported",
            "gateway state cannot be represented safely across runtimes",
            phase="serialize",
            cause=cause,
        )
    if len(payload) > MAX_STATE_BYTES:
        raise _error(
            "gateway_state_too_large",
            "serialized gateway state exceeds its byte limit",
            phase="serialize",
        )
    return payload


def _commit_state(
    authority: _StateAuthority,
    state: dict[str, Any],
    expected: _FileSnapshot | None,
    failure_injector: FailureInjector | None,
) -> None:
    assert authority.directory_fd is not None
    payload = _serialize_state(state)
    stage_name = STAGE_PREFIX + secrets.token_hex(16)
    stage_fd = -1
    stage_identity = (-1, -1)
    committed = False
    try:
        stage_fd = os.open(
            stage_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            PRIVATE_FILE_MODE,
            dir_fd=authority.directory_fd,
        )
        os.fchmod(stage_fd, PRIVATE_FILE_MODE)
        stage_metadata = os.fstat(stage_fd)
        stage_identity = (stage_metadata.st_dev, stage_metadata.st_ino)
        if (
            not stat.S_ISREG(stage_metadata.st_mode)
            or stage_metadata.st_nlink != 1
            or stage_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(stage_metadata.st_mode) != PRIVATE_FILE_MODE
        ):
            raise _error(
                "gateway_state_stage_unsafe",
                "gateway state stage file is unsafe",
                phase="stage",
            )
        view = memoryview(payload)
        while view:
            view = view[os.write(stage_fd, view) :]
        os.fsync(stage_fd)
        if failure_injector is not None:
            failure_injector("after_stage_fsync")
        os.close(stage_fd)
        stage_fd = -1
        if not _snapshot_matches(authority, expected):
            raise _error(
                "gateway_state_target_changed",
                "gateway state changed before commit",
                phase="pre_replace",
            )
        os.replace(
            stage_name,
            STATE_FILE_NAME,
            src_dir_fd=authority.directory_fd,
            dst_dir_fd=authority.directory_fd,
        )
        committed = True
        if failure_injector is not None:
            failure_injector("after_replace")
        os.fsync(authority.directory_fd)
    except GatewayStateProtocolError as error:
        if committed:
            raise _error(
                "committed_durability_uncertain",
                "gateway state was committed but directory durability is uncertain",
                phase="directory_sync",
                cause=error,
                committed=True,
                durability="uncertain",
            )
        raise
    except BaseException as cause:
        if committed:
            raise _error(
                "committed_durability_uncertain",
                "gateway state was committed but directory durability is uncertain",
                phase="directory_sync",
                cause=cause,
                committed=True,
                durability="uncertain",
            )
        raise _error(
            "gateway_state_io_failed",
            "gateway state commit failed before replacement",
            phase="stage",
            cause=cause,
        )
    finally:
        if stage_fd >= 0:
            os.close(stage_fd)
        if not committed and stage_identity != (-1, -1):
            _remove_owned_stage(authority, stage_name, stage_identity)


def _merge_domain(
    domain: DomainName, current: Any, mutation: DomainMutation
) -> Any:
    if mutation.mode not in {"replace", "patch"}:
        raise _error(
            "gateway_state_invalid_domain_update",
            "gateway state mutation mode is invalid",
            phase="mutate",
        )
    if mutation.value is None:
        return None
    if not isinstance(mutation.value, dict):
        raise _error(
            "gateway_state_invalid_domain_update",
            "gateway state domain update must be an object or null",
            phase="mutate",
        )
    existing = copy.deepcopy(current) if isinstance(current, dict) else {}
    if mutation.mode == "patch":
        existing.update(copy.deepcopy(mutation.value))
        return existing
    unknown = {
        key: copy.deepcopy(value)
        for key, value in existing.items()
        if key not in _DOMAIN_KEYS[domain]
    }
    unknown.update(copy.deepcopy(mutation.value))
    return unknown


def mutate_gateway_state_domain(
    cwd: Path,
    domain: DomainName,
    mutator: Callable[[Any, dict[str, Any]], DomainMutation | None],
    *,
    timeout_ms: int = LOCK_TIMEOUT_MS,
    _failure_injector: FailureInjector | None = None,
) -> GatewayStateTransactionResult:
    if domain not in _DOMAIN_KEYS:
        raise _error(
            "gateway_state_invalid_domain_update",
            "gateway state transaction must select exactly one known domain",
            phase="mutate",
        )
    if (
        isinstance(timeout_ms, bool)
        or not isinstance(timeout_ms, (int, float))
        or not math.isfinite(float(timeout_ms))
    ):
        raise _error(
            "gateway_state_invalid_timeout",
            "gateway state lock timeout must be a finite number",
            phase="lock_acquire",
        )
    primary_error: GatewayStateProtocolError | None = None
    transaction_result: GatewayStateTransactionResult | None = None
    lock: _StateLock | None = None
    release_succeeded = False
    with _state_authority(cwd, create_directory=True) as authority:
        try:
            lock = _acquire_lock(
                authority,
                timeout_ms=timeout_ms,
                failure_injector=_failure_injector,
            )
            state, expected = _read_state(authority)
            mutation = mutator(copy.deepcopy(state.get(domain)), copy.deepcopy(state))
            if mutation is None:
                transaction_result = GatewayStateTransactionResult(
                    state=copy.deepcopy(state), changed=False, commit=None
                )
            else:
                root_updates = mutation.root_updates or {}
                if any(key not in _ROOT_UPDATE_KEYS for key in root_updates):
                    raise _error(
                        "gateway_state_invalid_domain_update",
                        "gateway state root update owns unsupported fields",
                        phase="mutate",
                    )
                next_state = copy.deepcopy(state)
                next_state[domain] = _merge_domain(
                    domain, state.get(domain), mutation
                )
                for key, value in root_updates.items():
                    if value is None and key == "source":
                        next_state.pop(key, None)
                    else:
                        next_state[key] = copy.deepcopy(value)
                _commit_state(
                    authority, next_state, expected, _failure_injector
                )
                transaction_result = GatewayStateTransactionResult(
                    state=copy.deepcopy(next_state),
                    changed=True,
                    commit=GatewayStateCommitResult(
                        path=authority.directory / STATE_FILE_NAME,
                        committed=True,
                        durability="synced",
                        lock_released=False,
                    ),
                )
        except GatewayStateProtocolError as error:
            primary_error = error
        except BaseException as cause:
            primary_error = _error(
                "gateway_state_io_failed",
                "gateway state transaction failed",
                phase="transaction",
                cause=cause,
            )
        finally:
            if lock is not None:
                try:
                    if _failure_injector is not None:
                        _failure_injector("before_lock_release")
                    _release_lock(authority, lock, _failure_injector)
                    release_succeeded = True
                except GatewayStateProtocolError as release_error:
                    _active_lock_set().discard(lock.key)
                    release_succeeded = release_error.lock_released
                    if primary_error is not None:
                        primary_error.secondary_reason_code = release_error.reason_code
                    else:
                        committed = bool(
                            transaction_result
                            and transaction_result.commit
                            and transaction_result.commit.committed
                        )
                        primary_error = GatewayStateProtocolError(
                            "committed_lock_release_failed"
                            if committed
                            else "gateway_state_lock_release_failed",
                            "gateway state lock release failed after transaction",
                            phase="lock_release",
                            committed=committed,
                            durability="synced" if committed else "not_committed",
                            lock_released=False,
                            cause=release_error,
                        )
                except BaseException as cause:
                    _active_lock_set().discard(lock.key)
                    committed = bool(
                        transaction_result
                        and transaction_result.commit
                        and transaction_result.commit.committed
                    )
                    release_error = _error(
                        "gateway_state_lock_release_failed",
                        "gateway state lock release failed",
                        phase="lock_release",
                        cause=cause,
                        committed=committed,
                        durability="synced" if committed else "not_committed",
                    )
                    if primary_error is not None:
                        primary_error.secondary_reason_code = release_error.reason_code
                    else:
                        primary_error = GatewayStateProtocolError(
                            "committed_lock_release_failed"
                            if committed
                            else "gateway_state_lock_release_failed",
                            "gateway state lock release failed after transaction",
                            phase="lock_release",
                            committed=committed,
                            durability="synced" if committed else "not_committed",
                            lock_released=False,
                            cause=cause,
                        )
        if primary_error is not None:
            primary_error.lock_released = release_succeeded
            raise primary_error
        if transaction_result is None:
            raise _error(
                "gateway_state_io_failed",
                "gateway state transaction produced no result",
                phase="transaction",
            )
        if transaction_result.commit is not None:
            transaction_result = GatewayStateTransactionResult(
                state=transaction_result.state,
                changed=True,
                commit=GatewayStateCommitResult(
                    path=transaction_result.commit.path,
                    committed=True,
                    durability="synced",
                    lock_released=release_succeeded,
                ),
            )
        return transaction_result


def update_gateway_state_domain(
    cwd: Path,
    domain: DomainName,
    value: Any,
    *,
    mode: MutationMode = "replace",
    root_updates: dict[str, Any] | None = None,
    timeout_ms: int = LOCK_TIMEOUT_MS,
    _failure_injector: FailureInjector | None = None,
) -> GatewayStateTransactionResult:
    return mutate_gateway_state_domain(
        cwd,
        domain,
        lambda _current, _state: DomainMutation(
            value=copy.deepcopy(value),
            mode=mode,
            root_updates=copy.deepcopy(root_updates) if root_updates else None,
        ),
        timeout_ms=timeout_ms,
        _failure_injector=_failure_injector,
    )


def gateway_state_lock_status(cwd: Path) -> dict[str, Any]:
    path = gateway_state_lock_path(cwd)
    try:
        with _state_authority(cwd, create_directory=False) as authority:
            if authority.directory_fd is None:
                return {
                    "path": str(path),
                    "present": False,
                    "safe": True,
                    "state": "missing",
                    "recovery_guidance": LOCK_RECOVERY_GUIDANCE,
                }
            state = _inspect_existing_lock(authority)
            return {
                "path": str(path),
                "present": state != "missing",
                "safe": True,
                "state": state,
                "recovery_guidance": LOCK_RECOVERY_GUIDANCE,
            }
    except GatewayStateProtocolError as error:
        return {
            "path": str(path),
            "present": path.lexists() if hasattr(path, "lexists") else os.path.lexists(path),
            "safe": False,
            "state": "unsafe",
            "reason_code": error.reason_code,
            "recovery_guidance": LOCK_RECOVERY_GUIDANCE,
        }
