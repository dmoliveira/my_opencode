#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import shlex
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
    return shlex.quote(value)


_SHELL_TOKEN = r'(?:"[^"]*"|\'[^\']*\'|\S+)'
_SAFE_ENV_PREFIX = rf"(?:(?:env\s+)?(?:[A-Za-z_][A-Za-z0-9_]*={_SHELL_TOKEN}\s+)*)"
_OC_BINARY = r"(?:[^\s;&|]*/)?oc"
_ALLOWED_OC_DIRECT_PATTERN = re.compile(
    rf"^{_SAFE_ENV_PREFIX}{_OC_BINARY}\s+(?:"
    rf"(?:current|next|queue)"
    rf"|(?:resume)(?:\s+.+)"
    rf"|(?:done)(?:\s+.+)"
    rf"|(?:end-session)(?:\s+.+)"
    rf")\s*$"
)


def is_direct_allowed_oc_command(command: str | None) -> bool:
    if not command:
        return False
    normalized = command.strip()
    if has_disallowed_shell_syntax(normalized):
        return False
    return bool(_ALLOWED_OC_DIRECT_PATTERN.match(normalized))


def direct_run_report(directory: Path, blocked_command: str) -> dict[str, object]:
    return {
        "result": "PASS",
        "mode": "direct_run",
        "directory": str(directory),
        "blocked_command": blocked_command,
        "note": (
            "This Codememory command is already allowed directly on protected main. "
            "Do not wrap it with the maintenance helper; run it directly instead."
        ),
        "commands": [blocked_command],
    }


def has_disallowed_shell_syntax(command: str) -> bool:
    quote: str | None = None
    index = 0
    while index < len(command):
        char = command[index]
        if quote:
            if char == quote:
                quote = None
            elif char == "\\" and quote == '"' and index + 1 < len(command):
                index += 1
            index += 1
            continue
        if char in {'"', "'"}:
            quote = char
            index += 1
            continue
        if char == "&" and index + 1 < len(command) and command[index + 1] == "&":
            return True
        if char == "|" and index + 1 < len(command) and command[index + 1] == "|":
            return True
        if char in {";", "\n", "|", "<", ">", "`", "(", ")"}:
            return True
        if char == "$" and index + 1 < len(command):
            next_char = command[index + 1]
            if next_char in {"(", "{"} or next_char.isalpha() or next_char == "_":
                return True
        index += 1
    return False


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

    if is_direct_allowed_oc_command(blocked_command):
        report = direct_run_report(directory, blocked_command)
    else:
        repo_name = directory.name or "repo"
        blocked_slug = slugify(blocked_command or "maintenance")
        suggested_branch = branch or f"chore/{blocked_slug[:40]}"
        suggested_worktree = (directory.parent / f"{repo_name}-maint").resolve()
        create_command = f"git worktree add -b {shell_quote(suggested_branch)} {shell_quote(str(suggested_worktree))} HEAD"
        report = {
            "result": "PASS",
            "mode": "maintenance_worktree",
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
    if report.get("mode") == "direct_run":
        print(f"note: {report['note']}")
    else:
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
