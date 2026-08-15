#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from bounded_subprocess import BoundedCommandError, run_bounded  # type: ignore

FORMAT_VERSION = 1
JOURNAL_VERSION = 1
MAX_STATE_BYTES = 1024 * 1024
MAX_JOURNAL_BYTES = 64 * 1024
MAX_OC_OUTPUT_BYTES = 256 * 1024
MAX_CONFIG_BYTES = 1024 * 1024
SOURCE_DEADLINE_SECONDS = 8.0
MIN_TTL_SECONDS = 1
MAX_TTL_SECONDS = 24 * 60 * 60
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

DEFAULT_STATE_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_TASK_LEASE_PATH",
        "~/.config/opencode/my_opencode/runtime/codememory_task_leases.json",
    )
).expanduser()
DEFAULT_OC_BIN = os.environ.get("MY_OPENCODE_CODEMEMORY_BIN", "").strip() or "oc"
_configured_oc_config = os.environ.get("MY_OPENCODE_CODEMEMORY_CONFIG", "").strip()
DEFAULT_OC_CONFIG = (
    Path(_configured_oc_config).expanduser() if _configured_oc_config else None
)
DEFAULT_SCOPE = os.environ.get("MY_OPENCODE_CODEMEMORY_SCOPE", "").strip()

T = TypeVar("T")
Runner = Callable[[list[str], str], dict[str, Any]]
_CALLBACK_STATE = threading.local()
_FAULTED_PATHS: set[str] = set()
_FAULTED_PATHS_LOCK = threading.Lock()


