#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
START_WORK_SCRIPT = SCRIPT_DIR / "start_work_command.py"
REQUIRED_CONTRACT_HEADINGS = (
    "## objective",
    "## scope",
    "## acceptance criteria",
    "## stop conditions",
)


def usage() -> int:
    print(
        "usage: /plan run <plan.md> [--deviation <note> ...] [--background] [--json] | "
        "/plan status [--json] | /plan doctor [--json]"
    )
    return 2


def _run_start_work(args: list[str]) -> int:
    completed = subprocess.run(
        [sys.executable, str(START_WORK_SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    return completed.returncode


def _contract_missing_sections(plan_path: Path) -> list[str]:
    text = plan_path.read_text(encoding="utf-8", errors="replace")
    lowered = text.lower()
    missing: list[str] = []
    for heading in REQUIRED_CONTRACT_HEADINGS:
        if heading not in lowered:
            missing.append(heading.replace("## ", ""))
    return missing


def command_run(args: list[str]) -> int:
    json_output = "--json" in args
    if not args or args[0].startswith("--"):
        return usage()
    plan_path = Path(args[0]).expanduser().resolve()
    if not plan_path.exists():
        report = {
            "result": "FAIL",
            "reason_code": "plan_not_found",
            "plan": str(plan_path),
        }
        print(json.dumps(report, indent=2) if json_output else "plan not found")
        return 1
    missing_sections = _contract_missing_sections(plan_path)
    if missing_sections:
        report = {
            "result": "FAIL",
            "reason_code": "plan_contract_missing_sections",
            "plan": str(plan_path),
            "missing_sections": missing_sections,
            "required_sections": [
                heading.replace("## ", "") for heading in REQUIRED_CONTRACT_HEADINGS
            ],
        }
        print(
            json.dumps(report, indent=2)
            if json_output
            else "plan contract missing required sections"
        )
        return 1
    return _run_start_work(args)


def command_status(args: list[str]) -> int:
    return _run_start_work(["status", *args])


def command_doctor(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    json_output = "--json" in args
    report = {
        "result": "PASS" if START_WORK_SCRIPT.exists() else "FAIL",
        "backend_exists": START_WORK_SCRIPT.exists(),
        "required_contract_sections": [
            heading.replace("## ", "") for heading in REQUIRED_CONTRACT_HEADINGS
        ],
    }
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"result: {report['result']}")
        print(f"backend_exists: {report['backend_exists']}")
    return 0 if report["result"] == "PASS" else 1


def main(argv: list[str]) -> int:
    if not START_WORK_SCRIPT.exists():
        print("plan: backend unavailable (missing start_work_command.py)")
        return 1

    if not argv or argv[0] in {"help", "-h", "--help"}:
        return usage()

    command = argv[0]
    rest = argv[1:]
    if command == "run":
        return command_run(rest)
    if command == "status":
        return command_status(rest)
    if command == "doctor":
        return command_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
