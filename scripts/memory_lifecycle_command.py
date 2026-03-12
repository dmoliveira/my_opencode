#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from shared_memory_runtime import (  # type: ignore
    _row_to_record,
    _upsert_fts,
    DEFAULT_DB_PATH,
    connect,
    doctor_report,
    normalize_confidence,
    normalize_kind,
    normalize_scope,
    normalize_tags,
    now_iso,
    upsert_memory_by_source,
)


DEFAULT_MEMORY_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_MEMORY_LIFECYCLE_PATH",
        "~/.config/opencode/my_opencode/runtime/memory_store.json",
    )
).expanduser()


def runtime_path() -> Path:
    return DEFAULT_DB_PATH


def _query_counts(conn: sqlite3.Connection) -> tuple[int, int]:
    active = int(
        conn.execute(
            "SELECT COUNT(*) AS count FROM memories WHERE archived = 0"
        ).fetchone()["count"]
    )
    archived = int(
        conn.execute(
            "SELECT COUNT(*) AS count FROM memories WHERE archived = 1"
        ).fetchone()["count"]
    )
    return active, archived


def _export_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT * FROM memories ORDER BY archived ASC, updated_at DESC, created_at DESC"
    ).fetchall()
    entries: list[dict[str, Any]] = []
    archive: list[dict[str, Any]] = []
    for row in rows:
        payload = {
            "id": str(row["id"]),
            "kind": str(row["kind"]),
            "scope": str(row["scope"]),
            "namespace": str(row["namespace"]),
            "title": str(row["title"]),
            "content": str(row["content"]),
            "summary": str(row["summary"]),
            "tags": json.loads(str(row["tags_json"] or "[]")),
            "links": json.loads(str(row["links_json"] or "[]")),
            "source_type": str(row["source_type"]) if row["source_type"] else None,
            "source_ref": str(row["source_ref"]) if row["source_ref"] else None,
            "session_id": str(row["session_id"]) if row["session_id"] else None,
            "cwd": str(row["cwd"]),
            "pinned": bool(row["pinned"]),
            "archived": bool(row["archived"]),
            "confidence": int(row["confidence"] or 0),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }
        if payload["archived"]:
            archive.append(payload)
        else:
            entries.append(payload)
    return {
        "version": 2,
        "path": str(runtime_path()),
        "entries": entries,
        "archive": archive,
    }


