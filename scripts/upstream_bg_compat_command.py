#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
BG_MANAGER_SCRIPT = SCRIPT_DIR / "background_task_manager.py"


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean: {value}")


def _run_bg_manager(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(BG_MANAGER_SCRIPT), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def _job_id_from_output(stdout: str) -> str:
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("id: "):
            return stripped.replace("id: ", "", 1).strip()
    return ""


def _emit(payload: dict[str, Any], *, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("result") in {"PASS", "WARN"} else 1
    for key in ("result", "task_id", "status", "message"):
        if key in payload and payload[key] is not None:
            print(f"{key}: {payload[key]}")
    return 0 if payload.get("result") in {"PASS", "WARN"} else 1


def _compat_call(args: argparse.Namespace) -> dict[str, Any]:
    cwd = Path(args.cwd).expanduser().resolve()
    run_in_background = _parse_bool(str(args.run_in_background))
    command_text = str(args.command or "").strip()
    if not command_text:
        return {
            "result": "FAIL",
            "code": "missing_command",
            "message": "compat call requires --command",
        }

    labels = ["upstream_compat"]
    if args.subagent_type:
        labels.append(str(args.subagent_type))

    if run_in_background:
        bg_args = [
            "start",
            "--cwd",
            str(cwd),
            "--timeout-seconds",
            str(int(args.timeout_seconds)),
        ]
        for label in labels:
            bg_args.extend(["--label", label])
        bg_args.extend(["--", "bash", "-lc", command_text])
        proc = _run_bg_manager(bg_args, cwd=cwd)
        job_id = _job_id_from_output(proc.stdout)
        if proc.returncode != 0 or not job_id:
            return {
                "result": "FAIL",
                "code": "background_start_failed",
                "message": proc.stderr.strip() or proc.stdout.strip(),
                "backend": "bg",
            }
        compat_task_id = job_id if job_id.startswith("bg_") else f"bg_{job_id}"
        return {
            "result": "PASS",
            "mode": "background",
            "backend": "bg",
            "task_id": compat_task_id,
            "status": "queued",
            "mapped_command": "/bg start",
            "subagent_type": args.subagent_type,
            "prompt": args.prompt,
            "command": command_text,
        }

    proc = subprocess.run(
        ["bash", "-lc", command_text],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "result": "PASS" if proc.returncode == 0 else "FAIL",
        "mode": "foreground",
        "backend": "shell",
        "task_id": None,
        "status": "completed" if proc.returncode == 0 else "failed",
        "mapped_command": "direct shell",
        "subagent_type": args.subagent_type,
        "prompt": args.prompt,
        "command": command_text,
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _compat_output(args: argparse.Namespace) -> dict[str, Any]:
    cwd = Path(args.cwd).expanduser().resolve()
    task_id = str(args.task_id).strip()
    if not task_id:
        return {
            "result": "FAIL",
            "code": "missing_task_id",
            "message": "background_output requires --task-id",
        }
    candidate_ids = [task_id]
    if task_id.startswith("bg_"):
        stripped = task_id[3:]
        if stripped and stripped not in candidate_ids:
            candidate_ids.append(stripped)

    proc: subprocess.CompletedProcess[str] | None = None
    used_job_id = ""
    for candidate in candidate_ids:
        trial = _run_bg_manager(
            ["read", candidate, "--tail", str(int(args.tail)), "--json"],
            cwd=cwd,
        )
        if trial.returncode == 0:
            proc = trial
            used_job_id = candidate
            break
        proc = trial

    if proc is None or proc.returncode != 0:
        return {
            "result": "FAIL",
            "code": "background_read_failed",
            "task_id": task_id,
            "message": (proc.stderr.strip() if proc else "")
            or (proc.stdout.strip() if proc else "")
            or "unable to resolve background task id",
        }

    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {
            "result": "FAIL",
            "code": "invalid_background_payload",
            "task_id": task_id,
            "message": "bg read returned non-json payload",
        }

    job = report.get("job") or {}
    status = str(job.get("status") or "unknown")
    result = "PASS" if status == "completed" else "WARN"
    if status in {"failed", "cancelled"}:
        result = "FAIL"

    return {
        "result": result,
        "task_id": task_id,
        "job_id": used_job_id,
        "backend": "bg",
        "status": status,
        "completed": status in {"completed", "failed", "cancelled"},
        "summary": job.get("summary"),
        "log_tail": report.get("log_tail", ""),
        "job": job,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upstream_bg_compat_command.py",
        description="Upstream-style background delegation compatibility facade over /bg.",
    )
    sub = parser.add_subparsers(dest="subcommand")

    call = sub.add_parser(
        "call_omo_agent", help="compat facade for upstream background delegation"
    )
    call.add_argument("--subagent-type", default="explore")
    call.add_argument("--prompt", default="")
    call.add_argument("--command", required=True)
    call.add_argument("--run-in-background", default="true")
    call.add_argument("--timeout-seconds", type=int, default=1800)
    call.add_argument("--cwd", default=str(Path.cwd()))
    call.add_argument("--json", action="store_true")

    output = sub.add_parser(
        "background_output",
        help="compat facade for upstream background result retrieval",
    )
    output.add_argument("--task-id", required=True)
    output.add_argument("--tail", type=int, default=60)
    output.add_argument("--cwd", default=str(Path.cwd()))
    output.add_argument("--json", action="store_true")

    status = sub.add_parser("status", help="show compatibility facade status")
    status.add_argument("--json", action="store_true")

    sub.add_parser("help", help="show usage")
    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.subcommand in {None, "help"}:
        parser.print_help()
        return 0 if args.subcommand == "help" else 2

    if args.subcommand == "status":
        payload = {
            "result": "PASS",
            "mode": "compatibility_facade",
            "facade": ["call_omo_agent", "background_output"],
            "mapped_runtime": "/bg",
        }
        return _emit(payload, as_json=bool(args.json))

    if args.subcommand == "call_omo_agent":
        payload = _compat_call(args)
        return _emit(payload, as_json=bool(args.json))

    if args.subcommand == "background_output":
        payload = _compat_output(args)
        return _emit(payload, as_json=bool(args.json))

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
