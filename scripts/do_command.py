#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
AUTOPILOT_SCRIPT = SCRIPT_DIR / "autopilot_command.py"


def usage() -> int:
    print("usage: /do <goal> [--json]")
    return 2


def main(argv: list[str]) -> int:
    args = list(argv)
    if not args:
        return usage()
    if args[0] in {"help", "--help", "-h"}:
        return usage()
    while "--json" in args:
        args.remove("--json")
    goal = " ".join(args).strip()
    if not goal:
        return usage()

    completed = subprocess.run(
        [
            sys.executable,
            str(AUTOPILOT_SCRIPT),
            "go",
            "--goal",
            goal,
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
