#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
CLAIMS_SCRIPT = SCRIPT_DIR / "claims_command.py"
WORKFLOW_SCRIPT = SCRIPT_DIR / "workflow_command.py"

DEFAULT_STATE_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_DELIVERY_STATE_PATH",
        "~/.config/opencode/my_opencode/runtime/delivery_runs.json",
    )
).expanduser()


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def usage() -> int:
    print(
        "usage: /delivery start --issue <id> --workflow <file> [--role <role>|--by <owner>] [--execute] [--handoff-to <owner>] [--json] | "
        "/delivery status [--id <run_id>] [--json] | /delivery handoff --issue <id> --to <owner> [--json] | "
        "/delivery close --issue <id> [--json] | /delivery doctor [--json]"
    )
    return 2


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "runs": []}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {"version": 1, "runs": []}
    if not isinstance(raw.get("runs"), list):
        raw["runs"] = []
    return raw


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def parse_flag_value(argv: list[str], flag: str) -> str | None:
    if flag not in argv:
        return None
    idx = argv.index(flag)
    if idx + 1 >= len(argv):
        raise ValueError(f"{flag} requires value")
    value = argv[idx + 1]
    del argv[idx : idx + 2]
    return value


def run_json(command: list[str]) -> tuple[int, dict[str, Any]]:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    try:
        payload = json.loads((completed.stdout or "").strip() or "{}")
        if not isinstance(payload, dict):
            payload = {}
    except json.JSONDecodeError:
        payload = {
            "result": "FAIL",
            "reason_code": "non_json_backend_response",
            "stdout": (completed.stdout or "").strip(),
            "stderr": (completed.stderr or "").strip(),
        }
    return completed.returncode, payload


def emit(payload: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        if payload.get("result") != "PASS":
            print(f"error: {payload.get('error', 'delivery failed')}")
            return 1
        print(f"result: {payload.get('result')}")
        if payload.get("run_id"):
            print(f"run_id: {payload.get('run_id')}")
        if payload.get("status"):
            print(f"status: {payload.get('status')}")
    return 0 if payload.get("result") == "PASS" else 1


def cmd_start(argv: list[str]) -> int:
    as_json = "--json" in argv
    execute = "--execute" in argv
    argv = [a for a in argv if a not in {"--json", "--execute"}]

    try:
        issue_id = parse_flag_value(argv, "--issue")
        workflow_file = parse_flag_value(argv, "--workflow")
        role = parse_flag_value(argv, "--role")
        owner = parse_flag_value(argv, "--by")
        handoff_to = parse_flag_value(argv, "--handoff-to")
    except ValueError:
        return usage()

    if not issue_id or not workflow_file:
        return usage()

    claim_cmd = [sys.executable, str(CLAIMS_SCRIPT), "claim", issue_id]
    if role:
        claim_cmd.extend(["--role", role])
    elif owner:
        claim_cmd.extend(["--by", owner])
    else:
        return usage()
    claim_cmd.append("--json")

    claim_code, claim_payload = run_json(claim_cmd)
    if claim_code != 0 or claim_payload.get("result") != "PASS":
        return emit(
            {
                "result": "FAIL",
                "command": "start",
                "error": "claim step failed",
                "reason_code": "claim_failed",
                "claim": claim_payload,
            },
            as_json,
        )

    workflow_cmd = [
        sys.executable,
        str(WORKFLOW_SCRIPT),
        "run",
        "--file",
        workflow_file,
    ]
    if execute:
        workflow_cmd.append("--execute")
    workflow_cmd.append("--json")
    workflow_code, workflow_payload = run_json(workflow_cmd)

    final_step = "none"
    final_payload: dict[str, Any] = {}
    status = str(workflow_payload.get("status") or "unknown")
    if (
        workflow_code == 0
        and workflow_payload.get("result") == "PASS"
        and status == "completed"
    ):
        if handoff_to:
            final_step = "handoff"
            _, final_payload = run_json(
                [
                    sys.executable,
                    str(CLAIMS_SCRIPT),
                    "handoff",
                    issue_id,
                    "--to",
                    handoff_to,
                    "--json",
                ]
            )
            status = "handoff-pending"
        else:
            final_step = "release"
            _, final_payload = run_json(
                [
                    sys.executable,
                    str(CLAIMS_SCRIPT),
                    "release",
                    issue_id,
                    "--json",
                ]
            )
            status = "completed"
    elif (
        workflow_code == 0
        and workflow_payload.get("result") == "PASS"
        and status == "failed"
    ):
        final_step = "claimed"
        status = "workflow-failed"
    else:
        final_step = "claimed"
        status = "workflow-error"

    run_id = f"dlv-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    run_record = {
        "run_id": run_id,
        "issue_id": issue_id,
        "workflow_file": workflow_file,
        "execute": execute,
        "status": status,
        "claim": claim_payload,
        "workflow": workflow_payload,
        "final_step": final_step,
        "final": final_payload,
        "created_at": now_iso(),
    }

    state = load_state(DEFAULT_STATE_PATH)
    runs = state.get("runs") if isinstance(state.get("runs"), list) else []
    runs.insert(0, run_record)
    state["runs"] = runs[:100]
    save_state(DEFAULT_STATE_PATH, state)

    result_value = "PASS"
    if status in {"workflow-error"}:
        result_value = "FAIL"
    return emit({"result": result_value, "command": "start", **run_record}, as_json)


