#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from shared_memory_runtime import (  # type: ignore
    active_memory_records,
    DEFAULT_DB_PATH,
    add_memory,
    connect,
    derive_relationship_links,
    doctor_report,
    find_memories,
    infer_namespace,
    normalize_confidence,
    normalize_kind,
    normalize_scope,
    normalize_tags,
    pin_memory,
    recall_memories,
    summarize_memories,
    upsert_memory_by_source,
)


DEFAULT_DIGEST_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_DIGEST_PATH", "~/.config/opencode/digests/last-session.json"
    )
).expanduser()
DEFAULT_SESSION_INDEX_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_SESSION_INDEX_PATH", "~/.config/opencode/sessions/index.json"
    )
).expanduser()
DEFAULT_WORKFLOW_STATE_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_WORKFLOW_STATE_PATH",
        "~/.config/opencode/my_opencode/runtime/workflow_state.json",
    )
).expanduser()
DEFAULT_CLAIMS_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_CLAIMS_PATH",
        "~/.config/opencode/my_opencode/runtime/claims.json",
    )
).expanduser()
DEFAULT_DOCTOR_REPORT_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_DOCTOR_REPORT_PATH",
        "~/.config/opencode/my_opencode/runtime/doctor_report.json",
    )
).expanduser()
PROMOTION_SOURCES = {"digest", "session", "workflow", "claims", "doctor", "all"}


def usage() -> int:
    print(
        "usage: /memory add --title <text> --content <text> [--summary <text>] "
        "[--kind <note|decision|blocker|artifact|summary|validation>] "
        "[--scope <session|repo|shared>] [--namespace <text>] [--tags a,b] "
        "[--source-type <text>] [--source-ref <text>] [--confidence <0-100>] [--json] | "
        "/memory find <query> [--limit <n>] [--scope <scope>] [--namespace <text>] [--json] | "
        "/memory recall [--limit <n>] [--scope <scope>] [--namespace <text>] [--pinned-only] [--json] | "
        "/memory pin <id> [--json] | /memory summarize [--limit <n>] [--scope <scope>] "
        "[--namespace <text>] [--query <text>] [--json] | /memory promote [--source <digest|session|workflow|claims|doctor|all>] [--limit <n>] [--json] | /memory doctor [--json]"
    )
    return 2


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def load_doctor_report() -> dict[str, Any]:
    return load_json_file(DEFAULT_DOCTOR_REPORT_PATH)


