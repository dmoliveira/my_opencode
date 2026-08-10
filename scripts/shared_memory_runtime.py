#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sqlite3
import stat
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from bounded_subprocess import BoundedCommandError, run_bounded  # type: ignore

try:
    import fcntl
except ImportError:  # pragma: no cover - connect_readonly rejects non-Unix hosts
    fcntl = None  # type: ignore[assignment]


DEFAULT_DB_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_SHARED_MEMORY_PATH",
        "~/.config/opencode/my_opencode/runtime/shared_memory.db",
    )
).expanduser()

SCHEMA_VERSION = 1
LEGACY_SCHEMA_VERSION = 0
SCHEMA_COLUMNS = {
    "meta": {
        "key": ("TEXT", 0, 1),
        "value": ("TEXT", 1, 0),
    },
    "memories": {
        "id": ("TEXT", 0, 1),
        "kind": ("TEXT", 1, 0),
        "scope": ("TEXT", 1, 0),
        "namespace": ("TEXT", 1, 0),
        "title": ("TEXT", 1, 0),
        "content": ("TEXT", 1, 0),
        "summary": ("TEXT", 1, 0),
        "tags_json": ("TEXT", 1, 0),
        "tags_text": ("TEXT", 1, 0),
        "links_json": ("TEXT", 1, 0),
        "source_type": ("TEXT", 0, 0),
        "source_ref": ("TEXT", 0, 0),
        "session_id": ("TEXT", 0, 0),
        "cwd": ("TEXT", 1, 0),
        "pinned": ("INTEGER", 1, 0),
        "archived": ("INTEGER", 1, 0),
        "confidence": ("INTEGER", 1, 0),
        "created_at": ("TEXT", 1, 0),
        "updated_at": ("TEXT", 1, 0),
    },
}
OWNED_INDEXES = {
    "idx_memories_scope_namespace_updated": (
        False,
        (
            ("scope", False, "BINARY"),
            ("namespace", False, "BINARY"),
            ("archived", False, "BINARY"),
            ("pinned", False, "BINARY"),
            ("updated_at", True, "BINARY"),
        ),
        False,
    ),
    "idx_memories_session_id": (False, (("session_id", False, "BINARY"),), False),
    "idx_memories_source_ref_unique": (
        True,
        (("source_type", False, "BINARY"), ("source_ref", False, "BINARY")),
        False,
    ),
}
VALID_SCOPES = {"session", "repo", "shared"}
VALID_KINDS = {
    "note",
    "decision",
    "blocker",
    "artifact",
    "summary",
    "validation",
}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _repo_root(cwd: Path, diagnostics: list[str] | None = None) -> str:
    try:
        result = run_bounded(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            operation="shared_memory_git_repo_root",
            capture_output=True,
            text=True,
        )
    except BoundedCommandError as exc:
        if diagnostics is not None and exc.reason_code not in diagnostics:
            diagnostics.append(exc.reason_code)
        return str(cwd)
    if result.returncode != 0:
        return str(cwd)
    return result.stdout.strip() or str(cwd)


def _repo_identity(cwd: Path, diagnostics: list[str] | None = None) -> str:
    try:
        result = run_bounded(
            [
                "git",
                "-C",
                str(cwd),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            operation="shared_memory_git_repo_identity",
            capture_output=True,
            text=True,
        )
    except BoundedCommandError as exc:
        if diagnostics is not None and exc.reason_code not in diagnostics:
            diagnostics.append(exc.reason_code)
        return _repo_root(cwd, diagnostics)
    if result.returncode != 0:
        return _repo_root(cwd, diagnostics)
    return result.stdout.strip() or _repo_root(cwd, diagnostics)


def normalize_scope(raw: str | None) -> str:
    scope = str(raw or "repo").strip().lower()
    return scope if scope in VALID_SCOPES else "repo"


def normalize_kind(raw: str | None) -> str:
    kind = str(raw or "note").strip().lower()
    return kind if kind in VALID_KINDS else "note"


def normalize_tags(raw: list[str] | str | None) -> list[str]:
    if isinstance(raw, str):
        parts = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, list):
        parts = [str(part).strip() for part in raw]
    else:
        parts = []
    seen: set[str] = set()
    tags: list[str] = []
    for part in parts:
        if not part:
            continue
        lowered = part.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        tags.append(lowered)
    return tags


def normalize_links(raw: list[str] | str | None) -> list[str]:
    if isinstance(raw, str):
        parts = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, list):
        parts = [str(part).strip() for part in raw]
    else:
        parts = []
    seen: set[str] = set()
    links: list[str] = []
    for part in parts:
        if not part or part in seen:
            continue
        seen.add(part)
        links.append(part)
    return links


def internal_memory_link(source_ref: str) -> str:
    return f"memory-ref:{source_ref}"


def normalize_confidence(raw: Any) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 60
    return max(0, min(100, value))


def infer_namespace(
    cwd: Path,
    scope: str,
    explicit: str | None = None,
    diagnostics: list[str] | None = None,
) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    if scope == "shared":
        return "shared"
    if scope == "session":
        return (
            os.environ.get("OPENCODE_SESSION_ID", "current-session").strip()
            or "current-session"
        )
    return _repo_root(cwd, diagnostics)


@dataclass
class MemoryRecord:
    memory_id: str
    kind: str
    scope: str
    namespace: str
    title: str
    content: str
    summary: str
    tags: list[str]
    links: list[str]
    source_type: str | None
    source_ref: str | None
    session_id: str | None
    cwd: str
    pinned: bool
    archived: bool
    confidence: int
    created_at: str
    updated_at: str
    lexical_score: float | None = None
    score: float | None = None
    score_reasons: list[str] | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "id": self.memory_id,
            "kind": self.kind,
            "scope": self.scope,
            "namespace": self.namespace,
            "title": self.title,
            "content": self.content,
            "summary": self.summary,
            "tags": self.tags,
            "links": self.links,
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "session_id": self.session_id,
            "cwd": self.cwd,
            "pinned": self.pinned,
            "archived": self.archived,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.lexical_score is not None:
            payload["lexical_score"] = round(self.lexical_score, 4)
        if self.score is not None:
            payload["score"] = round(self.score, 4)
        if self.score_reasons is not None:
            payload["score_reasons"] = self.score_reasons
        return payload


