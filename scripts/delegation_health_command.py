#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_MINUTES = 60

POSITIVE_REASON_CODES = {
    "delegation_decision_recorded",
    "subagent_lifecycle_started",
    "subagent_timeline_recorded",
}

RISK_REASON_CODES = {
    "delegation_mutation_intent_blocked",
    "tool_surface_enforced_runtime",
    "delegation_fallback_applied",
    "delegation_failure_recorded",
    "delegation_route_overridden_low_confidence",
}


@dataclass
class Args:
    command: str
    minutes: int
    json_output: bool
    path: Path


def usage() -> int:
    print(
        "usage: /delegation-health status [--minutes <n>] [--json] [--path <jsonl>] | /delegation-health doctor [--json] [--path <jsonl>]"
    )
    return 2


def parse_int(value: str, fallback: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else fallback
    except ValueError:
        return fallback


def default_audit_path(cwd: Path) -> Path:
    env_path = (os.environ.get("MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH") or "").strip()
    if env_path:
        return Path(env_path).expanduser()
    return cwd / ".opencode" / "gateway-events.jsonl"


def parse_args(argv: list[str], cwd: Path) -> Args | None:
    if not argv:
        return None
    command = argv[0].strip().lower()
    if command not in {"status", "doctor"}:
        return None
    minutes = DEFAULT_MINUTES
    json_output = False
    path = default_audit_path(cwd)
    idx = 1
    while idx < len(argv):
        arg = argv[idx]
        if arg == "--json":
            json_output = True
            idx += 1
            continue
        if arg == "--minutes":
            if idx + 1 >= len(argv):
                return None
            minutes = parse_int(argv[idx + 1], DEFAULT_MINUTES)
            idx += 2
            continue
        if arg == "--path":
            if idx + 1 >= len(argv):
                return None
            path = Path(argv[idx + 1]).expanduser()
            idx += 2
            continue
        return None
    return Args(command=command, minutes=minutes, json_output=json_output, path=path)


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.exists() or not path.is_file():
        return events
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def summarize(events: list[dict[str, Any]], minutes: int) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    in_window: list[dict[str, Any]] = []
    for event in events:
        ts = parse_timestamp(event.get("ts") or event.get("timestamp"))
        if ts is None or ts >= cutoff:
            in_window.append(event)

    reason_counts = Counter(str(event.get("reason_code") or "") for event in in_window)
    by_subagent: dict[str, Counter[str]] = defaultdict(Counter)
    by_trace: dict[str, Counter[str]] = defaultdict(Counter)
    for event in in_window:
        reason = str(event.get("reason_code") or "")
        if not reason:
            continue
        subagent = str(event.get("subagent_type") or "none")
        by_subagent[subagent][reason] += 1
        trace_id = str(event.get("trace_id") or "")
        if trace_id:
            by_trace[trace_id][reason] += 1

    subagent_rows: list[dict[str, Any]] = []
    for subagent, counts in sorted(by_subagent.items()):
        positive = sum(counts.get(code, 0) for code in POSITIVE_REASON_CODES)
        risks = sum(counts.get(code, 0) for code in RISK_REASON_CODES)
        subagent_rows.append(
            {
                "subagent": subagent,
                "events": sum(counts.values()),
                "positive": positive,
                "risks": risks,
                "reasons": dict(counts),
            }
        )

    top_reasons = [
        {"reason_code": reason, "count": count}
        for reason, count in reason_counts.most_common(20)
        if reason
    ]

    return {
        "window_minutes": minutes,
        "events_total": len(events),
        "events_in_window": len(in_window),
        "traces_in_window": len(by_trace),
        "top_reasons": top_reasons,
        "subagents": subagent_rows,
        "risk_reason_codes": sorted(RISK_REASON_CODES),
    }


def command_status(args: Args) -> int:
    events = load_events(args.path)
    summary = summarize(events, args.minutes)
    warnings: list[str] = []
    if not args.path.exists():
        warnings.append("delegation audit path does not exist")
    if summary["events_in_window"] == 0:
        warnings.append("no delegation events found in selected window")
    result = "WARN" if warnings else "PASS"
    payload = {
        "result": result,
        "path": str(args.path),
        "exists": args.path.exists(),
        "warnings": warnings,
        "summary": summary,
        "quick_fixes": [
            "set MY_OPENCODE_GATEWAY_EVENT_AUDIT=1 and rerun your workflow",
            "rerun /delegation-health status --minutes 120 --json after delegated runs",
        ],
    }
    if args.json_output:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"result: {payload['result']}")
    print(f"path: {payload['path']}")
    print(f"exists: {'yes' if payload['exists'] else 'no'}")
    summary = payload["summary"]
    print(f"events_total: {summary['events_total']}")
    print(f"events_in_window: {summary['events_in_window']}")
    print(f"window_minutes: {summary['window_minutes']}")
    if warnings:
        print("warnings:")
        for item in warnings:
            print(f"- {item}")
    print("top_reasons:")
    for item in summary["top_reasons"][:8]:
        print(f"- {item['reason_code']}: {item['count']}")
    print("subagents:")
    for row in summary["subagents"]:
        if row["subagent"] == "none":
            continue
        print(
            f"- {row['subagent']}: events={row['events']} positive={row['positive']} risks={row['risks']}"
        )
    return 0


def command_doctor(args: Args) -> int:
    events = load_events(args.path)
    summary = summarize(events, args.minutes)
    problems: list[str] = []
    warnings: list[str] = []

    if not args.path.exists():
        warnings.append("delegation audit path does not exist")
    if summary["events_in_window"] == 0:
        warnings.append("no delegation events found in selected window")

    risk_counts = Counter()
    for item in summary["subagents"]:
        for reason, count in item["reasons"].items():
            if reason in RISK_REASON_CODES:
                risk_counts[reason] += count

    if risk_counts.get("delegation_mutation_intent_blocked", 0) > 0:
        warnings.append("detected read-only mutation blocks in selected window")
    if risk_counts.get("tool_surface_enforced_runtime", 0) > 0:
        warnings.append("detected denied-tool enforcement events in selected window")
    if risk_counts.get("delegation_fallback_applied", 0) > 3:
        problems.append("high fallback frequency suggests unstable delegation routing")

    result = "FAIL" if problems else ("WARN" if warnings else "PASS")
    payload = {
        "result": result,
        "path": str(args.path),
        "window_minutes": args.minutes,
        "problems": problems,
        "warnings": warnings,
        "summary": summary,
        "quick_fixes": [
            "set MY_OPENCODE_GATEWAY_EVENT_AUDIT=1 and rerun delegated tasks",
            "check /gateway doctor --json for process-pressure or guard anomalies",
            "rerun /delegation-health doctor --minutes 120 --json",
        ],
    }
    if args.json_output:
        print(json.dumps(payload, indent=2))
    else:
        print(f"result: {result}")
        print(f"path: {args.path}")
        print(f"window_minutes: {args.minutes}")
        print(f"problems: {len(problems)}")
        print(f"warnings: {len(warnings)}")
        for item in problems:
            print(f"- problem: {item}")
        for item in warnings:
            print(f"- warning: {item}")
    return 0 if result != "FAIL" else 1


def main(argv: list[str]) -> int:
    args = parse_args(argv, Path.cwd())
    if args is None:
        return usage()
    if args.command == "status":
        return command_status(args)
    if args.command == "doctor":
        return command_doctor(args)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
