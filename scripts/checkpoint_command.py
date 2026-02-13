#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from checkpoint_snapshot_manager import (  # type: ignore
    list_snapshots,
    prune_snapshots,
    show_snapshot,
)
from config_layering import resolve_write_path  # type: ignore


def usage() -> int:
    print(
        "usage: /checkpoint list [--run-id <id>] [--json] | "
        "/checkpoint show [--run-id <id>] [--snapshot <id|latest>] [--json] | "
        "/checkpoint prune [--max-per-run <n>] [--max-age-days <n>] [--compress-after-hours <n>] [--json] | "
        "/checkpoint doctor [--json]"
    )
    return 2


def command_list(args: list[str]) -> int:
    json_output = "--json" in args
    run_id: str | None = None

    index = 0
    while index < len(args):
        token = args[index]
        if token == "--json":
            index += 1
            continue
        if token == "--run-id":
            if index + 1 >= len(args):
                return usage()
            run_id = args[index + 1].strip()
            index += 2
            continue
        return usage()

    write_path = resolve_write_path()
    snapshots = list_snapshots(write_path, run_id=run_id)
    report = {
        "result": "PASS",
        "count": len(snapshots),
        "snapshots": snapshots,
        "config": str(write_path),
    }
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"count: {report['count']}")
        for item in snapshots[:20]:
            sid = str(item.get("snapshot_id") or "")
            rid = str(item.get("run_id") or "")
            status = str(item.get("status") or "")
            created = str(item.get("created_at") or "")
            print(f"- {sid} run={rid} status={status} at={created}")
    return 0


def command_show(args: list[str]) -> int:
    json_output = "--json" in args
    run_id = ""
    snapshot_id = "latest"

    index = 0
    while index < len(args):
        token = args[index]
        if token == "--json":
            index += 1
            continue
        if token == "--run-id":
            if index + 1 >= len(args):
                return usage()
            run_id = args[index + 1].strip()
            index += 2
            continue
        if token == "--snapshot":
            if index + 1 >= len(args):
                return usage()
            snapshot_id = args[index + 1].strip()
            index += 2
            continue
        return usage()

    write_path = resolve_write_path()
    if not run_id:
        snapshots = list_snapshots(write_path)
        if not snapshots:
            report = {
                "result": "FAIL",
                "reason_code": "resume_missing_checkpoint",
                "snapshot": None,
                "config": str(write_path),
            }
            print(json.dumps(report, indent=2) if json_output else "no snapshots found")
            return 1
        run_id = str(snapshots[0].get("run_id") or "")

    report = show_snapshot(write_path, run_id, snapshot_id)
    report["config"] = str(write_path)
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"result: {report.get('result')}")
        print(f"reason_code: {report.get('reason_code')}")
        if report.get("result") == "PASS":
            snapshot = report.get("snapshot", {})
            if isinstance(snapshot, dict):
                print(f"snapshot_id: {snapshot.get('snapshot_id')}")
                print(f"run_id: {snapshot.get('run_id')}")
                print(f"status: {snapshot.get('status')}")
    return 0 if report.get("result") == "PASS" else 1


def command_prune(args: list[str]) -> int:
    json_output = "--json" in args
    max_per_run = 50
    max_age_days = 14
    compress_after_hours = 24

    index = 0
    while index < len(args):
        token = args[index]
        if token == "--json":
            index += 1
            continue
        if token == "--max-per-run":
            if index + 1 >= len(args):
                return usage()
            max_per_run = int(args[index + 1])
            index += 2
            continue
        if token == "--max-age-days":
            if index + 1 >= len(args):
                return usage()
            max_age_days = int(args[index + 1])
            index += 2
            continue
        if token == "--compress-after-hours":
            if index + 1 >= len(args):
                return usage()
            compress_after_hours = int(args[index + 1])
            index += 2
            continue
        return usage()

    write_path = resolve_write_path()
    report = prune_snapshots(
        write_path,
        max_per_run=max_per_run,
        max_age_days=max_age_days,
        compress_after_hours=compress_after_hours,
    )
    report["config"] = str(write_path)
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"result: {report.get('result')}")
        print(f"removed: {report.get('removed', 0)}")
        print(f"compressed: {report.get('compressed', 0)}")
    return 0 if report.get("result") == "PASS" else 1


def command_doctor(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    json_output = "--json" in args
    write_path = resolve_write_path()
    snapshots = list_snapshots(write_path)
    warnings: list[str] = []
    problems: list[str] = []
    if not snapshots:
        warnings.append("no checkpoint snapshots found yet")
    else:
        latest = snapshots[0]
        run_id = str(latest.get("run_id") or "")
        latest_report = show_snapshot(write_path, run_id, "latest")
        if latest_report.get("result") != "PASS":
            problems.append(
                f"latest checkpoint unreadable: {latest_report.get('reason_code')}"
            )

    report = {
        "result": "PASS" if not problems else "FAIL",
        "snapshot_count": len(snapshots),
        "warnings": warnings,
        "problems": problems,
        "quick_fixes": [
            "/checkpoint list --json",
            "/checkpoint prune --max-per-run 50 --max-age-days 14 --json",
        ],
        "config": str(write_path),
    }
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"result: {report['result']}")
        print(f"snapshot_count: {report['snapshot_count']}")
        for item in warnings:
            print(f"- warning: {item}")
        for item in problems:
            print(f"- problem: {item}")
    return 0 if report["result"] == "PASS" else 1


def main(argv: list[str]) -> int:
    if not argv:
        return usage()
    command = argv[0]
    rest = argv[1:]
    if command in ("help", "--help", "-h"):
        return usage()
    if command == "list":
        return command_list(rest)
    if command == "show":
        return command_show(rest)
    if command == "prune":
        return command_prune(rest)
    if command == "doctor":
        return command_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