def _schema_inspection(conn: sqlite3.Connection) -> dict[str, Any]:
    tables = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    columns: dict[str, dict[str, tuple[str, int, int]]] = {}
    missing_columns: dict[str, list[str]] = {}
    unexpected_columns: dict[str, list[str]] = {}
    for table, expected in SCHEMA_COLUMNS.items():
        actual = {
            str(row[1]): (str(row[2]).upper(), int(row[3]), int(row[5]))
            for row in conn.execute(f"PRAGMA table_info({table})")
        }
        columns[table] = actual
        missing_columns[table] = sorted(set(expected) - set(actual))
        unexpected_columns[table] = sorted(set(actual) - set(expected))
    version_row = None
    if "meta" in tables:
        version_row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
    version_raw = None if version_row is None else str(version_row[0])
    version_state = (
        "legacy"
        if version_raw is None or version_raw == str(LEGACY_SCHEMA_VERSION)
        else "current"
        if version_raw == str(SCHEMA_VERSION)
        else "unsupported"
    )
    structure_ok = (
        set(SCHEMA_COLUMNS).issubset(tables)
        and not any(missing_columns.values())
        and not any(unexpected_columns.values())
        and all(
            all(columns[table][name] == specification for name, specification in expected.items())
            for table, expected in SCHEMA_COLUMNS.items()
        )
    )
    indexes: dict[str, tuple[bool, tuple[tuple[str | None, bool, str], ...], bool]] = {}
    if "memories" in tables:
        for row in conn.execute("PRAGMA index_list(memories)"):
            name = str(row[1])
            quoted_name = '"' + name.replace('"', '""') + '"'
            index_columns = [
                column
                for column in conn.execute(f"PRAGMA index_xinfo({quoted_name})")
                if int(column[5]) == 1
            ]
            indexes[name] = (
                bool(row[2]),
                tuple(
                    (
                        str(column[2]) if column[2] is not None else None,
                        bool(column[3]),
                        str(column[4] or ""),
                    )
                    for column in index_columns
                ),
                bool(row[4]),
            )
    missing_indexes = sorted(set(OWNED_INDEXES) - set(indexes))
    incompatible_indexes = sorted(
        name for name, expected in OWNED_INDEXES.items() if name in indexes and indexes[name] != expected
    )
    duplicate_source_keys = 0
    if not missing_columns.get("memories") and "memories" in tables:
        duplicate_source_keys = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT source_type, source_ref
                    FROM memories
                    WHERE source_type IS NOT NULL AND source_ref IS NOT NULL
                    GROUP BY source_type, source_ref
                    HAVING COUNT(*) > 1
                )
                """
            ).fetchone()[0]
        )
    owned_triggers = sorted(
        str(row[0])
        for row in conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'trigger' AND tbl_name IN ('meta', 'memories')
            """
        )
    )
    return {
        "tables": sorted(tables),
        "columns": columns,
        "missing_columns": missing_columns,
        "unexpected_columns": unexpected_columns,
        "version_raw": version_raw,
        "version": int(version_raw) if version_raw in {"0", "1"} else None,
        "version_state": version_state,
        "structure_ok": structure_ok,
        "missing_indexes": missing_indexes,
        "incompatible_indexes": incompatible_indexes,
        "duplicate_source_keys": duplicate_source_keys,
        "owned_triggers": owned_triggers,
        "legacy_migration_ready": structure_ok
        and not missing_indexes
        and not incompatible_indexes
        and duplicate_source_keys == 0
        and not owned_triggers,
        "fresh": not tables,
    }


def _require_current_schema(inspection: dict[str, Any]) -> None:
    if inspection.get("fresh"):
        raise RuntimeError("shared-memory database has no schema; initialize it explicitly")
    if inspection.get("version_state") == "unsupported":
        raise RuntimeError(
            f"shared-memory schema version {inspection.get('version_raw')} is incompatible "
            f"with supported version {SCHEMA_VERSION}; run an explicit migration before opening the store"
        )
    if not inspection.get("structure_ok"):
        raise RuntimeError("shared-memory database schema structure is incompatible")
    if inspection.get("incompatible_indexes"):
        raise RuntimeError("shared-memory database has incompatible owned indexes")
    if inspection.get("owned_triggers"):
        raise RuntimeError("shared-memory database has unexpected owned-table triggers")
    if inspection.get("version_state") != "current":
        raise RuntimeError(
            "shared-memory schema version is incompatible; run /memory-lifecycle migrate --apply"
        )


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = (db_path or DEFAULT_DB_PATH).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    initialize(conn)
    return conn


def _entry_stat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _require_regular_entry(path: Path, label: str) -> os.stat_result | None:
    details = _entry_stat(path)
    if details is None:
        return None
    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
        raise RuntimeError(f"read-only preview rejects unsupported {label} entry")
    return details


def _canonical_preview_path(path: Path) -> tuple[Path, os.stat_result]:
    source_details = _entry_stat(path)
    if source_details is None:
        orphan_paths = [
            Path(f"{path}{suffix}") for suffix in ("-wal", "-shm", "-journal")
        ]
        if any(_entry_stat(sidecar) is not None for sidecar in orphan_paths):
            raise RuntimeError("read-only preview refuses orphaned SQLite sidecars")
        raise FileNotFoundError(path)
    try:
        canonical = path.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as exc:
        raise RuntimeError("read-only preview refuses a dangling database path") from exc
    details = _require_regular_entry(canonical, "database")
    if details is None:  # pragma: no cover - resolve(strict=True) established existence
        raise FileNotFoundError(canonical)
    return canonical, details


