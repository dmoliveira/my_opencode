#!/usr/bin/env python3

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import tempfile
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from config_layering import load_layered_config  # type: ignore


class SessionIndexError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        reason_code: str,
        corruption_kind: str | None = None,
        raw_bytes: bytes | None = None,
        quarantine: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.corruption_kind = corruption_kind
        self.raw_bytes = raw_bytes
        self.quarantine = quarantine


class SessionIndexCorruption(SessionIndexError):
    def __init__(self, corruption_kind: str, raw_bytes: bytes) -> None:
        label = corruption_kind.replace("_", " ")
        super().__init__(
            f"session index is corrupt ({label}); active file preserved",
            reason_code="session_index_corrupt",
            corruption_kind=corruption_kind,
            raw_bytes=raw_bytes,
        )


SESSION_INDEX_VERSION = 1
QUARANTINE_ENV = "MY_OPENCODE_SESSION_INDEX_QUARANTINE_DIR"
QUARANTINE_SUFFIX = ".bin"

CORRUPTION_RECOVERY_STEPS = [
    "stop session-index writers",
    "inspect the quarantine path and SHA-256 checksum locally",
    "repair or replace the active index from a verified source",
    "run /digest run --reason manual",
    "run /session doctor --json",
]


DEFAULT_INDEX_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_SESSION_INDEX_PATH", "~/.config/opencode/sessions/index.json"
    )
).expanduser()