class TaskLeaseError(RuntimeError):
    def __init__(
        self,
        reason_code: str,
        detail: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail
        self.context = context or {}


@dataclass(frozen=True)
class LeaseIdentity:
    task_id: str
    session_id: str
    owner: str
    worker_id: str
    lease_id: str
    fencing_token: int


@dataclass
class _LockedStore:
    state_path: Path
    lock_path: Path
    journal_path: Path
    fault_path: Path
    handle: Any
    marker: dict[str, Any]
    state_bytes: bytes | None
    state: dict[str, Any] | None


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _iso_from_ms(value: int) -> str:
    return (
        datetime.fromtimestamp(value / 1000, UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _require_token(value: str, name: str) -> str:
    normalized = value.strip()
    if not TOKEN_PATTERN.fullmatch(normalized):
        raise TaskLeaseError(
            "task_lease_argument_invalid",
            f"{name} must be a non-empty bounded identifier",
        )
    return normalized


def _require_scope(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 512 or "\x00" in normalized:
        raise TaskLeaseError(
            "task_lease_argument_invalid", "scope must be a non-empty bounded string"
        )
    return normalized


def _require_positive_int(value: Any, name: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise TaskLeaseError(
            "task_lease_state_invalid", f"{name} must be a positive integer"
        )
    if maximum is not None and value > maximum:
        raise TaskLeaseError(
            "task_lease_state_invalid", f"{name} exceeds its supported maximum"
        )
    return value


def _ttl_ms(ttl_seconds: int) -> int:
    if (
        isinstance(ttl_seconds, bool)
        or not isinstance(ttl_seconds, int)
        or ttl_seconds < MIN_TTL_SECONDS
        or ttl_seconds > MAX_TTL_SECONDS
    ):
        raise TaskLeaseError(
            "task_lease_argument_invalid",
            f"ttl seconds must be between {MIN_TTL_SECONDS} and {MAX_TTL_SECONDS}",
        )
    return ttl_seconds * 1000


def _require_supported_platform() -> None:
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise TaskLeaseError(
            "task_lease_platform_unsupported",
            "durable task leases require POSIX flock, O_NOFOLLOW, and directory fsync",
        )


def _path_key(path: Path) -> str:
    return str(path.expanduser().resolve(strict=False))


def _mark_process_faulted(path: Path) -> None:
    with _FAULTED_PATHS_LOCK:
        _FAULTED_PATHS.add(_path_key(path))


def _clear_process_fault(path: Path) -> None:
    with _FAULTED_PATHS_LOCK:
        _FAULTED_PATHS.discard(_path_key(path))


def _is_process_faulted(path: Path) -> bool:
    with _FAULTED_PATHS_LOCK:
        return _path_key(path) in _FAULTED_PATHS


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_private_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        metadata = path.lstat()
    except OSError as exc:
        raise TaskLeaseError("task_lease_state_path_unsafe", str(exc)) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise TaskLeaseError(
            "task_lease_state_path_unsafe",
            "task lease state directory must be a real directory",
        )
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise TaskLeaseError(
            "task_lease_state_path_unsafe",
            "task lease state directory must be owned by the current user",
        )
    try:
        os.chmod(path, 0o700)
    except OSError as exc:
        raise TaskLeaseError("task_lease_state_path_unsafe", str(exc)) from exc


def _open_regular_file(path: Path, flags: int, mode: int = 0o600) -> int:
    descriptor = os.open(
        path,
        flags | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        mode,
    )
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise TaskLeaseError(
                "task_lease_state_path_unsafe", f"not a regular file: {path.name}"
            )
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise TaskLeaseError(
                "task_lease_state_path_unsafe",
                f"file is not owned by the current user: {path.name}",
            )
        if metadata.st_mode & 0o077:
            raise TaskLeaseError(
                "task_lease_state_path_unsafe",
                f"file permissions are not owner-only: {path.name}",
            )
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _read_state_bytes(path: Path) -> bytes | None:
    try:
        descriptor = _open_regular_file(path, os.O_RDONLY)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise TaskLeaseError("task_lease_state_path_unsafe", str(exc)) from exc
    try:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, MAX_STATE_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_STATE_BYTES:
                raise TaskLeaseError(
                    "task_lease_state_invalid", "task lease state exceeds size limit"
                )
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _digest(payload: bytes | None) -> str | None:
    return hashlib.sha256(payload).hexdigest() if payload is not None else None


def _clean_marker(state_bytes: bytes | None) -> dict[str, Any]:
    return {
        "version": JOURNAL_VERSION,
        "status": "clean",
        "state_sha256": _digest(state_bytes),
    }


def _committing_marker(
    previous_bytes: bytes | None, next_bytes: bytes | None
) -> dict[str, Any]:
    return {
        "version": JOURNAL_VERSION,
        "status": "committing",
        "previous_sha256": _digest(previous_bytes),
        "next_sha256": _digest(next_bytes),
    }


def _serialize_journal(marker: dict[str, Any]) -> bytes:
    encoded = (json.dumps(marker, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    if len(encoded) > MAX_JOURNAL_BYTES:
        raise TaskLeaseError(
            "task_lease_journal_invalid", "task lease journal exceeds size limit"
        )
    return encoded


def _atomic_write_file(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        descriptor = _open_regular_file(path, os.O_RDONLY)
        os.close(descriptor)
    temporary_path: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        _fsync_directory(path.parent)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _remove_fault_marker(path: Path, payload: bytes) -> None:
    try:
        descriptor = _open_regular_file(path, os.O_RDONLY)
    except FileNotFoundError:
        return
    os.close(descriptor)
    path.unlink()
    try:
        _fsync_directory(path.parent)
    except Exception:
        with suppress(OSError, TaskLeaseError):
            _atomic_write_file(path, payload)
        raise


def _read_journal(path: Path) -> dict[str, Any] | None:
    try:
        descriptor = _open_regular_file(path, os.O_RDONLY)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise TaskLeaseError("task_lease_state_path_unsafe", str(exc)) from exc
    try:
        raw = os.read(descriptor, MAX_JOURNAL_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(raw) > MAX_JOURNAL_BYTES:
        raise TaskLeaseError(
            "task_lease_journal_invalid", "task lease journal exceeds size limit"
        )
    try:
        marker = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise TaskLeaseError(
            "task_lease_journal_invalid", "task lease journal is unreadable"
        ) from exc
    if not isinstance(marker, dict) or marker.get("version") != JOURNAL_VERSION:
        raise TaskLeaseError(
            "task_lease_journal_invalid", "task lease journal version is unsupported"
        )
    status = marker.get("status")
    if status == "clean":
        if set(marker) != {"version", "status", "state_sha256"}:
            raise TaskLeaseError(
                "task_lease_journal_invalid", "task lease clean journal is malformed"
            )
        digest = marker.get("state_sha256")
        if digest is not None and (
            not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest)
        ):
            raise TaskLeaseError(
                "task_lease_journal_invalid", "task lease journal digest is invalid"
            )
        return marker
    if status == "committing":
        if set(marker) != {
            "version",
            "status",
            "previous_sha256",
            "next_sha256",
        }:
            raise TaskLeaseError(
                "task_lease_journal_invalid",
                "task lease committing journal is malformed",
            )
        for field in ("previous_sha256", "next_sha256"):
            digest = marker.get(field)
            if digest is not None and (
                not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest)
            ):
                raise TaskLeaseError(
                    "task_lease_journal_invalid",
                    "task lease journal digest is invalid",
                )
        return marker
    raise TaskLeaseError(
        "task_lease_journal_invalid", "task lease journal status is unsupported"
    )


def _open_lock(state_path: Path) -> tuple[Any, bool, Path]:
    _require_supported_platform()
    state_path = state_path.expanduser().absolute()
    _ensure_private_directory(state_path.parent)
    lock_path = state_path.with_name(f"{state_path.name}.lock")
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(
            lock_path,
            flags | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        created = True
    except FileExistsError:
        try:
            descriptor = _open_regular_file(lock_path, os.O_RDWR)
        except OSError as exc:
            raise TaskLeaseError("task_lease_state_path_unsafe", str(exc)) from exc
        created = False
    try:
        os.fchmod(descriptor, 0o600)
        handle = os.fdopen(descriptor, "r+", encoding="utf-8", closefd=True)
    except Exception:
        os.close(descriptor)
        raise
    return handle, created, lock_path


@contextmanager
def _locked_store(
    state_path: Path, *, allow_indeterminate: bool = False
) -> Iterator[_LockedStore]:
    import fcntl

    state_key = _path_key(state_path)
    locked_paths = getattr(_CALLBACK_STATE, "locked_paths", None)
    if locked_paths is None:
        locked_paths = set()
        _CALLBACK_STATE.locked_paths = locked_paths
    if state_key in locked_paths:
        raise TaskLeaseError(
            "task_lease_reentry", "task lease storage must not re-enter its lock"
        )
    locked_paths.add(state_key)
    try:
        handle, created, lock_path = _open_lock(state_path)
    except Exception:
        locked_paths.discard(state_key)
        raise
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    except Exception:
        handle.close()
        locked_paths.discard(state_key)
        raise
    try:
        state_path = state_path.expanduser().absolute()
        state_bytes = _read_state_bytes(state_path)
        journal_path = state_path.with_name(f"{state_path.name}.journal")
        fault_path = state_path.with_name(f"{state_path.name}.fault")
        if created:
            try:
                _fsync_directory(state_path.parent)
            except Exception as exc:
                _mark_process_faulted(state_path)
                raise TaskLeaseError(
                    "task_lease_commit_indeterminate",
                    "task lease lock creation is not durably established",
                ) from exc
        try:
            marker = _read_journal(journal_path)
        except TaskLeaseError as exc:
            if not allow_indeterminate or exc.reason_code != "task_lease_journal_invalid":
                raise
            marker = _committing_marker(state_bytes, state_bytes)
        if marker is None:
            if state_bytes is None:
                marker = _clean_marker(None)
                try:
                    _atomic_write_file(journal_path, _serialize_journal(marker))
                except Exception as exc:
                    _mark_process_faulted(state_path)
                    raise TaskLeaseError(
                        "task_lease_commit_indeterminate",
                        "task lease journal creation is not durably established",
                    ) from exc
            else:
                marker = _committing_marker(None, state_bytes)
                if not allow_indeterminate:
                    raise TaskLeaseError(
                        "task_lease_commit_indeterminate",
                        "task lease journal is missing for existing state",
                    )
        process_faulted = _is_process_faulted(state_path)
        persistent_fault = fault_path.exists() or fault_path.is_symlink()
        if persistent_fault:
            descriptor = _open_regular_file(fault_path, os.O_RDONLY)
            os.close(descriptor)
        if marker["status"] != "clean" or process_faulted or persistent_fault:
            if not allow_indeterminate:
                raise TaskLeaseError(
                    "task_lease_commit_indeterminate",
                    "task lease storage has an indeterminate commit; run explicit recovery",
                )
        elif marker["state_sha256"] != _digest(state_bytes):
            raise TaskLeaseError(
                "task_lease_state_journal_mismatch",
                "task lease state does not match its durable journal",
            )
        state = _parse_state(state_bytes)
        yield _LockedStore(
            state_path=state_path,
            lock_path=lock_path,
            journal_path=journal_path,
            fault_path=fault_path,
            handle=handle,
            marker=marker,
            state_bytes=state_bytes,
            state=state,
        )
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
        locked_paths.discard(state_key)


def _parse_state(state_bytes: bytes | None) -> dict[str, Any] | None:
    if state_bytes is None:
        return None
    if not state_bytes:
        raise TaskLeaseError("task_lease_state_invalid", "task lease state is empty")
    try:
        payload = json.loads(state_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TaskLeaseError(
            "task_lease_state_invalid", "task lease state is unreadable"
        ) from exc
    if not isinstance(payload, dict):
        raise TaskLeaseError(
            "task_lease_state_invalid", "task lease state must be an object"
        )
    _validate_state(payload)
    return payload


def _validate_state(state: dict[str, Any]) -> None:
    expected = {
        "version",
        "scope",
        "backend_fingerprint",
        "clock_floor_ms",
        "epochs",
        "leases",
        "updated_at",
    }
    if set(state) != expected or state.get("version") != FORMAT_VERSION:
        raise TaskLeaseError(
            "task_lease_state_invalid", "task lease state schema is unsupported"
        )
    _require_scope(state.get("scope") if isinstance(state.get("scope"), str) else "")
    fingerprint = state.get("backend_fingerprint")
    if not isinstance(fingerprint, str) or not SHA256_PATTERN.fullmatch(fingerprint):
        raise TaskLeaseError(
            "task_lease_state_invalid", "backend fingerprint is invalid"
        )
    clock_floor = _require_positive_int(state.get("clock_floor_ms"), "clock_floor_ms")
    if not isinstance(state.get("updated_at"), str):
        raise TaskLeaseError("task_lease_state_invalid", "updated_at must be a string")
    epochs = state.get("epochs")
    leases = state.get("leases")
    if not isinstance(epochs, dict) or not isinstance(leases, dict):
        raise TaskLeaseError(
            "task_lease_state_invalid", "epochs and leases must be objects"
        )
    for task_id, epoch_value in epochs.items():
        _require_token(task_id if isinstance(task_id, str) else "", "epoch task id")
        _require_positive_int(epoch_value, f"epoch {task_id}")
    lease_keys = {
        "task_id",
        "session_id",
        "owner",
        "worker_id",
        "lease_id",
        "fencing_token",
        "issued_at_ms",
        "heartbeat_at_ms",
        "expires_at_ms",
        "source_sampled_at_ms",
    }
    for task_id, lease in leases.items():
        _require_token(task_id if isinstance(task_id, str) else "", "lease task id")
        if not isinstance(lease, dict) or set(lease) != lease_keys:
            raise TaskLeaseError(
                "task_lease_state_invalid", f"lease {task_id} has an invalid schema"
            )
        for field in ("task_id", "session_id", "owner", "worker_id", "lease_id"):
            value = lease.get(field)
            _require_token(value if isinstance(value, str) else "", field)
        if lease["task_id"] != task_id:
            raise TaskLeaseError(
                "task_lease_state_invalid", "lease key does not match task identity"
            )
        fence_value = _require_positive_int(
            lease.get("fencing_token"), "lease fencing_token"
        )
        if epochs.get(task_id) != fence_value:
            raise TaskLeaseError(
                "task_lease_state_invalid",
                "active lease token must equal the task epoch high-water mark",
            )
        issued = _require_positive_int(lease.get("issued_at_ms"), "issued_at_ms")
        heartbeat = _require_positive_int(
            lease.get("heartbeat_at_ms"), "heartbeat_at_ms"
        )
        expires = _require_positive_int(lease.get("expires_at_ms"), "expires_at_ms")
        sampled = _require_positive_int(
            lease.get("source_sampled_at_ms"), "source_sampled_at_ms"
        )
        if not (sampled <= issued <= heartbeat < expires) or heartbeat > clock_floor:
            raise TaskLeaseError(
                "task_lease_state_invalid", "lease timestamps are inconsistent"
            )


def _serialize_state(state: dict[str, Any]) -> bytes:
    _validate_state(state)
    encoded = (json.dumps(state, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(encoded) > MAX_STATE_BYTES:
        raise TaskLeaseError(
            "task_lease_state_invalid", "task lease state exceeds size limit"
        )
    return encoded


def _publish_clean_journal(store: _LockedStore, state_bytes: bytes | None) -> None:
    fault_payload = _serialize_journal(
        {
            "version": JOURNAL_VERSION,
            "status": "indeterminate",
            "state_sha256": _digest(state_bytes),
        }
    )
    _atomic_write_file(store.fault_path, fault_payload)
    _atomic_write_file(
        store.journal_path, _serialize_journal(_clean_marker(state_bytes))
    )
    _remove_fault_marker(store.fault_path, fault_payload)


def _commit_state(store: _LockedStore, state: dict[str, Any]) -> None:
    next_bytes = _serialize_state(state)
    committing = _committing_marker(store.state_bytes, next_bytes)
    try:
        _atomic_write_file(store.journal_path, _serialize_journal(committing))
        _atomic_write_file(store.state_path, next_bytes)
        _publish_clean_journal(store, next_bytes)
    except Exception as exc:
        _mark_process_faulted(store.state_path)
        if isinstance(exc, TaskLeaseError) and exc.reason_code == "task_lease_commit_indeterminate":
            raise
        raise TaskLeaseError(
            "task_lease_commit_indeterminate",
            "task lease commit durability is indeterminate; explicit recovery is required",
        ) from exc
    store.state = state
    store.state_bytes = next_bytes
    store.marker = _clean_marker(next_bytes)
    _clear_process_fault(store.state_path)


def _new_state(
    *, scope: str, backend_fingerprint: str, now_ms: int
) -> dict[str, Any]:
    return {
        "version": FORMAT_VERSION,
        "scope": scope,
        "backend_fingerprint": backend_fingerprint,
        "clock_floor_ms": now_ms,
        "epochs": {},
        "leases": {},
        "updated_at": _iso_from_ms(now_ms),
    }


def _check_clock(state: dict[str, Any], now_ms: int) -> None:
    floor = int(state["clock_floor_ms"])
    if now_ms < floor:
        raise TaskLeaseError(
            "task_lease_clock_rollback",
            "wall clock moved behind the persisted lease clock floor; stop workers and recover manually",
            context={"clock_floor_ms": floor, "observed_at_ms": now_ms},
        )


def _set_clock(state: dict[str, Any], now_ms: int) -> None:
    _check_clock(state, now_ms)
    state["clock_floor_ms"] = now_ms
    state["updated_at"] = _iso_from_ms(now_ms)


def _advance_clock_floor(store: _LockedStore, now_ms: int) -> None:
    if store.state is None:
        return
    _check_clock(store.state, now_ms)
    if now_ms == int(store.state["clock_floor_ms"]):
        return
    _set_clock(store.state, now_ms)
    _commit_state(store, store.state)


def _public_lease(lease: dict[str, Any], *, now_ms: int) -> dict[str, Any]:
    return {
        "task_id": lease["task_id"],
        "session_id": lease["session_id"],
        "owner": lease["owner"],
        "worker_id": lease["worker_id"],
        "lease_id": lease["lease_id"],
        "fencing_token": lease["fencing_token"],
        "issued_at": _iso_from_ms(lease["issued_at_ms"]),
        "heartbeat_at": _iso_from_ms(lease["heartbeat_at_ms"]),
        "expires_at": _iso_from_ms(lease["expires_at_ms"]),
        "source_sampled_at": _iso_from_ms(lease["source_sampled_at_ms"]),
        "expired": now_ms >= lease["expires_at_ms"],
    }


def _lease_identity(lease: dict[str, Any]) -> LeaseIdentity:
    return LeaseIdentity(
        task_id=str(lease["task_id"]),
        session_id=str(lease["session_id"]),
        owner=str(lease["owner"]),
        worker_id=str(lease["worker_id"]),
        lease_id=str(lease["lease_id"]),
        fencing_token=int(lease["fencing_token"]),
    )


def _validate_identity(identity: LeaseIdentity) -> LeaseIdentity:
    for field in ("task_id", "session_id", "owner", "worker_id", "lease_id"):
        _require_token(str(getattr(identity, field)), field)
    _require_positive_int(identity.fencing_token, "fencing_token")
    return identity


def _require_current_lease(
    state: dict[str, Any], identity: LeaseIdentity, *, now_ms: int
) -> dict[str, Any]:
    _validate_identity(identity)
    _check_clock(state, now_ms)
    lease = state["leases"].get(identity.task_id)
    if not isinstance(lease, dict):
        raise TaskLeaseError(
            "task_lease_not_found", f"no active lease exists for {identity.task_id}"
        )
    if _lease_identity(lease) != identity:
        raise TaskLeaseError(
            "task_lease_holder_mismatch",
            "lease identity or fencing token does not match the active holder",
        )
    if now_ms >= int(lease["expires_at_ms"]):
        raise TaskLeaseError(
            "task_lease_expired", "lease has expired and cannot be revived"
        )
    return lease


def make_oc_runner(*, oc_bin: str, config_path: Path, cwd: Path) -> Runner:
    config_path = config_path.expanduser().resolve()
    cwd = cwd.resolve()

    def run(arguments: list[str], operation: str) -> dict[str, Any]:
        command = [oc_bin, "--config", str(config_path), *arguments, "--format", "json"]
        run_options = {
            "cwd": cwd,
            "capture_output": True,
            "text": True,
            "max_output_bytes": MAX_OC_OUTPUT_BYTES,
        }
        try:
            if operation == "task_lease_codememory_doctor":
                completed = run_bounded(
                    command,
                    operation="task_lease_codememory_doctor",
                    **run_options,
                )
            elif operation == "task_lease_codememory_current":
                completed = run_bounded(
                    command,
                    operation="task_lease_codememory_current",
                    **run_options,
                )
            elif operation == "task_lease_codememory_get":
                completed = run_bounded(
                    command,
                    operation="task_lease_codememory_get",
                    **run_options,
                )
            else:
                raise ValueError(f"unsupported Codememory operation: {operation}")
        except BoundedCommandError as exc:
            raise TaskLeaseError(
                "task_lease_source_unavailable",
                "bounded Codememory source validation failed",
                context={"operation": operation, "source_reason_code": exc.reason_code},
            ) from exc
        stdout = str(completed.stdout or "")
        stderr = str(completed.stderr or "")
        if len(stdout.encode("utf-8")) > MAX_OC_OUTPUT_BYTES or len(
            stderr.encode("utf-8")
        ) > MAX_OC_OUTPUT_BYTES:
            raise TaskLeaseError(
                "task_lease_source_invalid",
                "Codememory source response exceeds the output limit",
                context={"operation": operation},
            )
        if completed.returncode != 0:
            raise TaskLeaseError(
                "task_lease_source_unavailable",
                "Codememory source validation returned a failure",
                context={"operation": operation},
            )
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise TaskLeaseError(
                "task_lease_source_invalid",
                "Codememory source returned invalid JSON",
                context={"operation": operation},
            ) from exc
        if not isinstance(payload, dict):
            raise TaskLeaseError(
                "task_lease_source_invalid",
                "Codememory source returned a non-object payload",
                context={"operation": operation},
            )
        return payload

    return run


def _config_sha256(path: Path) -> str:
    try:
        descriptor = os.open(
            path.expanduser().absolute(),
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError as exc:
        raise TaskLeaseError(
            "task_lease_source_unavailable", "Codememory config is unreadable"
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_CONFIG_BYTES:
            raise TaskLeaseError(
                "task_lease_source_unavailable",
                "Codememory config is not a bounded regular file",
            )
        digest = hashlib.sha256()
        previous_tail = b""
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            if b"${" in previous_tail + chunk:
                raise TaskLeaseError(
                    "task_lease_source_unsupported",
                    "Codememory config environment placeholders are not supported for lease authority",
                )
            digest.update(chunk)
            previous_tail = chunk[-1:]
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def validate_codememory_source(
    *,
    runner: Runner,
    config_path: Path,
    cwd: Path,
    scope: str,
    task_id: str,
    session_id: str,
) -> str:
    scope = _require_scope(scope)
    task_id = _require_token(task_id, "task_id")
    session_id = _require_token(session_id, "session_id")
    if "CODEMEMORY_SQLITE_PATH" in os.environ:
        raise TaskLeaseError(
            "task_lease_source_unsupported",
            "CODEMEMORY_SQLITE_PATH must be unset so the explicit config remains authoritative",
        )
    config_digest = _config_sha256(config_path)
    started = time.monotonic()
    doctor = runner(["config", "--doctor"], "task_lease_codememory_doctor")
    if time.monotonic() - started > SOURCE_DEADLINE_SECONDS:
        raise TaskLeaseError(
            "task_lease_source_unavailable", "Codememory source deadline exceeded"
        )
    if doctor.get("status") != "ok" or doctor.get("runtime_ready") is not True:
        raise TaskLeaseError(
            "task_lease_source_unavailable", "Codememory backend is not ready"
        )
    if doctor.get("backend") != "sqlite" or not isinstance(
        doctor.get("database_path"), str
    ):
        raise TaskLeaseError(
            "task_lease_backend_unsupported",
            "cooperative task leases currently require an explicit SQLite backend",
        )
    configured = doctor.get("config_path")
    if not isinstance(configured, str) or Path(configured).resolve() != config_path.resolve():
        raise TaskLeaseError(
            "task_lease_source_invalid", "Codememory doctor reported another config"
        )
    current = runner(
        ["current", "--scope", scope], "task_lease_codememory_current"
    )
    if time.monotonic() - started > SOURCE_DEADLINE_SECONDS:
        raise TaskLeaseError(
            "task_lease_source_unavailable", "Codememory source deadline exceeded"
        )
    expected_current = {
        "scope_key": scope,
        "worktree_path": str(cwd.resolve()),
        "session_id": session_id,
        "session_outcome": "active",
        "session_stale": False,
        "task_id": task_id,
    }
    if any(current.get(key) != value for key, value in expected_current.items()):
        raise TaskLeaseError(
            "task_lease_source_invalid",
            "Codememory current context does not match the requested active task holder",
        )
    task = runner(
        ["get", task_id, "--view", "full"], "task_lease_codememory_get"
    )
    if time.monotonic() - started > SOURCE_DEADLINE_SECONDS:
        raise TaskLeaseError(
            "task_lease_source_unavailable", "Codememory source deadline exceeded"
        )
    if (
        task.get("id") != task_id
        or task.get("type") != "task"
        or task.get("scope_key") != scope
        or task.get("status") != "doing"
    ):
        raise TaskLeaseError(
            "task_lease_source_invalid",
            "Codememory task is not doing in the requested scope",
        )
    current_recheck = runner(
        ["current", "--scope", scope], "task_lease_codememory_current"
    )
    if time.monotonic() - started > SOURCE_DEADLINE_SECONDS:
        raise TaskLeaseError(
            "task_lease_source_unavailable", "Codememory source deadline exceeded"
        )
    if any(
        current_recheck.get(key) != value
        for key, value in expected_current.items()
    ):
        raise TaskLeaseError(
            "task_lease_source_changed",
            "Codememory current context changed during lease admission",
        )
    if _config_sha256(config_path) != config_digest:
        raise TaskLeaseError(
            "task_lease_source_changed",
            "Codememory config changed during lease admission",
        )
    backend_identity = {
        "backend": doctor.get("backend"),
        "config_sha256": config_digest,
        "database_path": doctor.get("database_path"),
    }
    encoded = json.dumps(
        backend_identity, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def claim_lease(
    *,
    task_id: str,
    session_id: str,
    owner: str,
    worker_id: str,
    scope: str,
    ttl_seconds: int,
    runner: Runner,
    config_path: Path,
    cwd: Path,
    state_path: Path = DEFAULT_STATE_PATH,
    clock: Callable[[], int] = _now_ms,
) -> dict[str, Any]:
    task_id = _require_token(task_id, "task_id")
    session_id = _require_token(session_id, "session_id")
    owner = _require_token(owner, "owner")
    worker_id = _require_token(worker_id, "worker_id")
    scope = _require_scope(scope)
    ttl_ms = _ttl_ms(ttl_seconds)
    with _locked_store(state_path) as store:
        observed = clock()
        if store.state is not None:
            _advance_clock_floor(store, observed)
            if store.state["scope"] != scope:
                raise TaskLeaseError(
                    "task_lease_scope_mismatch",
                    "task lease store is bound to another Codememory scope",
                )
        backend_fingerprint = validate_codememory_source(
            runner=runner,
            config_path=config_path,
            cwd=cwd,
            scope=scope,
            task_id=task_id,
            session_id=session_id,
        )
        now_ms = clock()
        if store.state is not None:
            _advance_clock_floor(store, now_ms)
        state = store.state or _new_state(
            scope=scope, backend_fingerprint=backend_fingerprint, now_ms=now_ms
        )
        _check_clock(state, now_ms)
        if state["backend_fingerprint"] != backend_fingerprint:
            raise TaskLeaseError(
                "task_lease_backend_mismatch",
                "task lease store is bound to another Codememory backend",
            )
        current = state["leases"].get(task_id)
        if isinstance(current, dict) and now_ms < int(current["expires_at_ms"]):
            same_worker = (
                current["session_id"] == session_id
                and current["owner"] == owner
                and current["worker_id"] == worker_id
            )
            if same_worker:
                return {
                    "result": "PASS",
                    "command": "claim",
                    "reason_code": "task_lease_already_held",
                    "idempotent": True,
                    "reclaimed": False,
                    "lease": _public_lease(current, now_ms=now_ms),
                }
            raise TaskLeaseError(
                "task_lease_already_claimed",
                "task already has an unexpired lease",
                context={"task_id": task_id},
            )
        previous_epoch = int(state["epochs"].get(task_id, 0))
        fence_value = previous_epoch + 1
        lease = {
            "task_id": task_id,
            "session_id": session_id,
            "owner": owner,
            "worker_id": worker_id,
            "lease_id": uuid.uuid4().hex,
            "fencing_token": fence_value,
            "issued_at_ms": now_ms,
            "heartbeat_at_ms": now_ms,
            "expires_at_ms": now_ms + ttl_ms,
            "source_sampled_at_ms": now_ms,
        }
        state["epochs"][task_id] = fence_value
        state["leases"][task_id] = lease
        _set_clock(state, now_ms)
        _commit_state(store, state)
        return {
            "result": "PASS",
            "command": "claim",
            "reason_code": "task_lease_claimed",
            "idempotent": False,
            "reclaimed": isinstance(current, dict),
            "lease": _public_lease(lease, now_ms=now_ms),
        }


def heartbeat_lease(
    identity: LeaseIdentity,
    *,
    ttl_seconds: int,
    state_path: Path = DEFAULT_STATE_PATH,
    clock: Callable[[], int] = _now_ms,
) -> dict[str, Any]:
    ttl_ms = _ttl_ms(ttl_seconds)
    with _locked_store(state_path) as store:
        if store.state is None:
            raise TaskLeaseError("task_lease_not_found", "task lease store is empty")
        now_ms = clock()
        _advance_clock_floor(store, now_ms)
        lease = _require_current_lease(store.state, identity, now_ms=now_ms)
        lease["heartbeat_at_ms"] = now_ms
        lease["expires_at_ms"] = now_ms + ttl_ms
        _set_clock(store.state, now_ms)
        _commit_state(store, store.state)
        return {
            "result": "PASS",
            "command": "heartbeat",
            "reason_code": "task_lease_heartbeat_recorded",
            "lease": _public_lease(lease, now_ms=now_ms),
        }


def check_lease(
    identity: LeaseIdentity,
    *,
    state_path: Path = DEFAULT_STATE_PATH,
    clock: Callable[[], int] = _now_ms,
) -> dict[str, Any]:
    with _locked_store(state_path) as store:
        if store.state is None:
            raise TaskLeaseError("task_lease_not_found", "task lease store is empty")
        now_ms = clock()
        _advance_clock_floor(store, now_ms)
        lease = _require_current_lease(store.state, identity, now_ms=now_ms)
        return {
            "result": "PASS",
            "command": "check",
            "reason_code": "task_lease_valid",
            "lease": _public_lease(lease, now_ms=now_ms),
        }


def release_lease(
    identity: LeaseIdentity,
    *,
    state_path: Path = DEFAULT_STATE_PATH,
    clock: Callable[[], int] = _now_ms,
) -> dict[str, Any]:
    with _locked_store(state_path) as store:
        if store.state is None:
            raise TaskLeaseError("task_lease_not_found", "task lease store is empty")
        now_ms = clock()
        _advance_clock_floor(store, now_ms)
        lease = _require_current_lease(store.state, identity, now_ms=now_ms)
        public = _public_lease(lease, now_ms=now_ms)
        del store.state["leases"][identity.task_id]
        _set_clock(store.state, now_ms)
        _commit_state(store, store.state)
        return {
            "result": "PASS",
            "command": "release",
            "reason_code": "task_lease_released",
            "lease": public,
        }


def guarded_local_commit(
    identity: LeaseIdentity,
    callback: Callable[[], T],
    *,
    state_path: Path = DEFAULT_STATE_PATH,
    clock: Callable[[], int] = _now_ms,
) -> T:
    """Run one short local idempotent commit while the exact lease remains locked."""
    if getattr(_CALLBACK_STATE, "active", False):
        raise TaskLeaseError(
            "task_lease_reentry", "guarded lease commits must not re-enter"
        )
    with _locked_store(state_path) as store:
        if store.state is None:
            raise TaskLeaseError("task_lease_not_found", "task lease store is empty")
        now_ms = clock()
        _advance_clock_floor(store, now_ms)
        _require_current_lease(store.state, identity, now_ms=now_ms)
        _CALLBACK_STATE.active = True
        try:
            return callback()
        finally:
            _CALLBACK_STATE.active = False


def lease_status(
    *,
    task_id: str | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    clock: Callable[[], int] = _now_ms,
) -> dict[str, Any]:
    if task_id is not None:
        task_id = _require_token(task_id, "task_id")
    with _locked_store(state_path) as store:
        now_ms = clock()
        if store.state is None:
            return {
                "result": "PASS",
                "command": "status",
                "reason_code": "task_lease_store_empty",
                "count": 0,
                "leases": [],
            }
        _advance_clock_floor(store, now_ms)
        leases = [
            _public_lease(lease, now_ms=now_ms)
            for key, lease in sorted(store.state["leases"].items())
            if task_id is None or key == task_id
        ]
        return {
            "result": "PASS",
            "command": "status",
            "reason_code": "task_lease_status",
            "scope": store.state["scope"],
            "backend_fingerprint": store.state["backend_fingerprint"],
            "clock_floor": _iso_from_ms(store.state["clock_floor_ms"]),
            "count": len(leases),
            "leases": leases,
        }


def recover_indeterminate_store(
    *, state_path: Path = DEFAULT_STATE_PATH
) -> dict[str, Any]:
    with _locked_store(state_path, allow_indeterminate=True) as store:
        invalidated = 0
        if store.state is None:
            try:
                _publish_clean_journal(store, None)
            except Exception as exc:
                _mark_process_faulted(store.state_path)
                raise TaskLeaseError(
                    "task_lease_commit_indeterminate",
                    "task lease recovery could not establish durable state",
                ) from exc
            _clear_process_fault(store.state_path)
        else:
            invalidated = len(store.state["leases"])
            store.state["leases"] = {}
            _commit_state(store, store.state)
        return {
            "result": "PASS",
            "command": "doctor",
            "reason_code": "task_lease_indeterminate_recovered",
            "state_present": store.state is not None,
            "invalidated_lease_count": invalidated,
        }


def recover_clock_rollback(
    *,
    state_path: Path = DEFAULT_STATE_PATH,
    clock: Callable[[], int] = _now_ms,
) -> dict[str, Any]:
    with _locked_store(state_path) as store:
        if store.state is None:
            raise TaskLeaseError("task_lease_not_found", "task lease store is empty")
        now_ms = clock()
        if now_ms >= int(store.state["clock_floor_ms"]):
            raise TaskLeaseError(
                "task_lease_recovery_not_required",
                "observed clock is not behind the persisted clock floor",
            )
        invalidated = len(store.state["leases"])
        store.state["leases"] = {}
        store.state["clock_floor_ms"] = now_ms
        store.state["updated_at"] = _iso_from_ms(now_ms)
        _commit_state(store, store.state)
        return {
            "result": "PASS",
            "command": "doctor",
            "reason_code": "task_lease_clock_recovered",
            "invalidated_lease_count": invalidated,
        }


def lease_doctor(
    *,
    state_path: Path = DEFAULT_STATE_PATH,
    clock: Callable[[], int] = _now_ms,
) -> dict[str, Any]:
    report = lease_status(state_path=state_path, clock=clock)
    return {
        **report,
        "command": "doctor",
        "reason_code": "task_lease_healthy",
        "path": str(state_path.expanduser().absolute()),
        "limitations": [
            "single_host_cooperative_only",
            "source_authority_sampled_at_claim",
            "tokens_are_not_secrets",
            "external_effects_require_native_cas_or_idempotency",
        ],
    }


def _identity_from_args(args: argparse.Namespace) -> LeaseIdentity:
    return LeaseIdentity(
        task_id=args.task_id,
        session_id=args.session,
        owner=args.owner,
        worker_id=args.worker,
        lease_id=args.lease_id,
        fencing_token=args.fencing_token,
    )


def _add_identity_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("task_id")
    parser.add_argument("--session", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--worker", required=True)
    parser.add_argument("--lease-id", required=True)
    parser.add_argument("--fencing-token", required=True, type=int)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="/task-lease", description="Manage cooperative fenced Codememory task leases"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    claim = subparsers.add_parser("claim")
    claim.add_argument("task_id")
    claim.add_argument("--session", required=True)
    claim.add_argument("--owner", required=True)
    claim.add_argument("--worker", required=True)
    claim.add_argument("--scope", default=DEFAULT_SCOPE, required=not bool(DEFAULT_SCOPE))
    claim.add_argument("--ttl-seconds", type=int, default=300)

    heartbeat = subparsers.add_parser("heartbeat")
    _add_identity_arguments(heartbeat)
    heartbeat.add_argument("--ttl-seconds", type=int, default=300)

    for name in ("check", "release"):
        _add_identity_arguments(subparsers.add_parser(name))

    status = subparsers.add_parser("status")
    status.add_argument("--task")

    doctor = subparsers.add_parser("doctor")
    recovery = doctor.add_mutually_exclusive_group()
    recovery.add_argument("--recover-indeterminate", action="store_true")
    recovery.add_argument("--recover-clock", action="store_true")
    doctor.add_argument("--accept-current-state", action="store_true")

    for command in subparsers.choices.values():
        command.add_argument("--json", action="store_true")
    return parser


def _emit(payload: dict[str, Any], *, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif payload.get("result") == "PASS":
        print("result: PASS")
        print(f"reason_code: {payload.get('reason_code')}")
        lease = payload.get("lease")
        if isinstance(lease, dict):
            print(f"task_id: {lease.get('task_id')}")
            print(f"lease_id: {lease.get('lease_id')}")
            print(f"fencing_token: {lease.get('fencing_token')}")
            print(f"expires_at: {lease.get('expires_at')}")
        elif "count" in payload:
            print(f"count: {payload.get('count')}")
    else:
        print(f"error: {payload.get('error')}", file=sys.stderr)
        print(f"reason_code: {payload.get('reason_code')}", file=sys.stderr)
    return 0 if payload.get("result") == "PASS" else 1


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    as_json = bool(args.json)
    try:
        if args.command == "claim":
            if DEFAULT_OC_CONFIG is None:
                raise TaskLeaseError(
                    "task_lease_source_unavailable",
                    "MY_OPENCODE_CODEMEMORY_CONFIG must select an explicit config",
                )
            runner = make_oc_runner(
                oc_bin=DEFAULT_OC_BIN,
                config_path=DEFAULT_OC_CONFIG,
                cwd=Path.cwd(),
            )
            payload = claim_lease(
                task_id=args.task_id,
                session_id=args.session,
                owner=args.owner,
                worker_id=args.worker,
                scope=args.scope,
                ttl_seconds=args.ttl_seconds,
                runner=runner,
                config_path=DEFAULT_OC_CONFIG,
                cwd=Path.cwd(),
            )
        elif args.command == "heartbeat":
            payload = heartbeat_lease(
                _identity_from_args(args), ttl_seconds=args.ttl_seconds
            )
        elif args.command == "check":
            payload = check_lease(_identity_from_args(args))
        elif args.command == "release":
            payload = release_lease(_identity_from_args(args))
        elif args.command == "status":
            payload = lease_status(task_id=args.task)
        elif args.command == "doctor":
            if (args.recover_indeterminate or args.recover_clock) and not args.accept_current_state:
                raise TaskLeaseError(
                    "task_lease_recovery_confirmation_required",
                    "recovery requires --accept-current-state after all lease workers stop",
                )
            if args.recover_indeterminate:
                payload = recover_indeterminate_store()
            elif args.recover_clock:
                payload = recover_clock_rollback()
            else:
                payload = lease_doctor()
        else:
            parser.error("unsupported command")
            return 2
    except TaskLeaseError as exc:
        payload = {
            "result": "FAIL",
            "command": args.command,
            "reason_code": exc.reason_code,
            "error": exc.detail,
            **exc.context,
        }
    return _emit(payload, as_json=as_json)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