def _sidecar_state(
    canonical: Path,
) -> tuple[os.stat_result | None, os.stat_result | None]:
    journal_path = Path(f"{canonical}-journal")
    if _entry_stat(journal_path) is not None:
        raise RuntimeError("read-only preview refuses an active rollback journal")
    wal_path = Path(f"{canonical}-wal")
    shm_path = Path(f"{canonical}-shm")
    wal_details = _require_regular_entry(wal_path, "WAL sidecar")
    shm_details = _require_regular_entry(shm_path, "SHM sidecar")
    if (wal_details is None) != (shm_details is None):
        raise RuntimeError(
            "read-only WAL preview requires existing WAL and SHM sidecars"
        )
    return wal_details, shm_details


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _read_fd_bytes(descriptor: int, size: int) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while offset < size:
        chunk = os.pread(descriptor, min(1024 * 1024, size - offset), offset)
        if not chunk:
            break
        chunks.append(chunk)
        offset += len(chunk)
    if offset != size:
        raise RuntimeError("shared-memory database changed while snapshotting")
    return b"".join(chunks)


def _read_entry_prefix(
    path: Path, expected: os.stat_result, size: int, label: str
) -> tuple[bytes, os.stat_result]:
    if not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("read-only WAL preview requires no-follow file opens")
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if not _same_identity(expected, before):
            raise RuntimeError(f"shared-memory {label} identity changed while opening")
        payload = os.pread(descriptor, size, 0)
        after = os.fstat(descriptor)
        stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
            raise RuntimeError(f"shared-memory {label} changed while validating")
        if len(payload) != size:
            raise RuntimeError(f"shared-memory {label} has an invalid header")
        return payload, after
    finally:
        os.close(descriptor)


def _sqlite_checksum(
    data: bytes, byteorder: str, seed: tuple[int, int] = (0, 0)
) -> tuple[int, int]:
    first, second = seed
    for offset in range(0, len(data), 8):
        left = int.from_bytes(data[offset : offset + 4], byteorder)
        right = int.from_bytes(data[offset + 4 : offset + 8], byteorder)
        first = (first + left + second) & 0xFFFFFFFF
        second = (second + right + first) & 0xFFFFFFFF
    return first, second


def _validate_committed_wal_frames(
    wal_path: Path,
    expected: os.stat_result,
    *,
    wal_header: bytes,
    page_size: int,
    checksum_order: str,
    max_frame: int,
    shm_frame_checksum: tuple[int, int],
) -> None:
    if not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("read-only WAL preview requires no-follow file opens")
    descriptor = os.open(wal_path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if not _same_identity(expected, before):
            raise RuntimeError("shared-memory WAL identity changed while validating")
        frame_size = page_size + 24
        available_frames = (before.st_size - 32) // frame_size
        if max_frame > available_frames:
            raise RuntimeError("shared-memory SHM sidecar references a missing WAL frame")
        rolling = (
            int.from_bytes(wal_header[24:28], "big"),
            int.from_bytes(wal_header[28:32], "big"),
        )
        checksum_at_snapshot = rolling
        for frame_number in range(1, max_frame + 1):
            offset = 32 + (frame_number - 1) * frame_size
            frame = os.pread(descriptor, frame_size, offset)
            if len(frame) != frame_size:
                raise RuntimeError("shared-memory WAL sidecar has a partial frame")
            page_number = int.from_bytes(frame[0:4], "big")
            database_size = int.from_bytes(frame[4:8], "big")
            if page_number == 0 or frame[8:16] != wal_header[16:24]:
                raise RuntimeError("shared-memory WAL frame has invalid page or salt data")
            rolling = _sqlite_checksum(
                frame[:8] + frame[24:], checksum_order, rolling
            )
            stored = (
                int.from_bytes(frame[16:20], "big"),
                int.from_bytes(frame[20:24], "big"),
            )
            if rolling != stored:
                raise RuntimeError("shared-memory WAL frame failed its checksum")
            if frame_number == max_frame:
                if database_size == 0:
                    raise RuntimeError(
                        "shared-memory SHM sidecar references an uncommitted WAL frame"
                    )
                checksum_at_snapshot = rolling
        after = os.fstat(descriptor)
        stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
            raise RuntimeError("shared-memory WAL changed while validating frames")
        if max_frame and checksum_at_snapshot != shm_frame_checksum:
            raise RuntimeError("shared-memory WAL and SHM frame checksums do not match")
    finally:
        os.close(descriptor)


def _validate_active_wal_headers(
    wal_path: Path,
    shm_path: Path,
    wal_details: os.stat_result,
    shm_details: os.stat_result,
) -> None:
    wal_header, current_wal = _read_entry_prefix(
        wal_path, wal_details, 32, "WAL sidecar"
    )
    shm_headers, current_shm = _read_entry_prefix(
        shm_path, shm_details, 96, "SHM sidecar"
    )
    magic = int.from_bytes(wal_header[0:4], "big")
    if magic not in {0x377F0682, 0x377F0683}:
        raise RuntimeError("shared-memory WAL sidecar has an invalid magic value")
    version = int.from_bytes(wal_header[4:8], "big")
    page_size = int.from_bytes(wal_header[8:12], "big")
    if page_size == 1:
        page_size = 65536
    if (
        version != 3007000
        or page_size < 512
        or page_size > 65536
        or page_size & (page_size - 1)
    ):
        raise RuntimeError("shared-memory WAL sidecar has an invalid format")
    checksum_order = "big" if magic & 1 else "little"
    expected_checksum = _sqlite_checksum(wal_header[:24], checksum_order)
    stored_checksum = (
        int.from_bytes(wal_header[24:28], "big"),
        int.from_bytes(wal_header[28:32], "big"),
    )
    if expected_checksum != stored_checksum:
        raise RuntimeError("shared-memory WAL sidecar failed its header checksum")
    frame_size = page_size + 24
    if current_wal.st_size < 32 or (current_wal.st_size - 32) % frame_size:
        raise RuntimeError("shared-memory WAL sidecar has a partial frame")

    first_header = shm_headers[:48]
    second_header = shm_headers[48:96]
    if current_shm.st_size < 96 or first_header != second_header:
        raise RuntimeError("shared-memory SHM sidecar has inconsistent headers")
    native = sys.byteorder
    shm_version = int.from_bytes(first_header[0:4], native)
    initialized = first_header[12]
    checksum_endianness = first_header[13]
    shm_page_size = int.from_bytes(first_header[14:16], native)
    if shm_page_size == 1:
        shm_page_size = 65536
    if (
        shm_version != version
        or initialized != 1
        or checksum_endianness != (magic & 1)
        or shm_page_size != page_size
    ):
        raise RuntimeError("shared-memory SHM sidecar has an invalid format")
    expected_shm_checksum = _sqlite_checksum(first_header[:40], native)
    stored_shm_checksum = (
        int.from_bytes(first_header[40:44], native),
        int.from_bytes(first_header[44:48], native),
    )
    if expected_shm_checksum != stored_shm_checksum:
        raise RuntimeError("shared-memory SHM sidecar failed its header checksum")
    if wal_header[16:24] != first_header[32:40]:
        raise RuntimeError("shared-memory WAL and SHM sidecars do not match")
    max_frame = int.from_bytes(first_header[16:20], native)
    available_frames = (current_wal.st_size - 32) // frame_size
    if max_frame > available_frames:
        raise RuntimeError("shared-memory SHM sidecar references a missing WAL frame")
    shm_frame_checksum = (
        int.from_bytes(first_header[24:28], native),
        int.from_bytes(first_header[28:32], native),
    )
    _validate_committed_wal_frames(
        wal_path,
        current_wal,
        wal_header=wal_header,
        page_size=page_size,
        checksum_order=checksum_order,
        max_frame=max_frame,
        shm_frame_checksum=shm_frame_checksum,
    )


def _checkpointed_database_image(
    canonical: Path, expected: os.stat_result
) -> bytearray:
    if fcntl is None or not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("read-only checkpointed preview requires POSIX file locks")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    descriptor = os.open(canonical, flags)
    locked = False
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or not _same_identity(expected, opened)
        ):
            raise RuntimeError("shared-memory database identity changed before snapshot")
        try:
            fcntl.lockf(
                descriptor,
                fcntl.LOCK_SH | fcntl.LOCK_NB,
                0,
                0,
                os.SEEK_SET,
            )
            locked = True
        except OSError as exc:
            raise RuntimeError(
                "shared-memory database is busy; checkpointed preview could not lock it"
            ) from exc
        wal_details, shm_details = _sidecar_state(canonical)
        if wal_details is not None or shm_details is not None:
            raise RuntimeError("shared-memory sidecar appeared while snapshotting")
        before = os.fstat(descriptor)
        image = bytearray(_read_fd_bytes(descriptor, before.st_size))
        after = os.fstat(descriptor)
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
            raise RuntimeError("shared-memory database changed while snapshotting")
        named = canonical.stat(follow_symlinks=False)
        if not _same_identity(after, named):
            raise RuntimeError("shared-memory database path changed while snapshotting")
        wal_details, shm_details = _sidecar_state(canonical)
        if wal_details is not None or shm_details is not None:
            raise RuntimeError("shared-memory sidecar appeared while snapshotting")
        return image
    finally:
        if locked:
            fcntl.lockf(descriptor, fcntl.LOCK_UN, 0, 0, os.SEEK_SET)
        os.close(descriptor)


