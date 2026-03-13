#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def usage() -> int:
    print(
        "usage: /worktree-helper maintenance [--directory <path>] [--branch <name>] [--command <text>] [--json]"
    )
    return 2


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized or "maintenance"


def shell_quote(value: str) -> str:
    return json.dumps(value)


def command_maintenance(args: list[str]) -> int:
    directory = Path.cwd()
    branch: str | None = None
    blocked_command: str | None = None
    json_output = False
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--json":
            json_output = True
            index += 1
            continue
        if token == "--directory":
            if index + 1 >= len(args):
                return usage()
            directory = Path(args[index + 1]).expanduser().resolve()
            index += 2
            continue
        if token == "--branch":
            if index + 1 >= len(args):
                return usage()
            branch = args[index + 1].strip()
            index += 2
            continue
        if token == "--command":
            if index + 1 >= len(args):
                return usage()
            blocked_command = args[index + 1].strip()
            index += 2
            continue
        return usage()

    repo_name = directory.name or "repo"
    blocked_slug = slugify(blocked_command or "maintenance")
    suggested_branch = branch or f"chore/{blocked_slug[:40]}"
    suggested_worktree = (directory.parent / f"{repo_name}-maint").resolve()
    create_command = f"git worktree add -b {shell_quote(suggested_branch)} {shell_quote(str(suggested_worktree))} HEAD"
    report = {
        "result": "PASS",
        "directory": str(directory),
        "suggested_worktree": str(suggested_worktree),
        "suggested_branch": suggested_branch,
        "blocked_command": blocked_command,
        "commands": [
            create_command,
            f"git -C {shell_quote(str(suggested_worktree))} status --short --branch",
        ],
    }
    if json_output:
        print(json.dumps(report, indent=2))
        return 0

    print(f"directory: {report['directory']}")
    print(f"suggested_worktree: {report['suggested_worktree']}")
    print(f"suggested_branch: {report['suggested_branch']}")
    if blocked_command:
        print(f"blocked_command: {blocked_command}")
    print("commands:")
    for command in report["commands"]:
        print(f"- {command}")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        return usage()
    command = argv[0].strip().lower()
    if command == "maintenance":
        return command_maintenance(argv[1:])
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
