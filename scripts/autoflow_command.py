#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
START_WORK_SCRIPT = SCRIPT_DIR / "start_work_command.py"


def usage() -> int:
    print(
        "usage: /autoflow start <plan.md> [--deviation <note> ...] [--background] [--json] | /autoflow status [--json] | /autoflow report [--json] | /autoflow resume --interruption-class <class> [--approve-step <ordinal> ...] [--json] | /autoflow doctor [--json]"
    )
    return 2


def run_start_work(args: list[str]) -> int:
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


def main(argv: list[str]) -> int:
    if not START_WORK_SCRIPT.exists():
        print("autoflow: backend unavailable (missing start_work_command.py)")
        return 1

    if not argv or argv[0] in {"help", "-h", "--help"}:
        return usage()

    command = argv[0]
    rest = argv[1:]

    if command == "start":
        if not rest:
            return usage()
        return run_start_work(rest)

    if command == "status":
        return run_start_work(["status", *rest])

    if command == "report":
        return run_start_work(["deviations", *rest])

    if command == "resume":
        return run_start_work(["recover", *rest])

    if command == "doctor":
        return run_start_work(["doctor", *rest])

    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
