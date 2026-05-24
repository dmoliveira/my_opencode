#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from runtime_audit import DEFAULT_AUDIT_PATH, append_event, load_audit  # type: ignore


def usage() -> int:
    print(
        "usage: /audit status [--json] | /audit list [--limit <n>] [--json] | /audit report [--days <n>] [--bucket day|week|month] [--json] | /audit export --path <file> [--json] | /audit doctor [--json]"
    )
    return 2


def emit(payload: dict, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        if payload.get("result") != "PASS":
            print(f"error: {payload.get('error', 'audit command failed')}")
            return 1
        print(f"result: {payload.get('result')}")
        if payload.get("count") is not None:
            print(f"count: {payload.get('count')}")
    return 0 if payload.get("result") == "PASS" else 1


def parse_flag_value(argv: list[str], flag: str) -> str | None:
    if flag not in argv:
        return None
    idx = argv.index(flag)
    if idx + 1 >= len(argv):
        raise ValueError(f"{flag} requires value")
    value = argv[idx + 1]
    del argv[idx : idx + 2]
    return value


def bucket_key_for(dt: datetime, bucket: str) -> str:
    if bucket == "day":
        return dt.strftime("%Y-%m-%d")
    if bucket == "week":
        iso_year, iso_week, _ = dt.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if bucket == "month":
        return dt.strftime("%Y-%m")
    raise ValueError(f"unsupported bucket: {bucket}")


def report_now() -> datetime:
    configured = os.environ.get("MY_OPENCODE_AUDIT_NOW", "").strip()
    if configured:
        return datetime.fromisoformat(configured.replace("Z", "+00:00"))
    return datetime.now(UTC)


def cmd_status(argv: list[str]) -> int:
    as_json = "--json" in argv
    state = load_audit(DEFAULT_AUDIT_PATH)
    raw_events = state.get("events")
    events = raw_events if isinstance(raw_events, list) else []
    latest = events[0] if events and isinstance(events[0], dict) else {}
    return emit(
        {
            "result": "PASS",
            "command": "status",
            "path": str(DEFAULT_AUDIT_PATH),
            "count": len(events),
            "latest": latest,
        },
        as_json,
    )


def cmd_list(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    limit = 20
    if "--limit" in argv:
        idx = argv.index("--limit")
        if idx + 1 >= len(argv):
            return usage()
        try:
            limit = max(1, int(argv[idx + 1]))
        except ValueError:
            return usage()
    state = load_audit(DEFAULT_AUDIT_PATH)
    raw_events = state.get("events")
    events = raw_events if isinstance(raw_events, list) else []
    return emit(
        {
            "result": "PASS",
            "command": "list",
            "count": min(limit, len(events)),
            "events": events[:limit],
        },
        as_json,
    )


def cmd_export(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    try:
        target = parse_flag_value(argv, "--path")
    except ValueError:
        return usage()
    if not target:
        return usage()
    path = Path(target).expanduser()
    state = load_audit(DEFAULT_AUDIT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    append_event("audit", "export", "PASS", {"path": str(path)})
    return emit(
        {
            "result": "PASS",
            "command": "export",
            "path": str(path),
            "count": len(state.get("events", [])),
        },
        as_json,
    )


def cmd_report(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    days = 7
    bucket = "day"
    if "--days" in argv:
        idx = argv.index("--days")
        if idx + 1 >= len(argv):
            return usage()
        try:
            days = max(1, int(argv[idx + 1]))
        except ValueError:
            return usage()
    if "--bucket" in argv:
        idx = argv.index("--bucket")
        if idx + 1 >= len(argv):
            return usage()
        bucket = str(argv[idx + 1]).strip().lower()
        if bucket not in {"day", "week", "month"}:
            return usage()

    state = load_audit(DEFAULT_AUDIT_PATH)
    raw_events = state.get("events")
    events = raw_events if isinstance(raw_events, list) else []
    horizon_cutoff = report_now() - timedelta(days=days)

    within_horizon: list[dict] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        raw_at = str(event.get("at") or "")
        try:
            event_at = datetime.fromisoformat(raw_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if event_at >= horizon_cutoff:
            within_horizon.append(event)

    by_command: dict[str, int] = {}
    by_action: dict[str, int] = {}
    by_result: dict[str, int] = {}
    by_bucket: dict[str, dict[str, int]] = {}
    failures: list[dict] = []
    for event in within_horizon:
        command = str(event.get("command") or "unknown")
        action = str(event.get("action") or "unknown")
        result = str(event.get("result") or "UNKNOWN")
        raw_at = str(event.get("at") or "")
        try:
            event_at = datetime.fromisoformat(raw_at.replace("Z", "+00:00"))
        except ValueError:
            event_at = None
        by_command[command] = by_command.get(command, 0) + 1
        by_action[action] = by_action.get(action, 0) + 1
        by_result[result] = by_result.get(result, 0) + 1
        if event_at is not None:
            bucket_key = bucket_key_for(event_at, bucket)
            bucket_counts = by_bucket.setdefault(bucket_key, {})
            bucket_counts[result] = bucket_counts.get(result, 0) + 1
        if result not in {"PASS", "WARN"}:
            failures.append(event)

    bucket_series = [
        {
            "bucket": bucket_key,
            "total": sum(counts.values()),
            "by_result": counts,
        }
        for bucket_key, counts in sorted(by_bucket.items())
    ]

    report = {
        "result": "PASS",
        "command": "report",
        "days": days,
        "bucket": bucket,
        "total_events": len(events),
        "events_in_window": len(within_horizon),
        "by_command": by_command,
        "by_action": by_action,
        "by_result": by_result,
        "bucket_series": bucket_series,
        "failure_count": len(failures),
        "recent_failures": failures[:10],
    }
    return emit(report, as_json)


def cmd_doctor(argv: list[str]) -> int:
    as_json = "--json" in argv
    state = load_audit(DEFAULT_AUDIT_PATH)
    raw_events = state.get("events")
    events = raw_events if isinstance(raw_events, list) else []
    warnings: list[str] = []
    if not events:
        warnings.append("audit log is empty; run mutating commands to populate it")
    return emit(
        {
            "result": "PASS",
            "command": "doctor",
            "path": str(DEFAULT_AUDIT_PATH),
            "count": len(events),
            "warnings": warnings,
            "quick_fixes": [
                "/claims claim issue-1 --by human:alex --json",
                "/audit list --json",
                "/audit report --days 7 --json",
            ],
        },
        as_json,
    )


def main(argv: list[str]) -> int:
    if not argv:
        return usage()
    command = argv[0]
    rest = argv[1:]
    if command in {"help", "-h", "--help"}:
        return usage()
    if command == "status":
        return cmd_status(rest)
    if command == "list":
        return cmd_list(rest)
    if command == "report":
        return cmd_report(rest)
    if command == "export":
        return cmd_export(rest)
    if command == "doctor":
        return cmd_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
