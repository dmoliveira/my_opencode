#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_DB_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_SHARED_MEMORY_PATH",
        "~/.config/opencode/my_opencode/runtime/shared_memory.db",
    )
).expanduser()

SCHEMA_VERSION = 1
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
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _repo_root(cwd: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return str(cwd)
    if result.returncode != 0:
        return str(cwd)
    return result.stdout.strip() or str(cwd)


def _repo_identity(cwd: Path) -> str:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(cwd),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return _repo_root(cwd)
    if result.returncode != 0:
        return _repo_root(cwd)
    return result.stdout.strip() or _repo_root(cwd)


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


def infer_namespace(cwd: Path, scope: str, explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    if scope == "shared":
        return "shared"
    if scope == "session":
        return (
            os.environ.get("OPENCODE_SESSION_ID", "current-session").strip()
            or "current-session"
        )
    return _repo_root(cwd)


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


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = (db_path or DEFAULT_DB_PATH).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    initialize(conn)
    return conn


def initialize(conn: sqlite3.Connection) -> None:
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
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('fts_enabled', ?)",
        ("1" if _ensure_fts(conn) else "0",),
    )
    _rebuild_fts(conn)
    conn.commit()


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
    conn: sqlite3.Connection, memory_id: str, links: list[str] | str | None
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
    conn.commit()
    return record


def active_memory_records(conn: sqlite3.Connection) -> list[MemoryRecord]:
    rows = conn.execute(
        "SELECT * FROM memories WHERE archived = 0 ORDER BY updated_at DESC, created_at DESC"
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
) -> MemoryRecord:
    timestamp = now_iso()
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
            timestamp,
            timestamp,
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
            ORDER BY lexical_score ASC, m.updated_at DESC
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
        ORDER BY pinned DESC, updated_at DESC, confidence DESC
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
        ORDER BY pinned DESC, updated_at DESC, confidence DESC
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
    pinned_count = int(
        conn.execute(
            "SELECT COUNT(*) AS count FROM memories WHERE pinned = 1 AND archived = 0"
        ).fetchone()["count"]
    )
    if not fts_enabled(conn):
        warnings.append("fts5_unavailable_falling_back_to_like_search")
    if schema_version != SCHEMA_VERSION:
        warnings.append("schema_version_mismatch")
    return {
        "result": "PASS" if not warnings else "WARN",
        "path": path,
        "schema_version": schema_version,
        "memory_count": memory_count,
        "pinned_count": pinned_count,
        "warnings": warnings,
    }
