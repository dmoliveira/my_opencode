#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config_layering import load_layered_config, resolve_write_path  # type: ignore
from health_score_collector import (  # type: ignore
    drift_report,
    load_health_history,
    load_latest_health_snapshot,
    run_health_collection,
    score_bucket_recommendations,
)


def usage() -> int:
    print(
        "usage: /health [status|trend|drift|doctor] [--json] "
        "| /health status [--force-refresh] [--force-alert] [--json] "
        "| /health trend [--limit <n>] [--json]"
    )
    return 2


def pop_flag(args: list[str], flag: str) -> bool:
    if flag in args:
        args.remove(flag)
        return True
    return False


def pop_value(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag not in args:
        return default
    idx = args.index(flag)
    if idx + 1 >= len(args):
        raise ValueError(f"{flag} requires a value")
    value = args[idx + 1]
    del args[idx : idx + 2]
    return value


def emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def command_status(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    force_refresh = pop_flag(args, "--force-refresh")
    force_alert = pop_flag(args, "--force-alert")
    if args:
        return usage()

    config, _ = load_layered_config()
    write_path = resolve_write_path()
    if force_refresh:
        snapshot = run_health_collection(
            Path.cwd(),
            config,
            write_path,
            force_alert=force_alert,
        )
    else:
        snapshot = load_latest_health_snapshot(write_path)
        if not snapshot:
            snapshot = run_health_collection(
                Path.cwd(),
                config,
                write_path,
                force_alert=force_alert,
            )

    payload = {
        "result": "PASS",
        "score": snapshot.get("score"),
        "status": snapshot.get("status"),
        "reason_codes": snapshot.get("reason_codes", []),
        "next_actions": snapshot.get("next_actions", []),
        "suppression": snapshot.get("suppression", {}),
        "observed_at": snapshot.get("observed_at"),
        "paths": snapshot.get("paths", {}),
    }
    if not payload["next_actions"] and isinstance(payload.get("status"), str):
        payload["next_actions"] = score_bucket_recommendations(str(payload["status"]))
    emit(payload, as_json=as_json)
    return 0


def command_trend(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    try:
        raw_limit = pop_value(args, "--limit", "10") or "10"
    except ValueError:
        return usage()
    if args:
        return usage()
    try:
        limit = max(1, int(raw_limit))
    except ValueError:
        return usage()

    write_path = resolve_write_path()
    history = load_health_history(write_path, limit=limit)
    entries = []
    for item in history:
        entries.append(
            {
                "observed_at": item.get("observed_at"),
                "score": item.get("score"),
                "status": item.get("status"),
                "reason_codes": item.get("reason_codes", []),
            }
        )
    payload = {
        "result": "PASS",
        "count": len(entries),
        "entries": entries,
        "history_path": str(
            write_path.parent / "my_opencode" / "runtime" / "health_score_history.jsonl"
        ),
    }
    emit(payload, as_json=as_json)
    return 0


def command_drift(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    force_refresh = pop_flag(args, "--force-refresh")
    force_alert = pop_flag(args, "--force-alert")
    if args:
        return usage()

    config, _ = load_layered_config()
    write_path = resolve_write_path()
    if force_refresh:
        snapshot = run_health_collection(
            Path.cwd(),
            config,
            write_path,
            force_alert=force_alert,
        )
    else:
        snapshot = load_latest_health_snapshot(write_path)
        if not snapshot:
            snapshot = run_health_collection(
                Path.cwd(),
                config,
                write_path,
                force_alert=force_alert,
            )

    payload = drift_report(snapshot)
    payload["observed_at"] = snapshot.get("observed_at")
    payload["status"] = snapshot.get("status")
    payload["score"] = snapshot.get("score")
    emit(payload, as_json=as_json)
    return 0


def command_doctor(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    as_json = "--json" in args
    report = {
        "result": "PASS"
        if (SCRIPT_DIR / "health_score_collector.py").exists()
        else "FAIL",
        "collector_exists": (SCRIPT_DIR / "health_score_collector.py").exists(),
        "policy_exists": (
            SCRIPT_DIR.parent / "instructions" / "health_score_policy_contract.md"
        ).exists(),
        "warnings": []
        if (
            SCRIPT_DIR.parent / "instructions" / "health_score_policy_contract.md"
        ).exists()
        else ["missing instructions/health_score_policy_contract.md"],
        "problems": []
        if (SCRIPT_DIR / "health_score_collector.py").exists()
        else ["missing scripts/health_score_collector.py"],
        "quick_fixes": [
            "/health status --json",
            "/health trend --limit 10 --json",
            "/health drift --json",
        ],
    }
    emit(report, as_json=as_json)
    return 0 if report["result"] == "PASS" else 1


def main(argv: list[str]) -> int:
    if not argv:
        return command_status(["--json"])
    cmd, *rest = argv
    if cmd in {"help", "--help", "-h"}:
        return usage()
    if cmd == "status":
        return command_status(rest)
    if cmd == "trend":
        return command_trend(rest)
    if cmd == "drift":
        return command_drift(rest)
    if cmd == "doctor":
        return command_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