def _import_row(conn: sqlite3.Connection, entry: dict[str, Any]) -> None:
    source_type = entry.get("source_type")
    source_ref = entry.get("source_ref")
    if (
        isinstance(source_type, str)
        and source_type.strip()
        and isinstance(source_ref, str)
        and source_ref.strip()
    ):
        record = upsert_memory_by_source(
            conn,
            title=str(entry.get("title") or "Imported memory"),
            content=str(entry.get("content") or ""),
            summary=str(entry.get("summary") or entry.get("content") or ""),
            kind=str(entry.get("kind") or "note"),
            scope=str(entry.get("scope") or "repo"),
            namespace=str(entry.get("namespace") or "shared"),
            tags=entry.get("tags") if isinstance(entry.get("tags"), list) else [],
            links=entry.get("links") if isinstance(entry.get("links"), list) else [],
            source_type=source_type,
            source_ref=source_ref,
            confidence=normalize_confidence(entry.get("confidence")),
            session_id=str(entry.get("session_id") or "") or None,
            cwd=str(entry.get("cwd") or os.getcwd()),
        )
        if bool(entry.get("archived")):
            conn.execute(
                "UPDATE memories SET archived = 1, updated_at = ? WHERE id = ?",
                (str(entry.get("updated_at") or now_iso()), record.memory_id),
            )
        if bool(entry.get("pinned")):
            conn.execute(
                "UPDATE memories SET pinned = 1, updated_at = ? WHERE id = ?",
                (str(entry.get("updated_at") or now_iso()), record.memory_id),
            )
        return
    memory_id = str(entry.get("id") or f"legacy-{os.urandom(4).hex()}")
    conn.execute(
        """
        INSERT OR REPLACE INTO memories(
            id, kind, scope, namespace, title, content, summary, tags_json, tags_text,
            links_json, source_type, source_ref, session_id, cwd, pinned, archived,
            confidence, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            memory_id,
            normalize_kind(str(entry.get("kind") or "note")),
            normalize_scope(str(entry.get("scope") or "repo")),
            str(entry.get("namespace") or "shared"),
            str(entry.get("title") or "Imported memory"),
            str(entry.get("content") or ""),
            str(entry.get("summary") or entry.get("content") or ""),
            json.dumps(
                normalize_tags(
                    entry.get("tags") if isinstance(entry.get("tags"), list) else []
                )
            ),
            " ".join(
                normalize_tags(
                    entry.get("tags") if isinstance(entry.get("tags"), list) else []
                )
            ),
            json.dumps(
                entry.get("links") if isinstance(entry.get("links"), list) else []
            ),
            None,
            None,
            str(entry.get("session_id") or "") or None,
            str(entry.get("cwd") or os.getcwd()),
            1 if bool(entry.get("pinned")) else 0,
            1 if bool(entry.get("archived")) else 0,
            normalize_confidence(entry.get("confidence")),
            str(entry.get("created_at") or now_iso()),
            str(entry.get("updated_at") or now_iso()),
        ),
    )
    row = conn.execute(
        "SELECT rowid, * FROM memories WHERE id = ?", (memory_id,)
    ).fetchone()
    if row is not None:
        _upsert_fts(conn, int(row["rowid"]), _row_to_record(row))


def usage() -> int:
    print(
        "usage: /memory-lifecycle stats [--json] | /memory-lifecycle cleanup [--older-days <n>] [--json] | "
        "/memory-lifecycle compress [--json] | /memory-lifecycle export --path <file> [--json] | "
        "/memory-lifecycle import --path <file> [--json] | /memory-lifecycle doctor [--json]"
    )
    return 2


def load_store(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "entries": [], "archive": []}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {"version": 1, "entries": [], "archive": []}
    entries = raw.get("entries") if isinstance(raw.get("entries"), list) else []
    archive = raw.get("archive") if isinstance(raw.get("archive"), list) else []
    return {
        "version": int(raw.get("version", 1) or 1),
        "entries": entries,
        "archive": archive,
    }


def save_store(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def parse_flag_value(argv: list[str], flag: str) -> str | None:
    if flag not in argv:
        return None
    idx = argv.index(flag)
    if idx + 1 >= len(argv):
        raise ValueError(f"{flag} requires value")
    value = argv[idx + 1]
    del argv[idx : idx + 2]
    return value


def emit(payload: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        if payload.get("result") != "PASS":
            print(f"error: {payload.get('error', 'memory-lifecycle failed')}")
            return 1
        print(f"result: {payload.get('result')}")
        if payload.get("entry_count") is not None:
            print(f"entry_count: {payload.get('entry_count')}")
    return 0 if payload.get("result") == "PASS" else 1


def cmd_stats(argv: list[str]) -> int:
    as_json = "--json" in argv
    conn = connect()
    entry_count, archive_count = _query_counts(conn)
    return emit(
        {
            "result": "PASS",
            "command": "stats",
            "path": str(runtime_path()),
            "entry_count": entry_count,
            "archive_count": archive_count,
        },
        as_json,
    )


def cmd_cleanup(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    older_days = 30
    try:
        raw = parse_flag_value(argv, "--older-days")
        if raw is not None:
            older_days = max(1, int(raw))
    except (ValueError, TypeError):
        return usage()
    conn = connect()
    cutoff = datetime.now(UTC) - timedelta(days=older_days)
    moved = conn.execute(
        """
        UPDATE memories
        SET archived = 1, updated_at = ?
        WHERE archived = 0
          AND pinned = 0
          AND COALESCE(updated_at, created_at, '') < ?
        """,
        (now_iso(), cutoff.replace(microsecond=0).isoformat().replace("+00:00", "Z")),
    ).rowcount
    conn.commit()
    entry_count, archive_count = _query_counts(conn)
    return emit(
        {
            "result": "PASS",
            "command": "cleanup",
            "moved": moved,
            "entry_count": entry_count,
            "archive_count": archive_count,
        },
        as_json,
    )


def cmd_compress(argv: list[str]) -> int:
    as_json = "--json" in argv
    conn = connect()
    rows = conn.execute(
        "SELECT rowid, * FROM memories WHERE archived = 0 ORDER BY pinned DESC, updated_at DESC, created_at DESC"
    ).fetchall()
    before = len(rows)
    seen: set[str] = set()
    removed = 0
    for row in rows:
        key = str(row["source_type"] or "") + ":" + str(row["source_ref"] or "")
        if (
            not str(row["source_type"] or "").strip()
            or not str(row["source_ref"] or "").strip()
        ):
            key = (
                str(row["scope"] or "")
                + ":"
                + str(row["namespace"] or "")
                + ":"
                + str(row["title"] or "")
                + ":"
                + str(row["summary"] or "")
                + ":"
                + str(row["content"] or "")
            )
        if key in seen:
            if bool(row["pinned"]):
                continue
            conn.execute(
                "UPDATE memories SET archived = 1, updated_at = ? WHERE rowid = ?",
                (now_iso(), int(row["rowid"])),
            )
            removed += 1
            continue
        seen.add(key)
    conn.commit()
    after, archive_count = _query_counts(conn)
    return emit(
        {
            "result": "PASS",
            "command": "compress",
            "before": before,
            "after": after,
            "removed": removed,
            "archive_count": archive_count,
        },
        as_json,
    )


def cmd_export(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    try:
        path_arg = parse_flag_value(argv, "--path")
    except ValueError:
        return usage()
    if not path_arg:
        return usage()
    target = Path(path_arg).expanduser()
    conn = connect()
    store = _export_payload(conn)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
    return emit(
        {
            "result": "PASS",
            "command": "export",
            "path": str(target),
            "entry_count": len(store["entries"]),
            "archive_count": len(store["archive"]),
        },
        as_json,
    )


def cmd_import(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    try:
        path_arg = parse_flag_value(argv, "--path")
    except ValueError:
        return usage()
    if not path_arg:
        return usage()
    source = Path(path_arg).expanduser()
    if not source.exists():
        return emit(
            {
                "result": "FAIL",
                "command": "import",
                "error": f"file not found: {source}",
            },
            as_json,
        )
    incoming = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(incoming, dict):
        return emit(
            {
                "result": "FAIL",
                "command": "import",
                "error": "invalid memory export format",
            },
            as_json,
        )
    conn = connect()
    new_entries = (
        [entry for entry in incoming.get("entries", []) if isinstance(entry, dict)]
        if isinstance(incoming.get("entries"), list)
        else []
    )
    archived_entries = (
        [entry for entry in incoming.get("archive", []) if isinstance(entry, dict)]
        if isinstance(incoming.get("archive"), list)
        else []
    )
    for entry in new_entries + archived_entries:
        _import_row(conn, entry)
    conn.commit()
    entry_count, archive_count = _query_counts(conn)
    return emit(
        {
            "result": "PASS",
            "command": "import",
            "imported": len(new_entries) + len(archived_entries),
            "entry_count": entry_count,
            "archive_count": archive_count,
        },
        as_json,
    )


def cmd_doctor(argv: list[str]) -> int:
    as_json = "--json" in argv
    conn = connect()
    report = doctor_report(conn, runtime_path())
    report["command"] = "doctor"
    report.setdefault(
        "quick_fixes",
        [
            '/memory add --title "note" --content "..." --json',
            "/memory-lifecycle stats --json",
        ],
    )
    return emit(report, as_json)


def main(argv: list[str]) -> int:
    if not argv:
        return usage()
    command = argv[0]
    rest = argv[1:]
    if command in {"help", "-h", "--help"}:
        return usage()
    if command == "stats":
        return cmd_stats(rest)
    if command == "cleanup":
        return cmd_cleanup(rest)
    if command == "compress":
        return cmd_compress(rest)
    if command == "export":
        return cmd_export(rest)
    if command == "import":
        return cmd_import(rest)
    if command == "doctor":
        return cmd_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
