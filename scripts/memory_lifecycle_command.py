#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from shared_memory_runtime import (  # type: ignore
    DEFAULT_DB_PATH,
    SCHEMA_VERSION,
    VALID_KINDS,
    VALID_SCOPES,
    _row_to_record,
    _upsert_fts,
    connect,
    connect_readonly,
    doctor_report,
    inspect_schema,
    migrate_schema,
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


def _write_atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(json.dumps(payload, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


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
    payload = {
        "version": 2,
        "schema_version": SCHEMA_VERSION,
        "path": str(runtime_path()),
        "entries": entries,
        "archive": archive,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["sha256"] = hashlib.sha256(canonical).hexdigest()
    return payload


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
            created_at=str(entry.get("created_at") or "") or None,
            updated_at=str(entry.get("updated_at") or "") or None,
            commit=False,
        )
        if bool(entry.get("archived")):
            conn.execute(
                "UPDATE memories SET archived = 1, updated_at = ? WHERE id = ?",
                (str(entry.get("updated_at") or now_iso()), record.memory_id),
            )
        if entry.get("pinned") is not None:
            conn.execute(
                "UPDATE memories SET pinned = ?, updated_at = ? WHERE id = ?",
                (
                    1 if bool(entry["pinned"]) else 0,
                    str(entry.get("updated_at") or now_iso()),
                    record.memory_id,
                ),
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


_IMPORT_STRING_FIELDS = (
    "id",
    "kind",
    "scope",
    "namespace",
    "title",
    "content",
    "summary",
    "source_type",
    "source_ref",
    "session_id",
    "cwd",
    "created_at",
    "updated_at",
)


def _validate_import_entry(entry: dict[str, Any], location: str) -> None:
    for field in _IMPORT_STRING_FIELDS:
        value = entry.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{location}.{field} must be a string or null")

    for field in ("tags", "links"):
        value = entry.get(field)
        if value is not None and (
            not isinstance(value, list)
            or any(not isinstance(item, str) for item in value)
        ):
            raise ValueError(f"{location}.{field} must be a list of strings or null")

    for field in ("pinned", "archived"):
        value = entry.get(field)
        if value is not None and not isinstance(value, bool):
            raise ValueError(f"{location}.{field} must be a boolean or null")

    confidence = entry.get("confidence")
    if confidence is not None and (
        isinstance(confidence, bool)
        or not isinstance(confidence, int)
        or not 0 <= confidence <= 100
    ):
        raise ValueError(f"{location}.confidence must be an integer from 0 to 100 or null")

    kind = entry.get("kind")
    if kind is not None and kind not in VALID_KINDS:
        raise ValueError(f"{location}.kind is not a supported memory kind")

    scope = entry.get("scope")
    if scope is not None and scope not in VALID_SCOPES:
        raise ValueError(f"{location}.scope is not a supported memory scope")

    source_type = entry.get("source_type")
    source_ref = entry.get("source_ref")
    has_source_type = isinstance(source_type, str) and bool(source_type.strip())
    has_source_ref = isinstance(source_ref, str) and bool(source_ref.strip())
    if has_source_type != has_source_ref:
        raise ValueError(
            f"{location}.source_type and {location}.source_ref must be provided together"
        )


def _validate_import_payload(
    incoming: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    version = incoming.get("version")
    if version is not None and (
        isinstance(version, bool) or not isinstance(version, int) or version not in {1, 2}
    ):
        raise ValueError("unsupported shared-memory export version")

    path = incoming.get("path")
    if path is not None and not isinstance(path, str):
        raise ValueError("shared-memory export path must be a string or null")

    raw_entries = incoming.get("entries", [])
    raw_archive = incoming.get("archive", [])
    if not isinstance(raw_entries, list) or not isinstance(raw_archive, list):
        raise ValueError("entries and archive must be lists")
    validated: list[list[dict[str, Any]]] = []
    for container, values in (("entries", raw_entries), ("archive", raw_archive)):
        if any(not isinstance(entry, dict) for entry in values):
            raise ValueError("every imported entry must be an object")
        typed_values: list[dict[str, Any]] = []
        for index, entry in enumerate(values):
            _validate_import_entry(entry, f"{container}[{index}]")
            typed_values.append(entry)
        validated.append(typed_values)
    return validated[0], validated[1]


def usage() -> int:
    print(
        "usage: /memory-lifecycle stats [--json] | "
        "/memory-lifecycle cleanup [--older-days <n>] [--scope <scope>] [--namespace <name>] [--dry-run] [--json] | "
        "/memory-lifecycle compress [--scope <scope>] [--namespace <name>] [--dry-run] [--json] | "
        "/memory-lifecycle restore --id <id> [--json] | "
        "/memory-lifecycle export --path <file> [--json] | "
        "/memory-lifecycle import --path <file> [--json] | "
        "/memory-lifecycle migrate [--apply|--dry-run] [--json] | "
        "/memory-lifecycle doctor [--json]"
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


RECOVERY_STEPS = [
    "/memory-lifecycle export --path <private-export.json> --json",
    "/memory-lifecycle restore --id <memory-id> --json",
    "/memory-lifecycle import --path <verified-export.json> --json",
]
CANDIDATE_SAMPLE_LIMIT = 20


def _pop_boolean_flag(argv: list[str], flag: str) -> bool:
    count = argv.count(flag)
    if count > 1:
        raise ValueError(f"{flag} may be specified only once")
    if count == 1:
        argv.remove(flag)
        return True
    return False


def _pop_value_flag(argv: list[str], flag: str) -> str | None:
    if argv.count(flag) > 1:
        raise ValueError(f"{flag} may be specified only once")
    return parse_flag_value(argv, flag)


def _parse_archive_options(
    argv: list[str], *, cleanup: bool
) -> tuple[bool, bool, int, str | None, str | None]:
    args = list(argv)
    as_json = _pop_boolean_flag(args, "--json")
    dry_run = _pop_boolean_flag(args, "--dry-run")
    raw_older_days = _pop_value_flag(args, "--older-days") if cleanup else None
    raw_scope = _pop_value_flag(args, "--scope")
    raw_namespace = _pop_value_flag(args, "--namespace")
    if args:
        raise ValueError(f"unexpected argument: {args[0]}")

    older_days = 30
    if raw_older_days is not None:
        older_days = int(raw_older_days)
        if older_days < 1:
            raise ValueError("--older-days must be at least 1")
    scope = raw_scope.strip().lower() if raw_scope is not None else None
    if scope is not None and scope not in VALID_SCOPES:
        raise ValueError("--scope must be session, repo, or shared")
    namespace = raw_namespace.strip() if raw_namespace is not None else None
    if raw_namespace is not None and not namespace:
        raise ValueError("--namespace must not be blank")
    return as_json, dry_run, older_days, scope, namespace


def _parse_restore_options(argv: list[str]) -> tuple[bool, str]:
    args = list(argv)
    as_json = _pop_boolean_flag(args, "--json")
    memory_id = _pop_value_flag(args, "--id")
    if args:
        raise ValueError(f"unexpected argument: {args[0]}")
    if memory_id is None or not memory_id.strip():
        raise ValueError("--id must not be blank")
    return as_json, memory_id.strip()


def _filter_sql(
    *, scope: str | None, namespace: str | None, prefix: str = ""
) -> tuple[str, list[str]]:
    clauses: list[str] = []
    parameters: list[str] = []
    column_prefix = f"{prefix}." if prefix else ""
    if scope is not None:
        clauses.append(f"{column_prefix}scope = ?")
        parameters.append(scope)
    if namespace is not None:
        clauses.append(f"{column_prefix}namespace = ?")
        parameters.append(namespace)
    return "".join(f" AND {clause}" for clause in clauses), parameters


def _base_archive_payload(
    *,
    command: str,
    dry_run: bool,
    scope: str | None,
    namespace: str | None,
) -> dict[str, Any]:
    return {
        "command": command,
        "dry_run": dry_run,
        "scope": scope,
        "namespace": namespace,
        "whole_store": scope is None and namespace is None,
        "automatic_export": False,
        "recovery_steps": list(RECOVERY_STEPS),
    }


def _archive_failure_payload(
    *,
    command: str,
    reason_code: str,
    error: str,
    dry_run: bool,
    scope: str | None,
    namespace: str | None,
    candidate_count: int | None,
    transaction_outcome: str,
    failure_phase: str,
    commit_attempted: bool,
) -> dict[str, Any]:
    alias = "moved" if command == "cleanup" else "removed"
    change_count: int | None = 0 if transaction_outcome != "unknown" else None
    return {
        "result": "FAIL",
        **_base_archive_payload(
            command=command,
            dry_run=dry_run,
            scope=scope,
            namespace=namespace,
        ),
        "reason_code": reason_code,
        "error": error,
        "transaction_outcome": transaction_outcome,
        "failure_phase": failure_phase,
        "commit_attempted": commit_attempted,
        "candidate_count": candidate_count,
        "candidate_sample": [],
        "candidate_sample_truncated": bool(candidate_count),
        "changed_count": change_count,
        alias: change_count,
        "entry_count": None,
        "archive_count": None,
        "projected_entry_count": None,
        "projected_archive_count": None,
    }


def _open_preview_connection() -> sqlite3.Connection | None:
    path = runtime_path().expanduser()
    try:
        return connect_readonly(path)
    except FileNotFoundError:
        return None


def _settle_failed_transaction(
    conn: sqlite3.Connection | None,
    *,
    dry_run: bool,
    phase: str,
    commit_attempted: bool,
) -> tuple[str, str | None]:
    if conn is None:
        return "not_started", None
    if dry_run:
        if conn.in_transaction:
            try:
                conn.rollback()
            except Exception as exc:
                return "not_started", f"read transaction close failed: {exc}"
        return "not_started", None
    if conn.in_transaction:
        try:
            conn.rollback()
        except Exception as exc:
            return "unknown", f"rollback failed: {exc}"
        if conn.in_transaction:
            return "unknown", "rollback did not end the transaction"
        return "rolled_back", None
    if phase in {"open", "begin"} and not commit_attempted:
        return "not_started", None
    return "unknown", None


def _archive_failure_reason(
    *, command: str, dry_run: bool, transaction_outcome: str, phase: str
) -> str:
    if dry_run:
        return "shared_memory_preview_unavailable"
    prefix = "memory_cleanup" if command == "cleanup" else "memory_compression"
    if transaction_outcome == "rolled_back":
        return f"{prefix}_rolled_back"
    if transaction_outcome == "unknown" and phase == "commit":
        return f"{prefix}_commit_outcome_unknown"
    if transaction_outcome == "unknown":
        return f"{prefix}_transaction_outcome_unknown"
    return f"{prefix}_not_started"


def _finalize_connection(
    conn: sqlite3.Connection | None, payload: dict[str, Any]
) -> None:
    if conn is None:
        return
    if payload.get("transaction_outcome") != "committed":
        try:
            if conn.in_transaction:
                conn.rollback()
        except Exception as exc:
            payload.setdefault("warnings", []).append(
                f"connection rollback cleanup failed: {exc}"
            )
    try:
        conn.close()
    except Exception as exc:
        payload.setdefault("warnings", []).append(
            f"connection close cleanup failed: {exc}"
        )


def emit(payload: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        if payload.get("result") != "PASS":
            print(f"error: {payload.get('error', 'memory-lifecycle failed')}")
            for key in (
                "reason_code",
                "failure_phase",
                "transaction_outcome",
                "incompatible_indexes",
                "owned_triggers",
            ):
                if payload.get(key) is not None:
                    print(f"{key}: {payload.get(key)}")
            return 1
        print(f"result: {payload.get('result')}")
        for key in (
            "dry_run",
            "apply",
            "current_version",
            "target_version",
            "would_change",
            "changed",
            "transaction_outcome",
            "candidate_count",
            "changed_count",
            "entry_count",
            "archive_count",
            "restored",
            "outcome",
        ):
            if payload.get(key) is not None:
                print(f"{key}: {payload.get(key)}")
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


def cmd_migrate(argv: list[str]) -> int:
    as_json = "--json" in argv
    apply = "--apply" in argv
    dry_run = "--dry-run" in argv or not apply
    args = [item for item in argv if item not in {"--json", "--apply", "--dry-run"}]
    if args or (apply and "--dry-run" in argv):
        return usage()
    return emit(migrate_schema(runtime_path(), dry_run=dry_run), as_json)


def _cleanup_candidates(
    conn: sqlite3.Connection,
    *,
    cutoff: str,
    scope: str | None,
    namespace: str | None,
    all_rows: bool,
) -> tuple[int, list[dict[str, Any]]]:
    filter_sql, filter_parameters = _filter_sql(
        scope=scope, namespace=namespace
    )
    where_sql = (
        "archived = 0 AND pinned = 0 "
        "AND julianday(COALESCE(NULLIF(updated_at, ''), created_at)) < julianday(?)"
        + filter_sql
    )
    parameters: list[Any] = [cutoff, *filter_parameters]
    candidate_count = int(
        conn.execute(
            f"SELECT COUNT(*) FROM memories WHERE {where_sql}", parameters
        ).fetchone()[0]
    )
    limit_sql = "" if all_rows else f" LIMIT {CANDIDATE_SAMPLE_LIMIT}"
    rows = conn.execute(
        f"""
        SELECT rowid, id, scope
        FROM memories
        WHERE {where_sql}
        ORDER BY
          julianday(COALESCE(NULLIF(updated_at, ''), created_at)) ASC,
          id ASC
        {limit_sql}
        """,
        parameters,
    ).fetchall()
    return candidate_count, [
        {
            "rowid": int(row["rowid"]),
            "id": str(row["id"]),
            "scope": str(row["scope"]),
            "reason_code": "older_than_cutoff",
        }
        for row in rows
    ]


def _compression_key(row: sqlite3.Row) -> tuple[str, ...]:
    source_type = str(row["source_type"] or "").strip()
    source_ref = str(row["source_ref"] or "").strip()
    if source_type and source_ref:
        return ("source", source_type, source_ref)
    return (
        "content",
        str(row["scope"] or ""),
        str(row["namespace"] or ""),
        str(row["title"] or ""),
        str(row["summary"] or ""),
        str(row["content"] or ""),
    )


def _compression_candidates(
    conn: sqlite3.Connection,
    *,
    scope: str | None,
    namespace: str | None,
) -> list[dict[str, Any]]:
    filter_sql, filter_parameters = _filter_sql(
        scope=scope, namespace=namespace
    )
    rows = conn.execute(
        f"""
        SELECT rowid, *
        FROM memories
        WHERE archived = 0{filter_sql}
        ORDER BY
          pinned DESC,
          (julianday(updated_at) IS NULL) ASC,
          julianday(updated_at) DESC,
          (julianday(created_at) IS NULL) ASC,
          julianday(created_at) DESC,
          updated_at DESC,
          created_at DESC,
          id DESC
        """,
        filter_parameters,
    ).fetchall()
    groups: dict[tuple[str, ...], list[sqlite3.Row]] = {}
    for row in rows:
        groups.setdefault(_compression_key(row), []).append(row)

    candidates: list[dict[str, Any]] = []
    for duplicates in groups.values():
        pinned = [row for row in duplicates if bool(row["pinned"])]
        keeper = pinned[0] if pinned else duplicates[0]
        removable = (
            [row for row in duplicates if not bool(row["pinned"])]
            if pinned
            else duplicates[1:]
        )
        for row in removable:
            candidates.append(
                {
                    "rowid": int(row["rowid"]),
                    "id": str(row["id"]),
                    "scope": str(row["scope"]),
                    "reason_code": "duplicate_unpinned",
                    "keeper_id": str(keeper["id"]),
                }
            )
    return sorted(candidates, key=lambda item: item["id"])


def _public_candidate_sample(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in candidate.items() if key != "rowid"}
        for candidate in candidates[:CANDIDATE_SAMPLE_LIMIT]
    ]


def _archive_candidate_rows(
    conn: sqlite3.Connection,
    candidates: list[dict[str, Any]],
    operation_timestamp: str,
) -> int:
    changed = 0
    for candidate in candidates:
        changed += conn.execute(
            """
            UPDATE memories
            SET archived = 1, updated_at = ?
            WHERE rowid = ? AND archived = 0 AND pinned = 0
            """,
            (operation_timestamp, int(candidate["rowid"])),
        ).rowcount
    return changed


def cmd_cleanup(argv: list[str]) -> int:
    try:
        as_json, dry_run, older_days, scope, namespace = _parse_archive_options(
            argv, cleanup=True
        )
    except (TypeError, ValueError):
        return usage()

    cutoff = datetime.now(UTC) - timedelta(days=older_days)
    cutoff_value = cutoff.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    conn: sqlite3.Connection | None = None
    candidate_count: int | None = None
    phase = "open"
    commit_attempted = False
    payload: dict[str, Any]
    try:
        conn = _open_preview_connection() if dry_run else connect()
        if conn is None:
            entry_count = archive_count = 0
            candidates: list[dict[str, Any]] = []
            candidate_count = 0
        else:
            if not dry_run:
                phase = "begin"
                conn.execute("BEGIN IMMEDIATE")
            phase = "plan"
            entry_count, archive_count = _query_counts(conn)
            candidate_count, candidates = _cleanup_candidates(
                conn,
                cutoff=cutoff_value,
                scope=scope,
                namespace=namespace,
                all_rows=not dry_run,
            )
        sample = _public_candidate_sample(candidates)
        changed_count = 0
        if conn is not None and not dry_run:
            phase = "archive"
            changed_count = _archive_candidate_rows(conn, candidates, now_iso())
            entry_count, archive_count = _query_counts(conn)
        projected_entry_count = (
            entry_count - candidate_count if dry_run else entry_count
        )
        projected_archive_count = (
            archive_count + candidate_count if dry_run else archive_count
        )
        payload = {
            "result": "PASS",
            **_base_archive_payload(
                command="cleanup",
                dry_run=dry_run,
                scope=scope,
                namespace=namespace,
            ),
            "older_days": older_days,
            "cutoff": cutoff_value,
            "transaction_outcome": "not_started" if dry_run else "pending",
            "commit_attempted": False,
            "candidate_count": candidate_count,
            "candidate_sample": sample,
            "candidate_sample_truncated": candidate_count > len(sample),
            "changed_count": changed_count,
            "moved": candidate_count if dry_run else changed_count,
            "entry_count": entry_count,
            "archive_count": archive_count,
            "projected_entry_count": projected_entry_count,
            "projected_archive_count": projected_archive_count,
        }
        if conn is not None and not dry_run:
            phase = "commit"
            commit_attempted = True
            conn.commit()
            payload["transaction_outcome"] = "committed"
            payload["commit_attempted"] = True
    except Exception as exc:
        transaction_outcome, settlement_error = _settle_failed_transaction(
            conn,
            dry_run=dry_run,
            phase=phase,
            commit_attempted=commit_attempted,
        )
        error = str(exc)
        if settlement_error:
            error = f"{error}; {settlement_error}"
        payload = _archive_failure_payload(
            command="cleanup",
            reason_code=_archive_failure_reason(
                command="cleanup",
                dry_run=dry_run,
                transaction_outcome=transaction_outcome,
                phase=phase,
            ),
            error=error,
            dry_run=dry_run,
            scope=scope,
            namespace=namespace,
            candidate_count=candidate_count,
            transaction_outcome=transaction_outcome,
            failure_phase=phase,
            commit_attempted=commit_attempted,
        )
    finally:
        _finalize_connection(conn, payload)
    return emit(payload, as_json)


def cmd_compress(argv: list[str]) -> int:
    try:
        as_json, dry_run, _older_days, scope, namespace = _parse_archive_options(
            argv, cleanup=False
        )
    except (TypeError, ValueError):
        return usage()

    conn: sqlite3.Connection | None = None
    candidate_count: int | None = None
    phase = "open"
    commit_attempted = False
    payload: dict[str, Any]
    try:
        conn = _open_preview_connection() if dry_run else connect()
        if conn is None:
            entry_count = archive_count = 0
            candidates: list[dict[str, Any]] = []
            candidate_count = 0
        else:
            if not dry_run:
                phase = "begin"
                conn.execute("BEGIN IMMEDIATE")
            phase = "plan"
            entry_count, archive_count = _query_counts(conn)
            candidates = _compression_candidates(
                conn, scope=scope, namespace=namespace
            )
        candidate_count = len(candidates)
        sample = _public_candidate_sample(candidates)
        before = entry_count
        changed_count = 0
        if conn is not None and not dry_run:
            phase = "archive"
            changed_count = _archive_candidate_rows(conn, candidates, now_iso())
            entry_count, archive_count = _query_counts(conn)
        after = entry_count
        projected_entry_count = (
            entry_count - candidate_count if dry_run else entry_count
        )
        projected_archive_count = (
            archive_count + candidate_count if dry_run else archive_count
        )
        payload = {
            "result": "PASS",
            **_base_archive_payload(
                command="compress",
                dry_run=dry_run,
                scope=scope,
                namespace=namespace,
            ),
            "transaction_outcome": "not_started" if dry_run else "pending",
            "commit_attempted": False,
            "before": before,
            "after": after,
            "candidate_count": candidate_count,
            "candidate_sample": sample,
            "candidate_sample_truncated": candidate_count > len(sample),
            "changed_count": changed_count,
            "removed": candidate_count if dry_run else changed_count,
            "entry_count": entry_count,
            "archive_count": archive_count,
            "projected_entry_count": projected_entry_count,
            "projected_archive_count": projected_archive_count,
        }
        if conn is not None and not dry_run:
            phase = "commit"
            commit_attempted = True
            conn.commit()
            payload["transaction_outcome"] = "committed"
            payload["commit_attempted"] = True
    except Exception as exc:
        transaction_outcome, settlement_error = _settle_failed_transaction(
            conn,
            dry_run=dry_run,
            phase=phase,
            commit_attempted=commit_attempted,
        )
        error = str(exc)
        if settlement_error:
            error = f"{error}; {settlement_error}"
        payload = _archive_failure_payload(
            command="compress",
            reason_code=_archive_failure_reason(
                command="compress",
                dry_run=dry_run,
                transaction_outcome=transaction_outcome,
                phase=phase,
            ),
            error=error,
            dry_run=dry_run,
            scope=scope,
            namespace=namespace,
            candidate_count=candidate_count,
            transaction_outcome=transaction_outcome,
            failure_phase=phase,
            commit_attempted=commit_attempted,
        )
        payload.update({"before": None, "after": None})
    finally:
        _finalize_connection(conn, payload)
    return emit(payload, as_json)


def cmd_restore(argv: list[str]) -> int:
    try:
        as_json, memory_id = _parse_restore_options(argv)
    except ValueError:
        return usage()

    conn: sqlite3.Connection | None = None
    phase = "open"
    commit_attempted = False
    payload: dict[str, Any]
    try:
        conn = connect()
        phase = "begin"
        conn.execute("BEGIN IMMEDIATE")
        phase = "plan"
        row = conn.execute(
            "SELECT archived, updated_at FROM memories WHERE id = ?",
            (memory_id,),
        ).fetchone()
        if row is None:
            conn.rollback()
            payload = {
                "result": "FAIL",
                "command": "restore",
                "id": memory_id,
                "reason_code": "memory_not_found",
                "outcome": "not_found",
                "transaction_outcome": "rolled_back",
                "failure_phase": "plan",
                "commit_attempted": False,
                "restored": 0,
                "changed": False,
                "automatic_export": False,
                "recovery_steps": list(RECOVERY_STEPS),
                "error": "shared memory ID was not found",
            }
        elif not bool(row["archived"]):
            conn.rollback()
            payload = {
                "result": "PASS",
                "command": "restore",
                "id": memory_id,
                "reason_code": "already_active",
                "outcome": "already_active",
                "transaction_outcome": "rolled_back",
                "commit_attempted": False,
                "restored": 0,
                "changed": False,
                "automatic_export": False,
                "recovery_steps": list(RECOVERY_STEPS),
            }
        else:
            phase = "archive"
            restored = conn.execute(
                "UPDATE memories SET archived = 0, updated_at = ? WHERE id = ? AND archived = 1",
                (now_iso(), memory_id),
            ).rowcount
            payload = {
                "result": "PASS",
                "command": "restore",
                "id": memory_id,
                "reason_code": "memory_restored",
                "outcome": "restored",
                "transaction_outcome": "pending",
                "commit_attempted": False,
                "restored": restored,
                "changed": restored == 1,
                "automatic_export": False,
                "recovery_steps": list(RECOVERY_STEPS),
            }
            phase = "commit"
            commit_attempted = True
            conn.commit()
            payload["transaction_outcome"] = "committed"
            payload["commit_attempted"] = True
    except Exception as exc:
        transaction_outcome, settlement_error = _settle_failed_transaction(
            conn,
            dry_run=False,
            phase=phase,
            commit_attempted=commit_attempted,
        )
        error = str(exc)
        if settlement_error:
            error = f"{error}; {settlement_error}"
        unknown = transaction_outcome == "unknown"
        payload = {
            "result": "FAIL",
            "command": "restore",
            "id": memory_id,
            "reason_code": (
                "memory_restore_commit_outcome_unknown"
                if unknown and phase == "commit"
                else (
                    "memory_restore_transaction_outcome_unknown"
                    if unknown
                    else (
                        "memory_restore_rolled_back"
                        if transaction_outcome == "rolled_back"
                        else "memory_restore_not_started"
                    )
                )
            ),
            "outcome": "unknown" if unknown else "failed",
            "transaction_outcome": transaction_outcome,
            "failure_phase": phase,
            "commit_attempted": commit_attempted,
            "restored": None if unknown else 0,
            "changed": None if unknown else False,
            "automatic_export": False,
            "recovery_steps": list(RECOVERY_STEPS),
            "error": error,
        }
    finally:
        _finalize_connection(conn, payload)
    return emit(payload, as_json)


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
    dry_run = "--dry-run" in argv
    argv = [a for a in argv if a not in {"--json", "--dry-run"}]
    try:
        path_arg = parse_flag_value(argv, "--path")
        conflict_policy = parse_flag_value(argv, "--conflict") or "overwrite"
    except ValueError:
        return usage()
    if not path_arg or conflict_policy not in {"overwrite", "skip"}:
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
    expected_digest = incoming.pop("sha256", None)
    if expected_digest is not None:
        canonical = json.dumps(incoming, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if not isinstance(expected_digest, str) or hashlib.sha256(canonical).hexdigest() != expected_digest:
            return emit({"result": "FAIL", "command": "import", "error": "shared-memory export checksum mismatch"}, as_json)
    schema_version = incoming.get("schema_version")
    if schema_version is not None and (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != SCHEMA_VERSION
    ):
        return emit({"result": "FAIL", "command": "import", "error": "incompatible shared-memory export schema"}, as_json)
    try:
        new_entries, archived_entries = _validate_import_payload(incoming)
    except ValueError as exc:
        return emit(
            {"result": "FAIL", "command": "import", "error": str(exc)},
            as_json,
        )
    if dry_run:
        return emit(
            {
                "result": "PASS",
                "command": "import",
                "dry_run": True,
                "imported": len(new_entries) + len(archived_entries),
                "backup_path": None,
            },
            as_json,
        )
    conn: sqlite3.Connection | None = None
    backup_path = source.with_name(f"{source.stem}.pre-import-{uuid.uuid4().hex}.json")
    phase = "open"
    commit_attempted = False
    try:
        conn = connect()
        phase = "begin"
        conn.execute("BEGIN IMMEDIATE")
        phase = "backup"
        _write_atomic_json(backup_path, _export_payload(conn))
        skipped = 0
        phase = "import"
        for entry in new_entries + archived_entries:
            source_type = entry.get("source_type")
            source_ref = entry.get("source_ref")
            if conflict_policy == "skip":
                if (
                    isinstance(source_type, str)
                    and source_type.strip()
                    and isinstance(source_ref, str)
                    and source_ref.strip()
                ):
                    existing = conn.execute(
                        "SELECT 1 FROM memories WHERE source_type = ? AND source_ref = ? LIMIT 1",
                        (source_type, source_ref),
                    ).fetchone()
                else:
                    memory_id = entry.get("id")
                    existing = (
                        conn.execute(
                            "SELECT 1 FROM memories WHERE id = ? LIMIT 1",
                            (memory_id,),
                        ).fetchone()
                        if isinstance(memory_id, str) and memory_id
                        else None
                    )
                if existing:
                    skipped += 1
                    continue
            _import_row(conn, entry)
        entry_count, archive_count = _query_counts(conn)
        phase = "commit"
        commit_attempted = True
        conn.commit()
    except Exception as exc:
        transaction_outcome, settlement_error = _settle_failed_transaction(
            conn,
            dry_run=False,
            phase=phase,
            commit_attempted=commit_attempted,
        )
        error = str(exc)
        if settlement_error:
            error = f"{error}; {settlement_error}"
        prefix = (
            "import rolled back"
            if transaction_outcome == "rolled_back"
            else (
                "import transaction outcome unknown"
                if transaction_outcome == "unknown"
                else "import failed"
            )
        )
        return emit(
            {
                "result": "FAIL",
                "command": "import",
                "error": f"{prefix}: {error}",
                "transaction_outcome": transaction_outcome,
                "failure_phase": phase,
                "commit_attempted": commit_attempted,
            },
            as_json,
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return emit(
        {
            "result": "PASS",
            "command": "import",
            "imported": len(new_entries) + len(archived_entries),
            "dry_run": False,
            "conflict_policy": conflict_policy,
            "skipped": skipped,
            "backup_path": str(backup_path),
            "entry_count": entry_count,
            "archive_count": archive_count,
        },
        as_json,
    )


def cmd_doctor(argv: list[str]) -> int:
    as_json = "--json" in argv
    schema = inspect_schema(runtime_path())
    if schema.get("result") == "FAIL":
        schema["quick_fixes"] = [
            "/memory-lifecycle migrate --dry-run --json",
            "/memory-lifecycle migrate --apply --json",
        ]
        return emit({"command": "doctor", **schema}, as_json)
    try:
        conn = connect()
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        return emit(
            {
                "result": "FAIL",
                "command": "doctor",
                "path": str(runtime_path()),
                "reason_code": "shared_memory_doctor_open_failed",
                "error": type(exc).__name__,
            },
            as_json,
        )
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
    if command == "migrate":
        return cmd_migrate(rest)
    if command == "cleanup":
        return cmd_cleanup(rest)
    if command == "compress":
        return cmd_compress(rest)
    if command == "restore":
        return cmd_restore(rest)
    if command == "export":
        return cmd_export(rest)
    if command == "import":
        return cmd_import(rest)
    if command == "doctor":
        return cmd_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
