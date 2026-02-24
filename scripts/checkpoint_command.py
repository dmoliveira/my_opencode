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
    restore_runtime_from_snapshot,
    runtime_run_id,
    show_snapshot,
    write_snapshot,
)
from config_layering import resolve_write_path  # type: ignore
from plan_execution_runtime import (  # type: ignore
    load_plan_execution_state,
    save_plan_execution_state,
)


def usage() -> int:
    print(
        "usage: /checkpoint create [--source <label>] [--json] | "
        "/checkpoint restore [--run-id <id>] [--snapshot <id|latest>] "
        "[--force] [--allow-run-id-mismatch] [--json] | "
        "/checkpoint list [--run-id <id>] [--json] | "
        "/checkpoint show [--run-id <id>] [--snapshot <id|latest>] [--json] | "
        "/checkpoint prune [--max-per-run <n>] [--max-age-days <n>] [--compress-after-hours <n>] [--json] | "
        "/checkpoint doctor [--json]"
    )
    return 2


def command_create(args: list[str]) -> int:
    json_output = "--json" in args
    source = "manual_checkpoint"

    index = 0
    while index < len(args):
        token = args[index]
        if token == "--json":
            index += 1
            continue
        if token == "--source":
            if index + 1 >= len(args):
                return usage()
            source = args[index + 1].strip() or source
            index += 2
            continue
        return usage()

    config: dict[str, object] = {}
    write_path = resolve_write_path()
    runtime, _ = load_plan_execution_state(config, write_path)
    if not isinstance(runtime, dict) or not runtime:
        report = {
            "result": "FAIL",
            "reason_code": "resume_missing_runtime_artifacts",
            "source": source,
            "config": str(write_path),
            "quick_fixes": [
                "/autopilot go --goal 'start objective' --json",
                "/checkpoint list --json",
            ],
        }
        print(
            json.dumps(report, indent=2)
            if json_output
            else "no runtime state to checkpoint"
        )
        return 1

    report = write_snapshot(write_path, runtime, source=source)
    report["config"] = str(write_path)
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"result: {report.get('result')}")
        print(f"reason_code: {report.get('reason_code')}")
        snapshot = report.get("snapshot")
        if isinstance(snapshot, dict):
            print(f"snapshot_id: {snapshot.get('snapshot_id')}")
            print(f"run_id: {snapshot.get('run_id')}")
    return 0 if report.get("result") == "PASS" else 1


def command_restore(args: list[str]) -> int:
    json_output = "--json" in args
    run_id = ""
    snapshot_id = "latest"
    force = "--force" in args
    allow_run_id_mismatch = "--allow-run-id-mismatch" in args

    index = 0
    while index < len(args):
        token = args[index]
        if token in {"--json", "--force", "--allow-run-id-mismatch"}:
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

    config: dict[str, object] = {}
    write_path = resolve_write_path()
    current_runtime, _ = load_plan_execution_state(config, write_path)

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

    snapshot_report = show_snapshot(write_path, run_id, snapshot_id)
    if snapshot_report.get("result") != "PASS":
        snapshot_report["config"] = str(write_path)
        print(
            json.dumps(snapshot_report, indent=2)
            if json_output
            else str(snapshot_report.get("reason_code") or "checkpoint restore failed")
        )
        return 1

    snapshot = snapshot_report.get("snapshot")
    if not isinstance(snapshot, dict):
        report = {
            "result": "FAIL",
            "reason_code": "checkpoint_schema_invalid",
            "config": str(write_path),
        }
        print(
            json.dumps(report, indent=2) if json_output else "checkpoint schema invalid"
        )
        return 1

    runtime_state = restore_runtime_from_snapshot(snapshot)
    if runtime_state is None:
        report = {
            "result": "FAIL",
            "reason_code": "checkpoint_restore_state_missing",
            "config": str(write_path),
            "run_id": run_id,
            "snapshot_id": snapshot.get("snapshot_id"),
        }
        print(
            json.dumps(report, indent=2)
            if json_output
            else "checkpoint missing runtime state"
        )
        return 1

    current_run_id = (
        runtime_run_id(current_runtime)
        if isinstance(current_runtime, dict) and current_runtime
        else ""
    )
    snapshot_run_id = str(snapshot.get("run_id") or "")
    if (
        current_run_id
        and snapshot_run_id
        and current_run_id != snapshot_run_id
        and not allow_run_id_mismatch
    ):
        report = {
            "result": "FAIL",
            "reason_code": "checkpoint_restore_run_id_mismatch",
            "current_run_id": current_run_id,
            "snapshot_run_id": snapshot_run_id,
            "config": str(write_path),
            "quick_fixes": ["re-run with --allow-run-id-mismatch --force"],
        }
        print(
            json.dumps(report, indent=2)
            if json_output
            else "restore blocked by run_id mismatch"
        )
        return 1

    if isinstance(current_runtime, dict) and current_runtime and not force:
        report = {
            "result": "FAIL",
            "reason_code": "checkpoint_restore_force_required",
            "config": str(write_path),
            "current_run_id": current_run_id or None,
            "snapshot_run_id": snapshot_run_id or None,
            "quick_fixes": ["re-run restore with --force"],
        }
        print(
            json.dumps(report, indent=2) if json_output else "restore requires --force"
        )
        return 1

    runtime_path = save_plan_execution_state(config, write_path, runtime_state)
    report = {
        "result": "PASS",
        "reason_code": "checkpoint_restored",
        "run_id": snapshot_run_id,
        "snapshot_id": snapshot.get("snapshot_id"),
        "runtime_path": str(runtime_path),
        "config": str(write_path),
    }
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"result: {report.get('result')}")
        print(f"reason_code: {report.get('reason_code')}")
        print(f"snapshot_id: {report.get('snapshot_id')}")
        print(f"run_id: {report.get('run_id')}")
    return 0


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
    if command == "create":
        return command_create(rest)
    if command == "restore":
        return command_restore(rest)
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
