#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
AUTOPILOT_SCRIPT = SCRIPT_DIR / "autopilot_command.py"
RESUME_SCRIPT = SCRIPT_DIR / "resume_command.py"
BENIGN_AUTOPILOT_REASON_CODES = {
    "autopilot_runtime_missing",
    "autopilot_not_running",
    "autopilot_already_stopped",
}


def usage() -> int:
    print("usage: /continuation-stop [--reason <text>] [--json]")
    return 2


def run_json_command(command: list[str]) -> tuple[int, dict]:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    payload: dict = {}
    try:
        payload = json.loads((completed.stdout or "").strip() or "{}")
    except json.JSONDecodeError:
        payload = {
            "result": "FAIL",
            "reason_code": "non_json_backend_response",
            "stdout": (completed.stdout or "").strip(),
            "stderr": (completed.stderr or "").strip(),
        }
    return completed.returncode, payload


def main(argv: list[str]) -> int:
    reason = "manual continuation stop"
    as_json = False
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--json":
            as_json = True
            index += 1
            continue
        if token == "--reason":
            if index + 1 >= len(argv):
                return usage()
            reason = argv[index + 1]
            index += 2
            continue
        if token in {"help", "-h", "--help"}:
            return usage()
        return usage()

    autopilot_code, autopilot_payload = run_json_command(
        [
            sys.executable,
            str(AUTOPILOT_SCRIPT),
            "stop",
            "--reason",
            reason,
            "--json",
        ]
    )
    resume_code, resume_payload = run_json_command(
        [sys.executable, str(RESUME_SCRIPT), "disable", "--json"]
    )

    problems: list[str] = []
    autopilot_reason_code = str(autopilot_payload.get("reason_code") or "")
    autopilot_ok = (
        autopilot_code == 0 and autopilot_payload.get("result") in {"PASS", "WARN"}
    ) or autopilot_reason_code in BENIGN_AUTOPILOT_REASON_CODES
    if not autopilot_ok:
        problems.append("autopilot stop did not complete successfully")
    if resume_code != 0 or resume_payload.get("result") not in {"PASS", "WARN"}:
        problems.append("resume disable did not complete successfully")

    report = {
        "result": "PASS" if not problems else "FAIL",
        "reason": reason,
        "actions": {
            "autopilot_stop": autopilot_payload,
            "resume_disable": resume_payload,
        },
        "problems": problems,
        "quick_fixes": [
            "/autopilot status --json",
            "/resume status --json",
            "/doctor run",
        ],
    }

    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print(f"result: {report['result']}")
        print(f"reason: {reason}")
        print(
            f"autopilot: {autopilot_payload.get('status', autopilot_payload.get('result', 'unknown'))}"
        )
        print(
            f"resume: {'disabled' if resume_payload.get('enabled') is False else 'updated'}"
        )
        if problems:
            print("problems:")
            for item in problems:
                print(f"- {item}")
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