def connect_readonly(
    db_path: Path | None = None, *, allow_legacy: bool = False
) -> sqlite3.Connection:
    """Open one coherent shared-memory snapshot without initializing the store."""
    path = (db_path or DEFAULT_DB_PATH).expanduser()
    if not (sys.platform.startswith("darwin") or sys.platform.startswith("linux")):
        raise RuntimeError("read-only shared-memory preview requires the Unix VFS")
    if sqlite3.sqlite_version_info < (3, 22, 0):
        raise RuntimeError("read-only WAL preview requires SQLite 3.22 or newer")

    canonical, database_details = _canonical_preview_path(path)
    wal_path = Path(f"{canonical}-wal")
    shm_path = Path(f"{canonical}-shm")
    wal_details, shm_details = _sidecar_state(canonical)
    active_wal = wal_details is not None and shm_details is not None

    if active_wal:
        uri = (
            f"{canonical.as_uri()}"
            "?mode=ro&cache=private&vfs=unix&readonly_shm=1"
        )
        conn = sqlite3.connect(uri, uri=True)
    else:
        if not hasattr(sqlite3.Connection, "deserialize"):
            raise RuntimeError(
                "read-only checkpointed preview requires SQLite deserialize support"
            )
        image = _checkpointed_database_image(canonical, database_details)
        if len(image) < 100 or bytes(image[:16]) != b"SQLite format 3\x00":
            raise RuntimeError("shared-memory snapshot has an invalid SQLite header")
        # A checkpointed WAL database can retain WAL read/write header bytes even
        # after its sidecars disappear. Normalize only the private in-memory copy
        # so deserialize never tries to recover sidecars beside the source path.
        image[18] = 1
        image[19] = 1
        conn = sqlite3.connect(":memory:")
        try:
            conn.deserialize(bytes(image))
        except Exception:
            conn.close()
            raise
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA query_only=ON")
        query_only = conn.execute("PRAGMA query_only").fetchone()
        if query_only is None or int(query_only[0]) != 1:
            raise RuntimeError("shared-memory preview could not verify query-only mode")
        conn.execute("BEGIN")
        if active_wal:
            current_database = _require_regular_entry(canonical, "database")
            current_wal, current_shm = _sidecar_state(canonical)
            if (
                current_database is None
                or current_wal is None
                or current_shm is None
                or not _same_identity(database_details, current_database)
                or not _same_identity(wal_details, current_wal)
                or not _same_identity(shm_details, current_shm)
            ):
                raise RuntimeError(
                    "shared-memory database sidecars changed while opening preview"
                )
            _validate_active_wal_headers(
                wal_path,
                shm_path,
                current_wal,
                current_shm,
            )
        inspection = _schema_inspection(conn)
        if allow_legacy:
            if not inspection["structure_ok"]:
                raise RuntimeError("shared-memory schema structure is incompatible")
            if inspection["version_state"] == "unsupported":
                raise RuntimeError(
                    f"shared-memory schema version {inspection['version_raw']} is incompatible"
                )
        else:
            _require_current_schema(inspection)
        quick_check = conn.execute("PRAGMA quick_check").fetchone()
        if quick_check is None or str(quick_check[0]).lower() != "ok":
            raise RuntimeError("shared-memory snapshot failed SQLite quick_check")
        return conn
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        conn.close()
        raise