def cmd_status(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    run_id = None
    try:
        run_id = parse_flag_value(argv, "--id")
    except ValueError:
        return usage()
    state = load_state(DEFAULT_STATE_PATH)
    runs = state.get("runs") if isinstance(state.get("runs"), list) else []
    if not runs:
        return emit(
            {
                "result": "PASS",
                "command": "status",
                "status": "idle",
                "warnings": ["no delivery runs recorded"],
            },
            as_json,
        )
    if run_id:
        match = next(
            (
                row
                for row in runs
                if isinstance(row, dict) and str(row.get("run_id") or "") == run_id
            ),
            None,
        )
        if not isinstance(match, dict):
            return emit(
                {
                    "result": "FAIL",
                    "command": "status",
                    "error": f"run not found: {run_id}",
                },
                as_json,
            )
        return emit({"result": "PASS", "command": "status", **match}, as_json)
    latest = runs[0] if isinstance(runs[0], dict) else {}
    return emit({"result": "PASS", "command": "status", **latest}, as_json)


def cmd_handoff(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    try:
        issue_id = parse_flag_value(argv, "--issue")
        to = parse_flag_value(argv, "--to")
    except ValueError:
        return usage()
    if not issue_id or not to:
        return usage()
    code, payload = run_json(
        [
            sys.executable,
            str(CLAIMS_SCRIPT),
            "handoff",
            issue_id,
            "--to",
            to,
            "--json",
        ]
    )
    if code != 0 or payload.get("result") != "PASS":
        return emit(
            {
                "result": "FAIL",
                "command": "handoff",
                "error": "handoff failed",
                "payload": payload,
            },
            as_json,
        )
    return emit({"result": "PASS", "command": "handoff", **payload}, as_json)


def cmd_close(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    try:
        issue_id = parse_flag_value(argv, "--issue")
    except ValueError:
        return usage()
    if not issue_id:
        return usage()
    code, payload = run_json(
        [sys.executable, str(CLAIMS_SCRIPT), "release", issue_id, "--json"]
    )
    if code != 0 or payload.get("result") != "PASS":
        return emit(
            {
                "result": "FAIL",
                "command": "close",
                "error": "close failed",
                "payload": payload,
            },
            as_json,
        )
    return emit({"result": "PASS", "command": "close", **payload}, as_json)


def cmd_doctor(argv: list[str]) -> int:
    as_json = "--json" in argv
    warnings: list[str] = []
    if not CLAIMS_SCRIPT.exists():
        warnings.append("claims command backend missing")
    if not WORKFLOW_SCRIPT.exists():
        warnings.append("workflow command backend missing")
    state = load_state(DEFAULT_STATE_PATH)
    runs = state.get("runs") if isinstance(state.get("runs"), list) else []
    return emit(
        {
            "result": "PASS",
            "command": "doctor",
            "state_path": str(DEFAULT_STATE_PATH),
            "runs": len(runs),
            "warnings": warnings,
            "quick_fixes": [
                "/delivery status --json",
                "/claims status --json",
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
    if command == "start":
        return cmd_start(rest)
    if command == "status":
        return cmd_status(rest)
    if command == "handoff":
        return cmd_handoff(rest)
    if command == "close":
        return cmd_close(rest)
    if command == "doctor":
        return cmd_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
