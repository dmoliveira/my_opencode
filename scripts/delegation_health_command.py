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
    "agent_runtime_model_observed",
}

RISK_REASON_CODES = {
    "delegation_mutation_intent_blocked",
    "tool_surface_enforced_runtime",
    "delegation_fallback_applied",
    "delegation_failure_recorded",
    "delegation_route_overridden_low_confidence",
    "agent_model_routing_drift_detected",
    "provider_header_timeout_observed",
    "session_recovery_model_downgrade_applied",
}

TIMEOUT_REASON_CODES = {
    "provider_header_timeout_observed",
    "provider_retry_backoff_delay_hint",
    "provider_retry_backoff_generic_hint",
    "session_recovery_model_downgrade_applied",
}

DRIFT_REASON_CODES = {
    "agent_model_routing_drift_detected",
}


@dataclass
class Args:
    command: str
    minutes: int
    json_output: bool
    path: Path
    state_path: Path


def usage() -> int:
    print(
        "usage: /delegation-health status [--minutes <n>] [--json] [--path <jsonl>] [--state-path <json>] | /delegation-health doctor [--minutes <n>] [--json] [--path <jsonl>] [--state-path <json>]"
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


def default_runtime_state_path(cwd: Path) -> Path:
    return cwd / ".opencode" / "delegation-runtime-state.json"


def parse_args(argv: list[str], cwd: Path) -> Args | None:
    if not argv:
        return None
    command = argv[0].strip().lower()
    if command not in {"status", "doctor"}:
        return None
    minutes = DEFAULT_MINUTES
    json_output = False
    path = default_audit_path(cwd)
    state_path = default_runtime_state_path(cwd)
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
        if arg == "--state-path":
            if idx + 1 >= len(argv):
                return None
            state_path = Path(argv[idx + 1]).expanduser()
            idx += 2
            continue
        return None
    return Args(
        command=command,
        minutes=minutes,
        json_output=json_output,
        path=path,
        state_path=state_path,
    )


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


def load_runtime_state(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def runtime_epoch_ms(item: dict[str, Any], key: str) -> int:
    try:
        return int(item.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def summarize_runtime_state(
    state: dict[str, Any], minutes: int
) -> dict[str, Any]:
    cutoff_ms = int(
        (datetime.now(timezone.utc) - timedelta(minutes=minutes)).timestamp() * 1000
    )
    raw_timeline = state.get("timeline")
    timeline = [item for item in raw_timeline if isinstance(item, dict)] if isinstance(raw_timeline, list) else []
    timeline_in_window = [
        item for item in timeline if runtime_epoch_ms(item, "endedAt") >= cutoff_ms
    ]
    raw_proposals = state.get("policyProposals")
    proposals = [item for item in raw_proposals if isinstance(item, dict)] if isinstance(raw_proposals, list) else []
    proposals_in_window = [
        item
        for item in proposals
        if runtime_epoch_ms(item, "createdAt") >= cutoff_ms
    ]

    outcomes_by_subagent: dict[str, Counter[str]] = defaultdict(Counter)
    for item in timeline_in_window:
        subagent = str(item.get("subagentType") or "unknown")
        status = str(item.get("status") or "unknown")
        outcomes_by_subagent[subagent][status] += 1
    outcome_rows = []
    for subagent, counts in sorted(outcomes_by_subagent.items()):
        completed = counts.get("completed", 0)
        failed = counts.get("failed", 0)
        total = completed + failed
        outcome_rows.append(
            {
                "subagent": subagent,
                "total": total,
                "completed": completed,
                "failed": failed,
                "failure_rate": round(failed / total, 4) if total else 0.0,
            }
        )

    proposals_by_subagent: dict[str, Counter[str]] = defaultdict(Counter)
    for item in proposals_in_window:
        subagent = str(item.get("subagentType") or "unknown")
        mode = str(item.get("mode") or "unknown")
        proposals_by_subagent[subagent][mode] += 1
        if item.get("applied") is True:
            proposals_by_subagent[subagent]["applied"] += 1
    proposal_rows = [
        {
            "subagent": subagent,
            "shadow": counts.get("shadow", 0),
            "enforce": counts.get("enforce", 0),
            "applied": counts.get("applied", 0),
        }
        for subagent, counts in sorted(proposals_by_subagent.items())
    ]

    return {
        "path_format": "delegation-runtime-state-v1",
        "timeline_total": len(timeline),
        "timeline_in_window": len(timeline_in_window),
        "outcomes_by_subagent": outcome_rows,
        "policy_proposals_total": len(proposals),
        "policy_proposals_in_window": len(proposals_in_window),
        "policy_proposals_by_subagent": proposal_rows,
        "shadow_proposals_in_window": sum(
            1 for item in proposals_in_window if item.get("mode") == "shadow"
        ),
        "applied_proposals_in_window": sum(
            1 for item in proposals_in_window if item.get("applied") is True
        ),
    }


def resolve_actor(event: dict[str, Any]) -> str:
    for key in ("subagent_type", "agent"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "none"


def summarize(events: list[dict[str, Any]], minutes: int) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    in_window: list[dict[str, Any]] = []
    for event in events:
        ts = parse_timestamp(event.get("ts") or event.get("timestamp"))
        if ts is None or ts >= cutoff:
            in_window.append(event)

    reason_counts = Counter(str(event.get("reason_code") or "") for event in in_window)
    by_actor: dict[str, Counter[str]] = defaultdict(Counter)
    by_trace: dict[str, Counter[str]] = defaultdict(Counter)
    for event in in_window:
        reason = str(event.get("reason_code") or "")
        if not reason:
            continue
        actor = resolve_actor(event)
        by_actor[actor][reason] += 1
        trace_id = str(event.get("trace_id") or "")
        if trace_id:
            by_trace[trace_id][reason] += 1

    actor_rows: list[dict[str, Any]] = []
    for actor, counts in sorted(by_actor.items()):
        positive = sum(counts.get(code, 0) for code in POSITIVE_REASON_CODES)
        risks = sum(counts.get(code, 0) for code in RISK_REASON_CODES)
        timeout_events = sum(counts.get(code, 0) for code in TIMEOUT_REASON_CODES)
        drift_events = sum(counts.get(code, 0) for code in DRIFT_REASON_CODES)
        actor_rows.append(
            {
                "actor": actor,
                "events": sum(counts.values()),
                "positive": positive,
                "risks": risks,
                "timeouts": timeout_events,
                "drifts": drift_events,
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
        "actors": actor_rows,
        "subagents": actor_rows,
        "risk_reason_codes": sorted(RISK_REASON_CODES),
        "timeout_reason_codes": sorted(TIMEOUT_REASON_CODES),
        "drift_reason_codes": sorted(DRIFT_REASON_CODES),
    }


def command_status(args: Args) -> int:
    events = load_events(args.path)
    summary = summarize(events, args.minutes)
    runtime_state = summarize_runtime_state(
        load_runtime_state(args.state_path), args.minutes
    )
    warnings: list[str] = []
    runtime_samples = int(runtime_state["timeline_in_window"]) + int(
        runtime_state["policy_proposals_in_window"]
    )
    if summary["events_in_window"] == 0 and runtime_samples == 0:
        warnings.append("no delegation telemetry found in selected window")
    result = "WARN" if warnings else "PASS"
    payload = {
        "result": result,
        "path": str(args.path),
        "exists": args.path.exists(),
        "state_path": str(args.state_path),
        "state_exists": args.state_path.exists(),
        "telemetry_source": (
            "audit+state"
            if summary["events_in_window"] and runtime_samples
            else "audit"
            if summary["events_in_window"]
            else "state"
            if runtime_samples
            else "none"
        ),
        "warnings": warnings,
        "summary": summary,
        "runtime_state": runtime_state,
        "quick_fixes": [
            "rerun /delegation-health status --minutes 120 --json after delegated runs",
            "enable MY_OPENCODE_GATEWAY_EVENT_AUDIT=1 only when full event traces are needed",
        ],
    }
    if args.json_output:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"result: {payload['result']}")
    print(f"path: {payload['path']}")
    print(f"exists: {'yes' if payload['exists'] else 'no'}")
    print(f"state_path: {payload['state_path']}")
    print(f"telemetry_source: {payload['telemetry_source']}")
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
    print("actors:")
    for row in summary["actors"]:
        if row["actor"] == "none":
            continue
        print(
            f"- {row['actor']}: events={row['events']} positive={row['positive']} risks={row['risks']} timeouts={row['timeouts']} drifts={row['drifts']}"
        )
    return 0


def command_doctor(args: Args) -> int:
    events = load_events(args.path)
    summary = summarize(events, args.minutes)
    runtime_state = summarize_runtime_state(
        load_runtime_state(args.state_path), args.minutes
    )
    problems: list[str] = []
    warnings: list[str] = []

    runtime_samples = int(runtime_state["timeline_in_window"]) + int(
        runtime_state["policy_proposals_in_window"]
    )
    if summary["events_in_window"] == 0 and runtime_samples == 0:
        warnings.append("no delegation telemetry found in selected window")
    if int(runtime_state["shadow_proposals_in_window"]) > 0:
        warnings.append(
            "shadow policy proposals await deterministic evaluation before promotion"
        )
    if int(runtime_state["applied_proposals_in_window"]) > 0:
        warnings.append("enforced delegation policy proposals were applied in selected window")

    risk_counts = Counter()
    timeout_counts = Counter()
    drift_counts = Counter()
    for item in summary["actors"]:
        for reason, count in item["reasons"].items():
            if reason in RISK_REASON_CODES:
                risk_counts[reason] += count
            if reason in TIMEOUT_REASON_CODES:
                timeout_counts[reason] += count
            if reason in DRIFT_REASON_CODES:
                drift_counts[reason] += count

    if risk_counts.get("delegation_mutation_intent_blocked", 0) > 0:
        warnings.append("detected read-only mutation blocks in selected window")
    if risk_counts.get("tool_surface_enforced_runtime", 0) > 0:
        warnings.append("detected denied-tool enforcement events in selected window")
    if risk_counts.get("delegation_fallback_applied", 0) > 3:
        problems.append("high fallback frequency suggests unstable delegation routing")
    if timeout_counts.get("provider_header_timeout_observed", 0) > 0:
        warnings.append("provider header timeouts detected in selected window")
    if timeout_counts.get("session_recovery_model_downgrade_applied", 0) > 0:
        warnings.append("session recovery downgraded models after repeated provider header timeouts")
    if drift_counts.get("agent_model_routing_drift_detected", 0) > 0:
        warnings.append("runtime model drift detected between expected and observed agent model selection")

    result = "FAIL" if problems else ("WARN" if warnings else "PASS")
    payload = {
        "result": result,
        "path": str(args.path),
        "state_path": str(args.state_path),
        "window_minutes": args.minutes,
        "problems": problems,
        "warnings": warnings,
        "summary": summary,
        "runtime_state": runtime_state,
        "quick_fixes": [
            "review shadow proposals against deterministic scenario results before enforce promotion",
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