def initialize(conn: sqlite3.Connection) -> None:
    inspection = _schema_inspection(conn)
    if not inspection["fresh"]:
        _require_current_schema(inspection)
        conn.execute("PRAGMA journal_mode=WAL")
        _ensure_owned_indexes(conn)
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('fts_enabled', ?)",
            ("1" if _ensure_fts(conn) else "0",),
        )
        _rebuild_fts(conn)
        conn.commit()
        return
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            scope TEXT NOT NULL,
            namespace TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            summary TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            tags_text TEXT NOT NULL,
            links_json TEXT NOT NULL,
            source_type TEXT,
            source_ref TEXT,
            session_id TEXT,
            cwd TEXT NOT NULL,
            pinned INTEGER NOT NULL DEFAULT 0,
            archived INTEGER NOT NULL DEFAULT 0,
            confidence INTEGER NOT NULL DEFAULT 60,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_memories_scope_namespace_updated
            ON memories(scope, namespace, archived, pinned, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_memories_session_id
            ON memories(session_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_source_ref_unique
            ON memories(source_type, source_ref);
        """
    )
    version_row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if version_row is None:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
    elif str(version_row["value"]) != str(SCHEMA_VERSION):
        raise RuntimeError(
            f"shared-memory schema version {version_row['value']} is incompatible with supported version {SCHEMA_VERSION}; run an explicit migration before opening the store"
        )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('fts_enabled', ?)",
        ("1" if _ensure_fts(conn) else "0",),
    )
    conn.execute("PRAGMA journal_mode=WAL")
    _rebuild_fts(conn)
    conn.commit()


def _ensure_owned_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_memories_scope_namespace_updated
            ON memories(scope, namespace, archived, pinned, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_memories_session_id
            ON memories(session_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_source_ref_unique
            ON memories(source_type, source_ref);
        """
    )


def _ensure_fts(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                id UNINDEXED,
                title,
                summary,
                content,
                tags,
                tokenize = 'porter unicode61'
            )
            """
        )
        return True
    except sqlite3.OperationalError:
        return False


def fts_enabled(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT value FROM meta WHERE key = 'fts_enabled'").fetchone()
    return bool(row and str(row["value"] or "") == "1")


def _rebuild_fts(conn: sqlite3.Connection) -> None:
    if not fts_enabled(conn):
        return
    count_row = conn.execute("SELECT COUNT(*) AS count FROM memory_fts").fetchone()
    if count_row and int(count_row["count"] or 0) > 0:
        return
    conn.execute("DELETE FROM memory_fts")
    conn.execute(
        """
        INSERT INTO memory_fts(rowid, id, title, summary, content, tags)
        SELECT rowid, id, title, summary, content, tags_text
        FROM memories
        """
    )


def inspect_schema(db_path: Path | None = None) -> dict[str, Any]:
    path = (db_path or DEFAULT_DB_PATH).expanduser()
    if not path.exists():
        return {
            "result": "FAIL",
            "path": str(path),
            "reason_code": "shared_memory_database_missing",
            "error": "shared-memory database does not exist",
        }
    connection = None
    try:
        connection = connect_readonly(path, allow_legacy=True)
        inspection = _schema_inspection(connection)
        result = "PASS" if inspection["version_state"] == "current" and inspection["structure_ok"] else "WARN"
        if (
            inspection["version_state"] == "unsupported"
            or not inspection["structure_ok"]
            or inspection["incompatible_indexes"]
            or inspection["owned_triggers"]
        ):
            result = "FAIL"
        payload = {"result": result, "path": str(path), **inspection}
        if result == "FAIL":
            payload["reason_code"] = "shared_memory_schema_incompatible"
            payload["error"] = "shared-memory schema is incompatible"
        return payload
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
        return {
            "result": "FAIL",
            "path": str(path),
            "reason_code": "shared_memory_schema_inspection_failed",
            "error": type(exc).__name__,
        }
    finally:
        if connection is not None:
            connection.close()


def migrate_schema(
    db_path: Path | None = None, *, dry_run: bool = True
) -> dict[str, Any]:
    path = (db_path or DEFAULT_DB_PATH).expanduser()
    report = inspect_schema(path)
    base = {
        "command": "migrate",
        "path": str(path),
        "target_version": SCHEMA_VERSION,
        "dry_run": dry_run,
        "apply": not dry_run,
        "changed": False,
        "would_change": False,
        "transaction_outcome": "not_started",
    }
    if report.get("result") == "FAIL":
        return {**base, **report}
    if report.get("version_state") == "current":
        return {**base, "result": "PASS", "current_version": SCHEMA_VERSION}
    if not report.get("legacy_migration_ready") or report.get("version_state") != "legacy":
        return {
            **base,
            "result": "FAIL",
            "reason_code": "shared_memory_schema_migration_unsupported",
            "error": "only versionless or canonical version 0 stores can migrate",
        }
    base["current_version"] = report.get("version")
    base["would_change"] = True
    if dry_run:
        return {**base, "result": "PASS"}

    connection = None
    phase = "open"
    try:
        canonical, _ = _canonical_preview_path(path)
        connection = sqlite3.connect(str(canonical))
        connection.row_factory = sqlite3.Row
        phase = "begin"
        connection.execute("BEGIN IMMEDIATE")
        inspection = _schema_inspection(connection)
        if (
            not inspection["legacy_migration_ready"]
            or inspection["version_state"] != "legacy"
        ):
            connection.rollback()
            return {
                **base,
                "result": "FAIL",
                "reason_code": "shared_memory_schema_changed",
                "transaction_outcome": "rolled_back",
            }
        phase = "validate"
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        if quick_check is None or str(quick_check[0]).lower() != "ok":
            connection.rollback()
            return {
                **base,
                "result": "FAIL",
                "reason_code": "shared_memory_quick_check_failed",
                "transaction_outcome": "rolled_back",
            }
        phase = "version"
        connection.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        phase = "commit"
        connection.commit()
        return {
            **base,
            "result": "PASS",
            "changed": True,
            "transaction_outcome": "committed",
        }
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
        if connection is not None and connection.in_transaction:
            try:
                connection.rollback()
                outcome = "rolled_back"
            except (OSError, sqlite3.Error, RuntimeError):
                outcome = "unknown"
        else:
            outcome = "unknown" if phase == "commit" else "not_started"
        return {
            **base,
            "result": "FAIL",
            "reason_code": "shared_memory_schema_migration_failed",
            "error": type(exc).__name__,
            "failure_phase": phase,
            "transaction_outcome": outcome,
            "changed": None if outcome == "unknown" else False,
        }
    finally:
        if connection is not None:
            connection.close()


def _next_memory_id(conn: sqlite3.Connection) -> str:
    del conn
    return f"mem-{uuid4().hex[:12]}"


def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
    tags = normalize_tags(json.loads(str(row["tags_json"] or "[]")))
    links_raw = json.loads(str(row["links_json"] or "[]"))
    links = [str(item) for item in links_raw if str(item).strip()]
    return MemoryRecord(
        memory_id=str(row["id"]),
        kind=str(row["kind"]),
        scope=str(row["scope"]),
        namespace=str(row["namespace"]),
        title=str(row["title"]),
        content=str(row["content"]),
        summary=str(row["summary"]),
        tags=tags,
        links=links,
        source_type=str(row["source_type"]) if row["source_type"] else None,
        source_ref=str(row["source_ref"]) if row["source_ref"] else None,
        session_id=str(row["session_id"]) if row["session_id"] else None,
        cwd=str(row["cwd"]),
        pinned=bool(row["pinned"]),
        archived=bool(row["archived"]),
        confidence=int(row["confidence"] or 0),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _upsert_fts(conn: sqlite3.Connection, rowid: int, record: MemoryRecord) -> None:
    if not fts_enabled(conn):
        return
    conn.execute("DELETE FROM memory_fts WHERE rowid = ?", (rowid,))
    conn.execute(
        "INSERT INTO memory_fts(rowid, id, title, summary, content, tags) VALUES (?, ?, ?, ?, ?, ?)",
        (
            rowid,
            record.memory_id,
            record.title,
            record.summary,
            record.content,
            " ".join(record.tags),
        ),
    )


def update_memory_links(
    conn: sqlite3.Connection,
    memory_id: str,
    links: list[str] | str | None,
    *,
    commit: bool = True,
) -> MemoryRecord | None:
    normalized_links = normalize_links(links)
    now = now_iso()
    conn.execute(
        "UPDATE memories SET links_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(normalized_links), now, memory_id),
    )
    row = conn.execute(
        "SELECT rowid, * FROM memories WHERE id = ?",
        (memory_id,),
    ).fetchone()
    if row is None:
        conn.rollback()
        return None
    record = _row_to_record(row)
    record.links = normalized_links
    record.updated_at = now
    _upsert_fts(conn, int(row["rowid"]), record)
    if commit:
        conn.commit()
    return record


def active_memory_records(conn: sqlite3.Connection) -> list[MemoryRecord]:
    rows = conn.execute(
        "SELECT * FROM memories WHERE archived = 0 ORDER BY julianday(updated_at) DESC, julianday(created_at) DESC, updated_at DESC"
    ).fetchall()
    return [_row_to_record(row) for row in rows]


def derive_relationship_links(conn: sqlite3.Connection) -> int:
    records = active_memory_records(conn)
    by_source_ref = {
        record.source_ref: record
        for record in records
        if isinstance(record.source_ref, str) and record.source_ref.strip()
    }
    if not by_source_ref:
        return 0
    records_by_session: dict[tuple[str, str], list[MemoryRecord]] = {}
    for record in records:
        if record.session_id:
            records_by_session.setdefault(
                (_repo_identity(Path(record.cwd)), record.session_id), []
            ).append(record)

    updated = 0
    for record in records:
        derived: list[str] = []
        if record.session_id:
            for related in records_by_session.get(
                (_repo_identity(Path(record.cwd)), record.session_id), []
            ):
                if related.memory_id == record.memory_id or not related.source_ref:
                    continue
                derived.append(internal_memory_link(related.source_ref))
        merged = normalize_links(record.links + derived)
        if merged != record.links:
            if update_memory_links(conn, record.memory_id, merged) is not None:
                updated += 1
    return updated


def _build_record(
    *,
    memory_id: str,
    title: str,
    content: str,
    summary: str | None,
    kind: str,
    scope: str,
    namespace: str,
    tags: list[str] | str | None,
    links: list[str] | str | None,
    source_type: str | None,
    source_ref: str | None,
    confidence: int,
    session_id: str | None,
    cwd: str,
    created_at: str,
    updated_at: str,
    pinned: bool = False,
    archived: bool = False,
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
        kind=normalize_kind(kind),
        scope=normalize_scope(scope),
        namespace=namespace,
        title=title.strip(),
        content=content.strip(),
        summary=(summary or content).strip(),
        tags=normalize_tags(tags),
        links=normalize_links(links),
        source_type=source_type.strip()
        if isinstance(source_type, str) and source_type.strip()
        else None,
        source_ref=source_ref.strip()
        if isinstance(source_ref, str) and source_ref.strip()
        else None,
        session_id=session_id.strip()
        if isinstance(session_id, str) and session_id.strip()
        else None,
        cwd=cwd,
        pinned=pinned,
        archived=archived,
        confidence=normalize_confidence(confidence),
        created_at=created_at,
        updated_at=updated_at,
    )


def _write_record(
    conn: sqlite3.Connection, record: MemoryRecord, *, update_existing: bool
) -> None:
    if update_existing:
        conn.execute(
            """
            UPDATE memories
            SET kind = ?, scope = ?, namespace = ?, title = ?, content = ?, summary = ?,
                tags_json = ?, tags_text = ?, links_json = ?, source_type = ?, source_ref = ?,
                session_id = ?, cwd = ?, archived = ?, confidence = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                record.kind,
                record.scope,
                record.namespace,
                record.title,
                record.content,
                record.summary,
                json.dumps(record.tags),
                " ".join(record.tags),
                json.dumps(record.links),
                record.source_type,
                record.source_ref,
                record.session_id,
                record.cwd,
                1 if record.archived else 0,
                record.confidence,
                record.updated_at,
                record.memory_id,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO memories(
                id, kind, scope, namespace, title, content, summary, tags_json, tags_text,
                links_json, source_type, source_ref, session_id, cwd, pinned, archived,
                confidence, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.memory_id,
                record.kind,
                record.scope,
                record.namespace,
                record.title,
                record.content,
                record.summary,
                json.dumps(record.tags),
                " ".join(record.tags),
                json.dumps(record.links),
                record.source_type,
                record.source_ref,
                record.session_id,
                record.cwd,
                1 if record.pinned else 0,
                1 if record.archived else 0,
                record.confidence,
                record.created_at,
                record.updated_at,
            ),
        )
    row = conn.execute(
        "SELECT rowid FROM memories WHERE id = ?",
        (record.memory_id,),
    ).fetchone()
    if row is not None:
        _upsert_fts(conn, int(row["rowid"]), record)