def _parse_iso(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _quarantine_directory() -> Path:
    configured = os.environ.get(QUARANTINE_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    state_home = os.environ.get("XDG_STATE_HOME", "").strip()
    root = Path(state_home).expanduser() if state_home else Path("~/.local/state").expanduser()
    return root / "my_opencode" / "quarantine" / "session-index"


def _session_id(timestamp: str, cwd: str) -> str:
    explicit = os.environ.get("OPENCODE_SESSION_ID", "").strip()
    if explicit:
        return explicit
    ts = _parse_iso(timestamp) or _utc_now()
    return f"{cwd}::{ts.isoformat()}::{uuid.uuid4().hex}"


def _load_policy() -> dict[str, int]:
    policy = {
        "max_sessions": 120,
        "max_age_days": 30,
        "max_events_per_session": 24,
        "max_reasons_per_session": 12,
        "max_plan_ids_per_session": 12,
    }
    try:
        config, _ = load_layered_config()
    except Exception:
        return policy
    section = config.get("session_index")
    if not isinstance(section, dict):
        return policy
    for key in policy:
        value = section.get(key)
        if isinstance(value, int) and value > 0:
            policy[key] = value
    return policy


@contextmanager
def _index_write_lock(path: Path) -> Iterator[None]:
    """Serialize the sidecar load-modify-write transaction across supported hosts."""
    lock_path = path.with_name(f"{path.name}.lock")
    with lock_path.open("a+", encoding="utf-8") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            handle.write("0")
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _raise_corruption(kind: str, raw_bytes: bytes) -> None:
    raise SessionIndexCorruption(kind, raw_bytes)


def _parse_index_bytes(raw_bytes: bytes) -> dict[str, Any]:
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        _raise_corruption("invalid_utf8", raw_bytes)
    try:
        loaded = json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        _raise_corruption("malformed_json", raw_bytes)
    if not isinstance(loaded, dict):
        _raise_corruption("non_object_root", raw_bytes)

    if "version" in loaded:
        loaded_version = loaded["version"]
        if (
            not isinstance(loaded_version, int)
            or isinstance(loaded_version, bool)
            or loaded_version != SESSION_INDEX_VERSION
        ):
            raise SessionIndexError(
                "session index version is unsupported; migrate before writing",
                reason_code="session_index_unsupported_version",
            )

    if "sessions" not in loaded:
        _raise_corruption("sessions_missing", raw_bytes)
    raw_sessions = loaded["sessions"]
    if not isinstance(raw_sessions, list):
        _raise_corruption("sessions_not_list", raw_bytes)

    for session in raw_sessions:
        if not isinstance(session, dict):
            _raise_corruption("session_not_object", raw_bytes)
        session_id = session.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            _raise_corruption("session_id_invalid", raw_bytes)
        if "event_count" in session:
            event_count = session["event_count"]
            if (
                not isinstance(event_count, int)
                or isinstance(event_count, bool)
                or event_count < 0
            ):
                _raise_corruption("event_count_invalid", raw_bytes)
        if "events" in session:
            events = session["events"]
            if not isinstance(events, list) or any(
                not isinstance(item, dict) for item in events
            ):
                _raise_corruption("events_invalid", raw_bytes)
        if "reasons" in session:
            reasons = session["reasons"]
            if not isinstance(reasons, list) or any(
                not isinstance(item, str) for item in reasons
            ):
                _raise_corruption("reasons_invalid", raw_bytes)
        if "plan_ids" in session:
            plan_ids = session["plan_ids"]
            if not isinstance(plan_ids, list) or any(
                not isinstance(item, str) for item in plan_ids
            ):
                _raise_corruption("plan_ids_invalid", raw_bytes)

    return {
        "version": SESSION_INDEX_VERSION,
        "generated_at": loaded.get("generated_at"),
        "sessions": raw_sessions,
    }


def _read_index_snapshot(
    path: Path,
) -> tuple[dict[str, Any], os.stat_result | None]:
    snapshot = _secure_read_path(path, missing_ok=True)
    if snapshot is None:
        return (
            {"version": SESSION_INDEX_VERSION, "generated_at": None, "sessions": []},
            None,
        )
    raw_bytes, source_stat = snapshot
    return _parse_index_bytes(raw_bytes), source_stat


def load_session_index(path: Path) -> dict[str, Any]:
    index, _ = _read_index_snapshot(path)
    return index


def _load_index(path: Path) -> dict[str, Any]:
    return load_session_index(path)


def _raise_index_error(
    reason_code: str,
    message: str,
    *,
    quarantine: dict[str, Any] | None = None,
) -> None:
    raise SessionIndexError(
        message,
        reason_code=reason_code,
        quarantine=quarantine,
    )


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


def _require_secure_index_primitives() -> None:
    required_flags = ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
    if (
        not hasattr(os, "geteuid")
        or any(not hasattr(os, name) for name in required_flags)
        or os.open not in os.supports_dir_fd
        or os.link not in os.supports_dir_fd
        or os.stat not in os.supports_dir_fd
        or os.unlink not in os.supports_dir_fd
        or os.link not in os.supports_follow_symlinks
        or os.stat not in os.supports_follow_symlinks
    ):
        _raise_index_error(
            "session_index_security_unsupported",
            "secure session-index access is unsupported on this platform",
        )


def _read_descriptor(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _secure_read_path(
    path: Path,
    *,
    expected_bytes: bytes | None = None,
    missing_ok: bool = False,
) -> tuple[bytes, os.stat_result] | None:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        if missing_ok:
            return None
        _raise_index_error(
            "session_index_source_changed",
            "session index changed before quarantine could preserve it",
        )
    except (OSError, NotImplementedError) as exc:
        raise SessionIndexError(
            "session index source safety could not be verified",
            reason_code="session_index_unsafe_source",
        ) from exc

    _require_secure_index_primitives()

    if (
        not stat.S_ISREG(path_stat.st_mode)
        or path_stat.st_uid != os.geteuid()
        or path_stat.st_nlink != 1
    ):
        _raise_index_error(
            "session_index_unsafe_source",
            "session index source is not a current-user-owned regular single-link file",
        )

    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        descriptor = os.open(path, flags)
    except (OSError, NotImplementedError) as exc:
        reason_code = (
            "session_index_source_changed"
            if isinstance(exc, OSError) and exc.errno == errno.ENOENT
            else "session_index_unsafe_source"
        )
        raise SessionIndexError(
            "session index source safety could not be verified",
            reason_code=reason_code,
        ) from exc
    try:
        opened_stat = os.fstat(descriptor)
        if _stat_signature(path_stat) != _stat_signature(opened_stat):
            _raise_index_error(
                "session_index_source_changed",
                "session index changed before quarantine could preserve it",
            )
        data = _read_descriptor(descriptor)
        completed_stat = os.fstat(descriptor)
    finally:
        os.close(descriptor)

    if _stat_signature(opened_stat) != _stat_signature(completed_stat):
        _raise_index_error(
            "session_index_source_changed",
            "session index changed while quarantine read it",
        )
    try:
        final_path_stat = os.lstat(path)
    except (OSError, NotImplementedError) as exc:
        raise SessionIndexError(
            "session index changed while it was being read",
            reason_code="session_index_source_changed",
        ) from exc
    if _stat_signature(completed_stat) != _stat_signature(final_path_stat):
        _raise_index_error(
            "session_index_source_changed",
            "session index path changed while it was being read",
        )
    if expected_bytes is not None and data != expected_bytes:
        _raise_index_error(
            "session_index_source_changed",
            "session index changed after corruption was detected",
        )
    return data, completed_stat


def _secure_read_source(
    path: Path, expected_bytes: bytes
) -> tuple[bytes, os.stat_result]:
    snapshot = _secure_read_path(path, expected_bytes=expected_bytes)
    if snapshot is None:
        raise AssertionError("required source snapshot unexpectedly missing")
    return snapshot


def _open_quarantine_directory(path: Path) -> int:
    try:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        path_stat = os.lstat(path)
    except OSError as exc:
        raise SessionIndexError(
            "session-index quarantine directory could not be created",
            reason_code="session_index_quarantine_error",
        ) from exc
    if (
        not stat.S_ISDIR(path_stat.st_mode)
        or path_stat.st_uid != os.geteuid()
        or stat.S_IMODE(path_stat.st_mode) != 0o700
    ):
        _raise_index_error(
            "session_index_quarantine_error",
            "session-index quarantine directory must be current-user-owned with mode 0700",
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except (OSError, NotImplementedError) as exc:
        raise SessionIndexError(
            "session-index quarantine directory safety could not be verified",
            reason_code="session_index_quarantine_error",
        ) from exc
    try:
        opened_stat = os.fstat(descriptor)
    except BaseException:
        os.close(descriptor)
        raise
    if _stat_signature(path_stat) != _stat_signature(opened_stat):
        os.close(descriptor)
        _raise_index_error(
            "session_index_quarantine_error",
            "session-index quarantine directory changed while opening",
        )
    return descriptor


def _artifact_details(
    directory: Path, artifact_name: str, data: bytes, *, reused: bool
) -> dict[str, Any]:
    return {
        "status": "preserved",
        "path": str(directory / artifact_name),
        "sha256": hashlib.sha256(data).hexdigest(),
        "byte_count": len(data),
        "reused": reused,
    }


def _collision_details(
    directory: Path, artifact_name: str, expected_bytes: bytes
) -> dict[str, Any]:
    return {
        "status": "collision",
        "path": str(directory / artifact_name),
        "expected_sha256": hashlib.sha256(expected_bytes).hexdigest(),
        "byte_count": len(expected_bytes),
        "reused": False,
    }


def _read_existing_artifact(
    directory_fd: int,
    directory: Path,
    artifact_name: str,
    expected_bytes: bytes,
) -> dict[str, Any] | None:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        descriptor = os.open(artifact_name, flags, dir_fd=directory_fd)
    except FileNotFoundError:
        return None
    except (OSError, NotImplementedError) as exc:
        raise SessionIndexError(
            "session-index quarantine artifact is unsafe or inaccessible",
            reason_code="session_index_quarantine_collision",
            quarantine=_collision_details(directory, artifact_name, expected_bytes),
        ) from exc
    try:
        opened_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or opened_stat.st_uid != os.geteuid()
            or opened_stat.st_nlink != 1
            or stat.S_IMODE(opened_stat.st_mode) != 0o600
        ):
            _raise_index_error(
                "session_index_quarantine_collision",
                "session-index quarantine artifact has unsafe metadata",
                quarantine=_collision_details(directory, artifact_name, expected_bytes),
            )
        data = _read_descriptor(descriptor)
        os.fsync(descriptor)
        completed_stat = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        _stat_signature(opened_stat) != _stat_signature(completed_stat)
        or data != expected_bytes
    ):
        _raise_index_error(
            "session_index_quarantine_collision",
            "session-index quarantine artifact conflicts with corrupt source bytes",
            quarantine=_collision_details(directory, artifact_name, expected_bytes),
        )
    return _artifact_details(directory, artifact_name, expected_bytes, reused=True)


def _confirm_durable_artifact(
    directory_fd: int,
    directory: Path,
    artifact_name: str,
    expected_bytes: bytes,
) -> dict[str, Any]:
    try:
        os.fsync(directory_fd)
        confirmed = _read_existing_artifact(
            directory_fd, directory, artifact_name, expected_bytes
        )
    except (OSError, NotImplementedError) as exc:
        raise SessionIndexError(
            "session-index quarantine artifact durability could not be verified",
            reason_code="session_index_quarantine_error",
        ) from exc
    if confirmed is None:
        _raise_index_error(
            "session_index_quarantine_error",
            "quarantine artifact disappeared before durability verification",
        )
    return confirmed


def _cleanup_owned_temporary(
    directory_fd: int, temporary_name: str, identity: tuple[int, int]
) -> bool:
    try:
        current = os.stat(
            temporary_name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if (int(current.st_dev), int(current.st_ino)) != identity:
        return False
    try:
        os.unlink(temporary_name, dir_fd=directory_fd)
    except OSError:
        return False
    return True


def _write_all(descriptor: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written <= 0:
            raise OSError("short write while preserving session index")
        offset += written


def _publish_quarantine_artifact(
    directory_fd: int,
    directory: Path,
    artifact_name: str,
    data: bytes,
) -> dict[str, Any]:
    existing = _read_existing_artifact(
        directory_fd, directory, artifact_name, data
    )
    if existing is not None:
        return _confirm_durable_artifact(
            directory_fd, directory, artifact_name, data
        )

    temporary_name = f".{artifact_name}.{uuid.uuid4().hex}.tmp"
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_CLOEXEC
        | os.O_NOFOLLOW
        | os.O_NONBLOCK
    )
    temporary_identity: tuple[int, int] | None = None
    try:
        descriptor = os.open(
            temporary_name,
            flags,
            0o600,
            dir_fd=directory_fd,
        )
        try:
            temporary_stat = os.fstat(descriptor)
            temporary_identity = (
                int(temporary_stat.st_dev),
                int(temporary_stat.st_ino),
            )
            os.fchmod(descriptor, 0o600)
            _write_all(descriptor, data)
            os.fsync(descriptor)
            completed_stat = os.fstat(descriptor)
            if (
                not stat.S_ISREG(completed_stat.st_mode)
                or completed_stat.st_uid != os.geteuid()
                or completed_stat.st_nlink != 1
                or stat.S_IMODE(completed_stat.st_mode) != 0o600
                or completed_stat.st_size != len(data)
            ):
                raise OSError("temporary quarantine artifact failed verification")
        finally:
            os.close(descriptor)

        try:
            os.link(
                temporary_name,
                artifact_name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            if not _cleanup_owned_temporary(
                directory_fd, temporary_name, temporary_identity
            ):
                _raise_index_error(
                    "session_index_quarantine_error",
                    "temporary quarantine artifact could not be safely removed",
                )
            existing = _read_existing_artifact(
                directory_fd, directory, artifact_name, data
            )
            if existing is None:
                _raise_index_error(
                    "session_index_quarantine_collision",
                    "session-index quarantine artifact disappeared during publication",
                )
            return _confirm_durable_artifact(
                directory_fd, directory, artifact_name, data
            )

        if not _cleanup_owned_temporary(
            directory_fd, temporary_name, temporary_identity
        ):
            _raise_index_error(
                "session_index_quarantine_error",
                "published quarantine artifact retained an unsafe temporary link",
            )
        os.fsync(directory_fd)
        verified = _read_existing_artifact(
            directory_fd, directory, artifact_name, data
        )
        if verified is None:
            _raise_index_error(
                "session_index_quarantine_error",
                "published quarantine artifact could not be verified",
            )
        verified["reused"] = False
        return verified
    except SessionIndexError:
        if temporary_identity is not None:
            _cleanup_owned_temporary(directory_fd, temporary_name, temporary_identity)
        raise
    except (OSError, NotImplementedError) as exc:
        if temporary_identity is not None:
            _cleanup_owned_temporary(directory_fd, temporary_name, temporary_identity)
        raise SessionIndexError(
            "session-index quarantine artifact could not be published",
            reason_code="session_index_quarantine_error",
        ) from exc
    except BaseException:
        if temporary_identity is not None:
            _cleanup_owned_temporary(directory_fd, temporary_name, temporary_identity)
        raise


def _recheck_source(path: Path, expected_stat: os.stat_result) -> None:
    try:
        current = os.lstat(path)
    except OSError as exc:
        raise SessionIndexError(
            "session index changed after quarantine preservation",
            reason_code="session_index_source_changed",
        ) from exc
    if _stat_signature(current) != _stat_signature(expected_stat):
        _raise_index_error(
            "session_index_source_changed",
            "session index changed after quarantine preservation",
        )


def _quarantine_corrupt_index(path: Path, expected_bytes: bytes) -> dict[str, Any]:
    source_bytes, source_stat = _secure_read_source(path, expected_bytes)
    directory = _quarantine_directory()
    artifact_name = f"{hashlib.sha256(source_bytes).hexdigest()}{QUARANTINE_SUFFIX}"
    directory_fd = _open_quarantine_directory(directory)
    try:
        details = _publish_quarantine_artifact(
            directory_fd,
            directory,
            artifact_name,
            source_bytes,
        )
    finally:
        os.close(directory_fd)
    try:
        _recheck_source(path, source_stat)
    except SessionIndexError as exc:
        exc.quarantine = details
        raise
    return details


def _atomic_write_json(
    path: Path,
    payload: dict[str, Any],
    expected_source: os.stat_result | None,
) -> None:
    """Persist sidecar JSON without exposing a partially written index."""
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    temporary_identity: tuple[int, int] | None = None
    try:
        temporary_stat = os.fstat(descriptor)
        temporary_identity = (
            int(temporary_stat.st_dev),
            int(temporary_stat.st_ino),
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        completed_stat = os.fstat(descriptor)
        named_temporary = os.lstat(temporary_path)
        if (
            (int(named_temporary.st_dev), int(named_temporary.st_ino))
            != temporary_identity
            or not stat.S_ISREG(completed_stat.st_mode)
            or completed_stat.st_uid != os.geteuid()
            or completed_stat.st_nlink != 1
            or stat.S_IMODE(completed_stat.st_mode) != 0o600
            or _stat_signature(completed_stat) != _stat_signature(named_temporary)
        ):
            _raise_index_error(
                "session_index_write_race",
                "temporary session index changed before publication",
            )

        try:
            current_source = os.lstat(path)
        except FileNotFoundError:
            current_source = None
        if expected_source is None:
            if current_source is not None:
                _raise_index_error(
                    "session_index_source_changed",
                    "session index appeared before publication",
                )
        elif current_source is None or _stat_signature(
            current_source
        ) != _stat_signature(expected_source):
            _raise_index_error(
                "session_index_source_changed",
                "session index changed before publication",
            )

        os.replace(temporary_path, path)
        published_stat = os.lstat(path)
        if (
            (int(published_stat.st_dev), int(published_stat.st_ino))
            != temporary_identity
            or not stat.S_ISREG(published_stat.st_mode)
            or published_stat.st_uid != os.geteuid()
            or published_stat.st_nlink != 1
            or stat.S_IMODE(published_stat.st_mode) != 0o600
            or published_stat.st_size != completed_stat.st_size
        ):
            _raise_index_error(
                "session_index_write_race",
                "published session index identity could not be verified",
            )
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        final_stat = os.lstat(path)
        if (int(final_stat.st_dev), int(final_stat.st_ino)) != temporary_identity:
            _raise_index_error(
                "session_index_write_race",
                "published session index changed before durability verification",
            )
    finally:
        os.close(descriptor)
        try:
            remaining = os.lstat(temporary_path)
        except FileNotFoundError:
            remaining = None
        if temporary_identity is not None and remaining is not None and (
            int(remaining.st_dev), int(remaining.st_ino)
        ) == temporary_identity:
            temporary_path.unlink()


def _event_from_digest(digest: dict[str, Any]) -> dict[str, Any]:
    raw_git = digest.get("git")
    raw_plan = digest.get("plan_execution")
    git: dict[str, Any] = raw_git if isinstance(raw_git, dict) else {}
    plan: dict[str, Any] = raw_plan if isinstance(raw_plan, dict) else {}
    timestamp = digest.get("timestamp")
    reason = digest.get("reason")
    changes = git.get("status_count", 0)
    branch = git.get("branch")
    plan_status = plan.get("status")
    plan_id = plan.get("plan_id")
    return {
        "timestamp": timestamp if isinstance(timestamp, str) else None,
        "reason": reason if isinstance(reason, str) else None,
        "changes": changes
        if isinstance(changes, int) and not isinstance(changes, bool)
        else 0,
        "branch": branch if isinstance(branch, str) else None,
        "plan_status": plan_status if isinstance(plan_status, str) else None,
        "plan_id": plan_id if isinstance(plan_id, str) else None,
    }


def _session_timestamp_sort_key(session: dict[str, Any]) -> tuple[bool, float]:
    parsed = _parse_iso(str(session.get("last_event_at") or ""))
    return (parsed is not None, parsed.timestamp() if parsed is not None else 0.0)


def _prune_sessions(
    sessions: list[dict[str, Any]], policy: dict[str, int]
) -> list[dict[str, Any]]:
    cutoff = _utc_now() - timedelta(days=policy["max_age_days"])
    kept: list[dict[str, Any]] = []
    for session in sessions:
        parsed = _parse_iso(str(session.get("last_event_at") or ""))
        if parsed is None or parsed >= cutoff:
            kept.append(session)
    kept.sort(key=_session_timestamp_sort_key, reverse=True)
    return kept[: policy["max_sessions"]]


def _recovery_steps(reason_code: str) -> list[str]:
    if reason_code.startswith("session_index_quarantine") or reason_code in {
        "session_index_corrupt",
        "session_index_source_changed",
        "session_index_unsafe_source",
    }:
        return list(CORRUPTION_RECOVERY_STEPS)
    if reason_code == "session_index_unsupported_version":
        return [
            "migrate the session index to the supported version before writing",
            "run /session doctor --json",
        ]
    return [
        "verify session index path ownership and access",
        "run /session doctor --json",
    ]


def _failure_result(
    path: Path,
    error: SessionIndexError,
    *,
    corruption_kind: str | None = None,
    quarantine: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_quarantine = quarantine if quarantine is not None else error.quarantine
    return {
        "result": "FAIL",
        "reason_code": error.reason_code,
        "corruption_kind": corruption_kind or error.corruption_kind,
        "path": str(path),
        "quarantine": resolved_quarantine,
        "recovery_steps": _recovery_steps(error.reason_code),
        "error": str(error),
    }


def update_session_index(
    digest: dict[str, Any], path: Path | None = None
) -> dict[str, Any]:
    index_path = path or DEFAULT_INDEX_PATH
    try:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        with _index_write_lock(index_path):
            return _update_session_index_unlocked(digest, index_path)
    except SessionIndexError as exc:
        return _failure_result(index_path, exc)
    except OSError as exc:
        error = SessionIndexError(
            "session index transaction could not be completed",
            reason_code="session_index_io_error",
        )
        error.__cause__ = exc
        return _failure_result(index_path, error)


def _update_session_index_unlocked(
    digest: dict[str, Any], path: Path | None = None
) -> dict[str, Any]:
    index_path = path or DEFAULT_INDEX_PATH
    try:
        index, source_stat = _read_index_snapshot(index_path)
    except SessionIndexCorruption as exc:
        try:
            quarantine = _quarantine_corrupt_index(
                index_path,
                exc.raw_bytes if exc.raw_bytes is not None else b"",
            )
        except SessionIndexError as quarantine_error:
            return _failure_result(
                index_path,
                quarantine_error,
                corruption_kind=exc.corruption_kind,
            )
        return _failure_result(
            index_path,
            exc,
            quarantine=quarantine,
        )
    except SessionIndexError as exc:
        return _failure_result(index_path, exc)
    policy = _load_policy()

    timestamp = str(digest.get("timestamp") or _utc_now().isoformat())
    cwd = str(digest.get("cwd") or "")
    session_id = _session_id(timestamp, cwd)
    event = _event_from_digest(digest)

    raw_sessions = index.get("sessions")
    sessions: list[dict[str, Any]] = (
        [item for item in raw_sessions if isinstance(item, dict)]
        if isinstance(raw_sessions, list)
        else []
    )
    target: dict[str, Any] | None = None
    for candidate in sessions:
        if candidate.get("session_id") == session_id:
            target = candidate
            break
    if target is None:
        target = {
            "session_id": session_id,
            "cwd": cwd,
            "started_at": timestamp,
            "last_event_at": timestamp,
            "event_count": 0,
            "last_reason": None,
            "reasons": [],
            "plan_ids": [],
            "events": [],
        }
        sessions.append(target)

    raw_events = target.get("events")
    events: list[dict[str, Any]] = (
        [item for item in raw_events if isinstance(item, dict)]
        if isinstance(raw_events, list)
        else []
    )
    events.append(event)
    pruned_event_count = max(0, len(events) - policy["max_events_per_session"])
    if pruned_event_count:
        events = events[-policy["max_events_per_session"] :]

    raw_reasons = target.get("reasons")
    reasons: list[str] = (
        [item for item in raw_reasons if isinstance(item, str)]
        if isinstance(raw_reasons, list)
        else []
    )
    reason = event.get("reason")
    if isinstance(reason, str) and reason and reason not in reasons:
        reasons.append(reason)

    raw_plan_ids = target.get("plan_ids")
    plan_ids: list[str] = (
        [item for item in raw_plan_ids if isinstance(item, str)]
        if isinstance(raw_plan_ids, list)
        else []
    )
    plan_id = event.get("plan_id")
    if isinstance(plan_id, str) and plan_id and plan_id not in plan_ids:
        plan_ids.append(plan_id)

    target["events"] = events
    target["event_count"] = int(target.get("event_count", 0)) + 1
    target["last_event_at"] = timestamp
    target["last_reason"] = reason
    pruned_reason_count = max(0, len(reasons) - policy["max_reasons_per_session"])
    pruned_plan_id_count = max(0, len(plan_ids) - policy["max_plan_ids_per_session"])
    target["reasons"] = reasons[-policy["max_reasons_per_session"] :]
    target["plan_ids"] = plan_ids[-policy["max_plan_ids_per_session"] :]
    target["cwd"] = cwd

    index["sessions"] = _prune_sessions(sessions, policy)
    index["generated_at"] = _utc_now().isoformat()

    try:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(index_path, index, source_stat)
    except SessionIndexError as exc:
        return _failure_result(index_path, exc)
    except OSError as exc:
        error = SessionIndexError(
            "session index could not be written",
            reason_code="session_index_io_error",
        )
        error.__cause__ = exc
        return _failure_result(index_path, error)
    except (TypeError, ValueError, RecursionError) as exc:
        error = SessionIndexError(
            "session index payload could not be serialized",
            reason_code="session_index_serialization_error",
        )
        error.__cause__ = exc
        return _failure_result(index_path, error)

    return {
        "result": "PASS",
        "path": str(index_path),
        "session_id": session_id,
        "session_count": len(index["sessions"]),
        "policy": policy,
        "pruned": {
            "events": pruned_event_count,
            "reasons": pruned_reason_count,
            "plan_ids": pruned_plan_id_count,
        },
    }