def limit_rows(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    rows = [item for item in items if isinstance(item, dict)]
    rows.sort(
        key=lambda item: str(
            item.get("updated_at")
            or item.get("finished_at")
            or item.get("last_event_at")
            or item.get("timestamp")
            or ""
        ),
        reverse=True,
    )
    return rows[: max(1, limit)]


def parse_flag_value(argv: list[str], flag: str) -> str | None:
    if flag not in argv:
        return None
    idx = argv.index(flag)
    if idx + 1 >= len(argv):
        raise ValueError(f"{flag} requires value")
    value = argv[idx + 1]
    del argv[idx : idx + 2]
    return value


def parse_limit(argv: list[str], default: int = 10) -> int:
    raw = parse_flag_value(argv, "--limit")
    if raw is None:
        return default
    return max(1, int(raw))


def emit(payload: dict, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("result") in {"PASS", "WARN"} else 1
    if payload.get("result") == "FAIL":
        print(f"error: {payload.get('error', 'memory command failed')}")
        return 1
    command = payload.get("command")
    if command in {"find", "recall"}:
        print(f"result: {payload.get('result')}")
        print(f"count: {payload.get('count', 0)}")
        for item in payload.get("memories", []):
            print(
                f"- {item.get('id')} | {item.get('title')} | scope={item.get('scope')} "
                f"| pinned={'yes' if item.get('pinned') else 'no'}"
            )
        return 0
    if command == "summarize":
        print(f"result: {payload.get('result')}")
        for line in payload.get("lines", []):
            print(f"- {line}")
        return 0
    if command == "doctor":
        print("memory doctor")
        print("-------------")
        print(f"path: {payload.get('path')}")
        print(f"schema_version: {payload.get('schema_version')}")
        print(f"memory_count: {payload.get('memory_count')}")
        print(f"pinned_count: {payload.get('pinned_count')}")
        for warning in payload.get("warnings", []):
            print(f"- warning: {warning}")
        print(f"result: {payload.get('result')}")
        return 0 if payload.get("result") in {"PASS", "WARN"} else 1
    print(f"result: {payload.get('result')}")
    if payload.get("memory") and isinstance(payload.get("memory"), dict):
        memory = payload["memory"]
        print(f"id: {memory.get('id')}")
        print(f"title: {memory.get('title')}")
        print(f"scope: {memory.get('scope')}")
        print(f"namespace: {memory.get('namespace')}")
    return 0


def cmd_add(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [arg for arg in argv if arg != "--json"]
    try:
        title = parse_flag_value(argv, "--title")
        content = parse_flag_value(argv, "--content")
        summary = parse_flag_value(argv, "--summary")
        kind = normalize_kind(parse_flag_value(argv, "--kind"))
        scope = normalize_scope(parse_flag_value(argv, "--scope"))
        namespace = parse_flag_value(argv, "--namespace")
        tags = normalize_tags(parse_flag_value(argv, "--tags"))
        source_type = parse_flag_value(argv, "--source-type")
        source_ref = parse_flag_value(argv, "--source-ref")
        confidence = normalize_confidence(parse_flag_value(argv, "--confidence"))
    except (TypeError, ValueError):
        return usage()
    if argv or not title or not content:
        return usage()
    cwd = Path.cwd()
    inferred_namespace = infer_namespace(cwd, scope, namespace)
    conn = connect()
    record = add_memory(
        conn,
        title=title,
        content=content,
        summary=summary,
        kind=kind,
        scope=scope,
        namespace=inferred_namespace,
        tags=tags,
        source_type=source_type,
        source_ref=source_ref,
        confidence=confidence,
        session_id=os.environ.get("OPENCODE_SESSION_ID", "").strip() or None,
        cwd=str(cwd),
    )
    return emit(
        {
            "result": "PASS",
            "command": "add",
            "path": str(DEFAULT_DB_PATH),
            "memory": record.to_payload(),
        },
        as_json,
    )


def cmd_find(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [arg for arg in argv if arg != "--json"]
    try:
        limit = parse_limit(argv)
        scope = parse_flag_value(argv, "--scope")
        namespace = parse_flag_value(argv, "--namespace")
    except (TypeError, ValueError):
        return usage()
    if not argv:
        return usage()
    query = " ".join(argv).strip()
    if not query:
        return usage()
    conn = connect()
    records = find_memories(
        conn,
        query=query,
        limit=limit,
        scope=normalize_scope(scope) if scope else None,
        namespace=namespace,
    )
    return emit(
        {
            "result": "PASS",
            "command": "find",
            "query": query,
            "count": len(records),
            "memories": [record.to_payload() for record in records],
        },
        as_json,
    )


def cmd_recall(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [arg for arg in argv if arg != "--json"]
    pinned_only = "--pinned-only" in argv
    argv = [arg for arg in argv if arg != "--pinned-only"]
    try:
        limit = parse_limit(argv)
        scope = parse_flag_value(argv, "--scope")
        namespace = parse_flag_value(argv, "--namespace")
    except (TypeError, ValueError):
        return usage()
    if argv:
        return usage()
    conn = connect()
    records = recall_memories(
        conn,
        limit=limit,
        scope=normalize_scope(scope) if scope else None,
        namespace=namespace,
        pinned_only=pinned_only,
    )
    return emit(
        {
            "result": "PASS",
            "command": "recall",
            "count": len(records),
            "memories": [record.to_payload() for record in records],
        },
        as_json,
    )


def cmd_pin(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [arg for arg in argv if arg != "--json"]
    if len(argv) != 1:
        return usage()
    conn = connect()
    record = pin_memory(conn, argv[0])
    if record is None:
        return emit(
            {
                "result": "FAIL",
                "command": "pin",
                "error": f"memory not found: {argv[0]}",
            },
            as_json,
        )
    return emit(
        {"result": "PASS", "command": "pin", "memory": record.to_payload()},
        as_json,
    )


def cmd_summarize(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [arg for arg in argv if arg != "--json"]
    try:
        limit = parse_limit(argv, default=5)
        scope = parse_flag_value(argv, "--scope")
        namespace = parse_flag_value(argv, "--namespace")
        query = parse_flag_value(argv, "--query")
    except (TypeError, ValueError):
        return usage()
    if argv:
        return usage()
    conn = connect()
    if query:
        records = find_memories(
            conn,
            query=query,
            limit=limit,
            scope=normalize_scope(scope) if scope else None,
            namespace=namespace,
        )
    else:
        records = recall_memories(
            conn,
            limit=limit,
            scope=normalize_scope(scope) if scope else None,
            namespace=namespace,
        )
    lines = summarize_memories(records)
    return emit(
        {
            "result": "PASS",
            "command": "summarize",
            "count": len(records),
            "lines": lines,
            "memories": [record.to_payload() for record in records],
        },
        as_json,
    )


def promote_digest(conn, *, cwd: Path) -> list[dict[str, Any]]:
    digest = load_json_file(DEFAULT_DIGEST_PATH)
    if not digest:
        return []
    raw_git = digest.get("git")
    git: dict[str, Any] = raw_git if isinstance(raw_git, dict) else {}
    raw_plan = digest.get("plan_execution")
    plan: dict[str, Any] = raw_plan if isinstance(raw_plan, dict) else {}
    raw_session_index = digest.get("session_index")
    session_index: dict[str, Any] = (
        raw_session_index if isinstance(raw_session_index, dict) else {}
    )
    reason = str(digest.get("reason") or "manual")
    timestamp = str(digest.get("timestamp") or "unknown")
    record = upsert_memory_by_source(
        conn,
        title=f"Digest {reason} {timestamp}",
        content="\n".join(
            [
                f"timestamp: {timestamp}",
                f"cwd: {digest.get('cwd')}",
                f"branch: {git.get('branch')}",
                f"changes: {git.get('status_count')}",
                f"plan_status: {plan.get('status')}",
                f"plan_id: {plan.get('plan_id')}",
                f"session_id: {session_index.get('session_id')}",
            ]
        ),
        summary=(
            f"reason={reason}; branch={git.get('branch')}; changes={git.get('status_count')}; "
            f"plan_status={plan.get('status')}"
        ),
        kind="summary",
        scope="repo",
        namespace=infer_namespace(cwd, "repo"),
        tags=["digest", reason, str(plan.get("status") or "idle")],
        links=[str(DEFAULT_DIGEST_PATH)],
        source_type="digest",
        source_ref=f"digest:{timestamp}:{reason}",
        confidence=82,
        session_id=str(
            session_index.get("session_id")
            or os.environ.get("OPENCODE_SESSION_ID", "")
            or ""
        )
        or None,
        cwd=str(digest.get("cwd") or cwd),
    )
    return [record.to_payload()]


def promote_sessions(conn, *, cwd: Path, limit: int) -> list[dict[str, Any]]:
    payload = load_json_file(DEFAULT_SESSION_INDEX_PATH)
    session_rows: list[dict[str, Any]] = (
        [item for item in payload.get("sessions", []) if isinstance(item, dict)]
        if isinstance(payload.get("sessions"), list)
        else []
    )
    rows = limit_rows(session_rows, limit)
    promoted: list[dict[str, Any]] = []
    for row in rows:
        session_id = str(row.get("session_id") or "")
        if not session_id:
            continue
        events = row.get("events") if isinstance(row.get("events"), list) else []
        last_event: dict[str, Any] = (
            events[-1] if events and isinstance(events[-1], dict) else {}
        )
        record = upsert_memory_by_source(
            conn,
            title=f"Session handoff {session_id}",
            content="\n".join(
                [
                    f"session_id: {session_id}",
                    f"cwd: {row.get('cwd')}",
                    f"started_at: {row.get('started_at')}",
                    f"last_event_at: {row.get('last_event_at')}",
                    f"event_count: {row.get('event_count')}",
                    f"last_reason: {row.get('last_reason')}",
                    f"plan_ids: {', '.join(str(item) for item in row.get('plan_ids', []))}",
                    f"last_branch: {last_event.get('branch')}",
                    f"last_plan_status: {last_event.get('plan_status')}",
                ]
            ),
            summary=(
                f"session={session_id}; events={row.get('event_count')}; last_reason={row.get('last_reason')}"
            ),
            kind="summary",
            scope="session",
            namespace=session_id,
            tags=["session", str(row.get("last_reason") or "unknown")],
            links=[str(DEFAULT_SESSION_INDEX_PATH)],
            source_type="session",
            source_ref=f"session:{session_id}",
            confidence=78,
            session_id=session_id,
            cwd=str(row.get("cwd") or cwd),
        )
        promoted.append(record.to_payload())
    return promoted


def promote_workflows(conn, *, cwd: Path, limit: int) -> list[dict[str, Any]]:
    payload = load_json_file(DEFAULT_WORKFLOW_STATE_PATH)
    runs: list[dict[str, Any]] = []
    raw_active = payload.get("active")
    active: dict[str, Any] = raw_active if isinstance(raw_active, dict) else {}
    if active:
        runs.append(active)
    history: list[dict[str, Any]] = (
        [item for item in payload.get("history", []) if isinstance(item, dict)]
        if isinstance(payload.get("history"), list)
        else []
    )
    runs.extend(item for item in history if isinstance(item, dict))
    promoted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in limit_rows(runs, limit):
        run_id = str(row.get("run_id") or "")
        if not run_id or run_id in seen:
            continue
        seen.add(run_id)
        status = str(row.get("status") or "unknown")
        record = upsert_memory_by_source(
            conn,
            title=f"Workflow {status} {run_id}",
            content="\n".join(
                [
                    f"run_id: {run_id}",
                    f"name: {row.get('name')}",
                    f"path: {row.get('path')}",
                    f"status: {status}",
                    f"execution_mode: {row.get('execution_mode')}",
                    f"step_count: {row.get('step_count')}",
                    f"completed_steps: {row.get('completed_steps')}",
                    f"failed_step_id: {row.get('failed_step_id')}",
                    f"resumed_from: {row.get('resumed_from')}",
                    f"finished_at: {row.get('finished_at')}",
                ]
            ),
            summary=(
                f"run={run_id}; status={status}; workflow={row.get('name')}; failed_step={row.get('failed_step_id')}"
            ),
            kind="blocker" if status == "failed" else "artifact",
            scope="repo",
            namespace=infer_namespace(cwd, "repo"),
            tags=["workflow", status],
            links=[str(DEFAULT_WORKFLOW_STATE_PATH), str(row.get("path") or "")],
            source_type="workflow",
            source_ref=f"workflow:{run_id}",
            confidence=90 if status in {"passed", "completed"} else 82,
            session_id=None,
            cwd=str(cwd),
        )
        promoted.append(record.to_payload())
    return promoted


def promote_claims(conn, *, cwd: Path, limit: int) -> list[dict[str, Any]]:
    payload = load_json_file(DEFAULT_CLAIMS_PATH)
    raw_claims = payload.get("claims")
    claims: dict[str, Any] = raw_claims if isinstance(raw_claims, dict) else {}
    promoted: list[dict[str, Any]] = []
    for row in limit_rows(list(claims.values()), limit):
        issue_id = str(row.get("issue_id") or "")
        if not issue_id:
            continue
        status = str(row.get("status") or "unknown")
        record = upsert_memory_by_source(
            conn,
            title=f"Claim {status} {issue_id}",
            content="\n".join(
                [
                    f"issue_id: {issue_id}",
                    f"owner: {row.get('owner')}",
                    f"status: {status}",
                    f"claimed_at: {row.get('claimed_at')}",
                    f"updated_at: {row.get('updated_at')}",
                    f"handoff_to: {row.get('handoff_to')}",
                ]
            ),
            summary=f"issue={issue_id}; status={status}; owner={row.get('owner')}",
            kind="blocker" if status in {"blocked", "handoff-pending"} else "artifact",
            scope="repo",
            namespace=infer_namespace(cwd, "repo"),
            tags=["claims", status],
            links=[str(DEFAULT_CLAIMS_PATH)],
            source_type="claims",
            source_ref=f"claims:{issue_id}",
            confidence=76,
            session_id=None,
            cwd=str(cwd),
        )
        promoted.append(record.to_payload())
    return promoted


def promote_doctor(conn, *, cwd: Path, limit: int) -> list[dict[str, Any]]:
    payload = load_doctor_report()
    if not payload:
        return []
    raw_checks = payload.get("checks")
    checks: list[dict[str, Any]] = (
        [item for item in raw_checks if isinstance(item, dict)]
        if isinstance(raw_checks, list)
        else []
    )
    failing_checks = [
        item for item in checks if isinstance(item, dict) and not bool(item.get("ok"))
    ]
    raw_warning_lines = payload.get("warnings")
    warning_lines: list[str] = (
        [str(item) for item in raw_warning_lines if str(item).strip()]
        if isinstance(raw_warning_lines, list)
        else []
    )
    items: list[dict[str, Any]] = []
    for check in limit_rows(failing_checks, limit):
        name = str(check.get("name") or "unknown")
        raw_report = check.get("report")
        report: dict[str, Any] = raw_report if isinstance(raw_report, dict) else {}
        content_lines = [
            f"check: {name}",
            f"kind: {check.get('kind')}",
            f"exit_code: {check.get('exit_code')}",
            f"report_result: {check.get('report_result')}",
            f"stderr: {check.get('stderr')}",
            f"stdout: {check.get('stdout')}",
        ]
        raw_report_warnings = report.get("warnings")
        report_warnings: list[str] = (
            [str(item) for item in raw_report_warnings if str(item).strip()]
            if isinstance(raw_report_warnings, list)
            else []
        )
        for warning in report_warnings:
            content_lines.append(f"report_warning: {warning}")
        record = upsert_memory_by_source(
            conn,
            title=f"Doctor finding {name}",
            content="\n".join(content_lines),
            summary=f"doctor check={name}; report_result={check.get('report_result')}; exit={check.get('exit_code')}",
            kind="validation",
            scope="repo",
            namespace=infer_namespace(cwd, "repo"),
            tags=["doctor", name, "failing-check"],
            links=[str(DEFAULT_DOCTOR_REPORT_PATH)],
            source_type="doctor",
            source_ref=f"doctor:check:{name}",
            confidence=92,
            session_id=None,
            cwd=str(cwd),
        )
        items.append(record.to_payload())
    for warning in warning_lines[: max(0, limit - len(items))]:
        text = str(warning).strip()
        if not text:
            continue
        record = upsert_memory_by_source(
            conn,
            title="Doctor warning summary",
            content=text,
            summary=text,
            kind="validation",
            scope="repo",
            namespace=infer_namespace(cwd, "repo"),
            tags=["doctor", "warning"],
            links=[str(DEFAULT_DOCTOR_REPORT_PATH)],
            source_type="doctor",
            source_ref=f"doctor:warning:{text}",
            confidence=80,
            session_id=None,
            cwd=str(cwd),
        )
        items.append(record.to_payload())
    return items


def cmd_promote(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [arg for arg in argv if arg != "--json"]
    try:
        source = str(parse_flag_value(argv, "--source") or "all").strip().lower()
        limit = parse_limit(argv, default=5)
    except (TypeError, ValueError):
        return usage()
    if argv or source not in PROMOTION_SOURCES:
        return usage()
    cwd = Path.cwd()
    conn = connect()
    promoted: list[dict[str, Any]] = []
    selected = (
        {source}
        if source != "all"
        else {"digest", "session", "workflow", "claims", "doctor"}
    )
    if "digest" in selected:
        promoted.extend(promote_digest(conn, cwd=cwd))
    if "session" in selected:
        promoted.extend(promote_sessions(conn, cwd=cwd, limit=limit))
    if "workflow" in selected:
        promoted.extend(promote_workflows(conn, cwd=cwd, limit=limit))
    if "claims" in selected:
        promoted.extend(promote_claims(conn, cwd=cwd, limit=limit))
    if "doctor" in selected:
        promoted.extend(promote_doctor(conn, cwd=cwd, limit=limit))
    relationships_updated = derive_relationship_links(conn)
    refreshed_records = active_memory_records(conn)
    refreshed_by_id = {record.memory_id: record for record in refreshed_records}
    promoted = [
        refreshed_by_id.get(str(item.get("id") or ""), item).to_payload()
        if hasattr(refreshed_by_id.get(str(item.get("id") or ""), item), "to_payload")
        else item
        for item in promoted
    ]
    return emit(
        {
            "result": "PASS",
            "command": "promote",
            "source": source,
            "count": len(promoted),
            "relationships_updated": relationships_updated,
            "memories": promoted,
        },
        as_json,
    )


def cmd_doctor(argv: list[str]) -> int:
    as_json = "--json" in argv
    args = [arg for arg in argv if arg != "--json"]
    if args:
        return usage()
    conn = connect()
    report = doctor_report(conn)
    return emit({"command": "doctor", **report}, as_json)


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"help", "--help", "-h"}:
        return usage()
    command = argv[0]
    args = argv[1:]
    if command == "add":
        return cmd_add(args)
    if command == "find":
        return cmd_find(args)
    if command == "recall":
        return cmd_recall(args)
    if command == "pin":
        return cmd_pin(args)
    if command == "summarize":
        return cmd_summarize(args)
    if command == "promote":
        return cmd_promote(args)
    if command == "doctor":
        return cmd_doctor(args)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