def add_memory(
    conn: sqlite3.Connection,
    *,
    title: str,
    content: str,
    summary: str | None,
    kind: str,
    scope: str,
    namespace: str,
    tags: list[str],
    links: list[str] | None = None,
    source_type: str | None,
    source_ref: str | None,
    confidence: int,
    session_id: str | None,
    cwd: str,
 ) -> MemoryRecord:
    timestamp = now_iso()
    memory_id = _next_memory_id(conn)
    record = _build_record(
        memory_id=memory_id,
        title=title,
        content=content,
        summary=summary,
        kind=kind,
        scope=scope,
        namespace=namespace,
        tags=tags,
        links=links,
        source_type=source_type,
        source_ref=source_ref,
        confidence=confidence,
        session_id=session_id,
        cwd=cwd,
        created_at=timestamp,
        updated_at=timestamp,
    )
    _write_record(conn, record, update_existing=False)
    conn.commit()
    return record


def upsert_memory_by_source(
    conn: sqlite3.Connection,
    *,
    title: str,
    content: str,
    summary: str | None,
    kind: str,
    scope: str,
    namespace: str,
    tags: list[str] | str | None,
    links: list[str] | str | None,
    source_type: str,
    source_ref: str,
    confidence: int,
    session_id: str | None,
    cwd: str,
    created_at: str | None = None,
    updated_at: str | None = None,
    commit: bool = True,
) -> MemoryRecord:
    created_timestamp = created_at.strip() if isinstance(created_at, str) and created_at.strip() else now_iso()
    updated_timestamp = updated_at.strip() if isinstance(updated_at, str) and updated_at.strip() else created_timestamp
    candidate_id = _next_memory_id(conn)
    tags_list = normalize_tags(tags)
    links_list = normalize_links(links)
    conn.execute(
        """
        INSERT INTO memories(
            id, kind, scope, namespace, title, content, summary, tags_json, tags_text,
            links_json, source_type, source_ref, session_id, cwd, pinned, archived,
            confidence, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?)
        ON CONFLICT(source_type, source_ref) DO UPDATE SET
            kind = excluded.kind,
            scope = excluded.scope,
            namespace = excluded.namespace,
            title = excluded.title,
            content = excluded.content,
            summary = excluded.summary,
            tags_json = excluded.tags_json,
            tags_text = excluded.tags_text,
            links_json = excluded.links_json,
            session_id = COALESCE(excluded.session_id, memories.session_id),
            cwd = excluded.cwd,
            archived = 0,
            confidence = excluded.confidence,
            updated_at = excluded.updated_at
        """,
        (
            candidate_id,
            normalize_kind(kind),
            normalize_scope(scope),
            namespace,
            title.strip(),
            content.strip(),
            (summary or content).strip(),
            json.dumps(tags_list),
            " ".join(tags_list),
            json.dumps(links_list),
            source_type,
            source_ref,
            session_id.strip()
            if isinstance(session_id, str) and session_id.strip()
            else None,
            cwd,
            normalize_confidence(confidence),
            created_timestamp,
            updated_timestamp,
        ),
    )
    row = conn.execute(
        "SELECT rowid, * FROM memories WHERE source_type = ? AND source_ref = ? LIMIT 1",
        (source_type, source_ref),
    ).fetchone()
    if row is None:
        conn.rollback()
        raise RuntimeError(
            f"failed to upsert memory source: {source_type}:{source_ref}"
        )
    record = _row_to_record(row)
    _upsert_fts(conn, int(row["rowid"]), record)
    if commit:
        conn.commit()
    return record


