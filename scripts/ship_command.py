#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
RELEASE_TRAIN_SCRIPT = SCRIPT_DIR / "release_train_command.py"


def usage() -> int:
    print(
        "usage: /ship --version <x.y.z> [--allow-version-jump] [--breaking-change] [--json]"
    )
    return 2


def _pop_flag(args: list[str], flag: str) -> bool:
    if flag in args:
        args.remove(flag)
        return True
    return False


def _pop_value(args: list[str], flag: str) -> str | None:
    if flag not in args:
        return None
    idx = args.index(flag)
    if idx + 1 >= len(args):
        raise ValueError(f"{flag} requires a value")
    value = args[idx + 1]
    del args[idx : idx + 2]
    return value


def main(argv: list[str]) -> int:
    args = list(argv)
    as_json = _pop_flag(args, "--json")
    try:
        version = _pop_value(args, "--version")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    allow_jump = _pop_flag(args, "--allow-version-jump")
    breaking = _pop_flag(args, "--breaking-change")

    if args or not version:
        return usage()

    prepare_cmd = [
        sys.executable,
        str(RELEASE_TRAIN_SCRIPT),
        "prepare",
        "--version",
        version,
        "--json",
    ]
    if allow_jump:
        prepare_cmd.append("--allow-version-jump")
    if breaking:
        prepare_cmd.append("--breaking-change")

    prepare = subprocess.run(
        prepare_cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if prepare.returncode not in (0, 1):
        if prepare.stdout:
            print(prepare.stdout, end="")
        if prepare.stderr:
            print(prepare.stderr, end="", file=sys.stderr)
        return prepare.returncode

    try:
        prepare_payload = json.loads(prepare.stdout) if prepare.stdout else {}
    except json.JSONDecodeError:
        prepare_payload = {}

    ready = bool(prepare_payload.get("ready"))
    payload: dict[str, Any] = {
        "result": "PASS" if ready else "FAIL",
        "reason_code": "ship_ready" if ready else "ship_prepare_blocked",
        "version": version,
        "prepare": prepare_payload,
        "required_evidence": [
            "make validate",
            "make selftest",
            "make install-test",
            "pre-commit run --all-files",
            "PR summary/body prepared",
        ],
        "next_actions": [
            "/release-train draft --include-milestones --head HEAD --json",
            "gh pr create --title '<title>' --body '<summary>'",
        ]
        if ready
        else ["fix prepare blockers then re-run /ship --version <x.y.z> --json"],
    }

    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"result: {payload['result']}")
        print(f"reason_code: {payload['reason_code']}")
        print(f"version: {payload['version']}")
        print("next_actions:")
        for action in payload["next_actions"]:
            print(f"- {action}")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