def pin_memory(conn: sqlite3.Connection, memory_id: str) -> MemoryRecord | None:
    now = now_iso()
    conn.execute(
        "UPDATE memories SET pinned = 1, updated_at = ? WHERE id = ?",
        (now, memory_id),
    )
    row = conn.execute(
        "SELECT rowid, * FROM memories WHERE id = ?", (memory_id,)
    ).fetchone()
    if not row:
        conn.rollback()
        return None
    record = _row_to_record(row)
    record.pinned = True
    record.updated_at = now
    _upsert_fts(conn, int(row["rowid"]), record)
    conn.commit()
    return record


def _score_record(
    record: MemoryRecord, lexical_score: float | None
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    if lexical_score is not None:
        normalized = max(0.0, 50.0 - lexical_score)
        score += normalized
        reasons.append(f"lexical={normalized:.2f}")
    if record.pinned:
        score += 25.0
        reasons.append("pinned=25")
    score += float(record.confidence) / 5.0
    reasons.append(f"confidence={float(record.confidence) / 5.0:.2f}")
    updated = _parse_iso(record.updated_at)
    if updated is not None:
        age_hours = max(0.0, (datetime.now(UTC) - updated).total_seconds() / 3600.0)
        recency = max(0.0, 24.0 - min(24.0, age_hours))
        if recency > 0:
            score += recency
            reasons.append(f"recency={recency:.2f}")
    return score, reasons


def _fts_query(query: str) -> str:
    terms = [term.strip() for term in query.split() if term.strip()]
    if not terms:
        return '""'
    normalized: list[str] = []
    for term in terms:
        if any(char in term for char in ":-./"):
            normalized.append('"' + term.replace('"', '""') + '"')
        else:
            normalized.append(term)
    return " ".join(normalized)


def find_memories(
    conn: sqlite3.Connection,
    *,
    query: str,
    limit: int,
    scope: str | None = None,
    namespace: str | None = None,
) -> list[MemoryRecord]:
    if not fts_enabled(conn):
        return _find_memories_like(
            conn,
            query=query,
            limit=limit,
            scope=scope,
            namespace=namespace,
        )
    filters = ["m.archived = 0"]
    params: list[Any] = [_fts_query(query)]
    if scope:
        filters.append("m.scope = ?")
        params.append(scope)
    if namespace:
        filters.append("m.namespace = ?")
        params.append(namespace)
    params.append(max(1, limit))
    try:
        rows = conn.execute(
            f"""
            SELECT m.rowid, m.*, bm25(memory_fts, 10.0, 6.0, 2.0, 1.0) AS lexical_score
            FROM memory_fts
            JOIN memories AS m ON m.rowid = memory_fts.rowid
            WHERE memory_fts MATCH ? AND {" AND ".join(filters)}
            ORDER BY lexical_score ASC, julianday(m.updated_at) DESC, m.updated_at DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    except sqlite3.OperationalError:
        return _find_memories_like(
            conn,
            query=query,
            limit=limit,
            scope=scope,
            namespace=namespace,
        )
    records: list[MemoryRecord] = []
    for row in rows:
        record = _row_to_record(row)
        lexical_score = float(row["lexical_score"] or 0.0)
        record.lexical_score = lexical_score
        record.score, record.score_reasons = _score_record(record, lexical_score)
        records.append(record)
    records.sort(key=lambda item: item.score or 0.0, reverse=True)
    return records


def _find_memories_like(
    conn: sqlite3.Connection,
    *,
    query: str,
    limit: int,
    scope: str | None,
    namespace: str | None,
) -> list[MemoryRecord]:
    filters = ["archived = 0"]
    params: list[Any] = [
        f"%{query}%",
        f"%{query}%",
        f"%{query}%",
        f"%{query}%",
        f"%{query}%",
    ]
    if scope:
        filters.append("scope = ?")
        params.append(scope)
    if namespace:
        filters.append("namespace = ?")
        params.append(namespace)
    params.append(max(1, limit))
    rows = conn.execute(
        f"""
        SELECT rowid, *, 0.0 AS lexical_score
        FROM memories
        WHERE (title LIKE ? OR summary LIKE ? OR content LIKE ? OR source_ref LIKE ? OR tags_text LIKE ?)
          AND {" AND ".join(filters)}
        ORDER BY pinned DESC, julianday(updated_at) DESC, updated_at DESC, confidence DESC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    records: list[MemoryRecord] = []
    for row in rows:
        record = _row_to_record(row)
        record.lexical_score = 0.0
        record.score, record.score_reasons = _score_record(record, 0.0)
        records.append(record)
    return records


def recall_memories(
    conn: sqlite3.Connection,
    *,
    limit: int,
    scope: str | None = None,
    namespace: str | None = None,
    pinned_only: bool = False,
) -> list[MemoryRecord]:
    filters = ["archived = 0"]
    params: list[Any] = []
    if scope:
        filters.append("scope = ?")
        params.append(scope)
    if namespace:
        filters.append("namespace = ?")
        params.append(namespace)
    if pinned_only:
        filters.append("pinned = 1")
    params.append(max(1, limit))
    rows = conn.execute(
        f"""
        SELECT rowid, *
        FROM memories
        WHERE {" AND ".join(filters)}
        ORDER BY pinned DESC, julianday(updated_at) DESC, updated_at DESC, confidence DESC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    records: list[MemoryRecord] = []
    for row in rows:
        record = _row_to_record(row)
        record.score, record.score_reasons = _score_record(record, None)
        records.append(record)
    return records


def summarize_memories(records: list[MemoryRecord]) -> list[str]:
    lines: list[str] = []
    for record in records:
        prefix = f"[{record.kind}/{record.scope}] {record.title}"
        detail = record.summary.strip() or record.content.strip()
        lines.append(f"{prefix}: {detail}")
    return lines


def doctor_report(
    conn: sqlite3.Connection, db_path: Path | None = None
) -> dict[str, Any]:
    path = str((db_path or DEFAULT_DB_PATH).expanduser())
    warnings: list[str] = []
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    schema_version = int(row["value"] or 0) if row else 0
    memory_count = int(
        conn.execute(
            "SELECT COUNT(*) AS count FROM memories WHERE archived = 0"
        ).fetchone()["count"]
    )
    total_memory_count = int(
        conn.execute("SELECT COUNT(*) AS count FROM memories").fetchone()["count"]
    )
    archive_count = total_memory_count - memory_count
    pinned_count = int(
        conn.execute(
            "SELECT COUNT(*) AS count FROM memories WHERE pinned = 1 AND archived = 0"
        ).fetchone()["count"]
    )
    fts_count: int | None = None
    fts_status = "unavailable"
    if not fts_enabled(conn):
        warnings.append("fts5_unavailable_falling_back_to_like_search")
    else:
        fts_count = int(conn.execute("SELECT COUNT(*) AS count FROM memory_fts").fetchone()["count"])
        if fts_count != total_memory_count:
            fts_status = "stale"
            warnings.append("fts_record_count_mismatch")
        else:
            fts_status = "ready"
    if schema_version != SCHEMA_VERSION:
        warnings.append("schema_version_mismatch")
    return {
        "result": "PASS" if not warnings else "WARN",
        "path": path,
        "schema_version": schema_version,
        "memory_count": memory_count,
        "archive_count": archive_count,
        "total_memory_count": total_memory_count,
        "pinned_count": pinned_count,
        "fts_count": fts_count,
        "fts_status": fts_status,
        "warnings": warnings,
    }
