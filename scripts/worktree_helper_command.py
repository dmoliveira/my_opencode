#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path


def usage() -> int:
    print(
        "usage: /worktree-helper maintenance [--directory <path>] [--branch <name>] [--command <text>] [--execute] [--json]"
    )
    return 2


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized or "maintenance"


def shell_quote(value: str) -> str:
    return shlex.quote(value)


_SHELL_TOKEN = r'(?:"[^"]*"|\'[^\']*\'|\S+)'
_SAFE_ENV_KEY = r"(?:CI|GIT_TERMINAL_PROMPT|GIT_EDITOR|GIT_PAGER|PAGER|GCM_INTERACTIVE|OPENCODE_SESSION_ID)"
_SAFE_ENV_PREFIX = rf"(?:(?:env\s+)?(?:{_SAFE_ENV_KEY}={_SHELL_TOKEN}\s+)*)"
_OC_BINARY = r"(?:[^\s;&|]*/)?oc"
_GIT_BINARY = r"(?:(?:[^\s;&|]*/)?rtk\s+)?(?:[^\s;&|]*/)?git"
_GH_BINARY = r"(?:(?:[^\s;&|]*/)?rtk\s+)?(?:[^\s;&|]*/)?gh"
_SQLITE_SAFE_FLAG = r"(?:-readonly|-header|-column|-csv|-json|-line|-list)"
_GIT_READ_ONLY_PATTERN = (
    rf"(?:status|diff|log"
    rf"|remote\s+-v"
    rf"|branch\s+--show-current"
    rf"|branch\s+-r(?:\s+--contains\s+{_SHELL_TOKEN})?"
    rf"|branch\s+(?:--list|-a)(?:\s+{_SHELL_TOKEN})*"
    rf"|remote\s+get-url\s+{_SHELL_TOKEN}"
    rf"|remote\s+add\s+{_SHELL_TOKEN}\s+{_SHELL_TOKEN}"
    rf"|remote\s+set-url\s+{_SHELL_TOKEN}\s+{_SHELL_TOKEN}"
    rf"|rev-parse(?:\s+{_SHELL_TOKEN})+"
    rf"|rev-list(?:\s+{_SHELL_TOKEN})+"
    rf"|merge-base(?:\s+{_SHELL_TOKEN})+"
    rf"|show(?:\s+{_SHELL_TOKEN})+"
    rf"|ls-files(?:\s+{_SHELL_TOKEN})*"
    rf"|for-each-ref(?:\s+{_SHELL_TOKEN})+"
    rf"|symbolic-ref(?:\s+{_SHELL_TOKEN})+"
    rf"|worktree\s+list(?:\s+{_SHELL_TOKEN})*)"
)


def sqlite_direct_pattern() -> re.Pattern[str]:
    return re.compile(
        rf"^{_SAFE_ENV_PREFIX}(?:[^\s;&|]*/)?sqlite3"
        rf"(?=[^;&|]*\s-readonly\b)(?:\s+{_SQLITE_SAFE_FLAG})*\s+{_SHELL_TOKEN}\s+"
        rf"(?:(?:\"\.(?:tables|schema(?:\s+[^\"]+)?)\")"
        rf"|(?:'\.(?:tables|schema(?:\s+[^']+)?)')"
        rf"|(?:\"PRAGMA\s+table_info\s*\([^\";=]+\)\s*;?\")"
        rf"|(?:'PRAGMA\s+table_info\s*\([^';=]+\)\s*;?')"
        rf"|(?:\"SELECT\b(?![^\";]*(?:load_extension|readfile|writefile|attach|pragma)\b)[^\";]*;?\")"
        rf"|(?:'SELECT\b(?![^';]*(?:load_extension|readfile|writefile|attach|pragma)\b)[^';]*;?'))\s*$"
    )


_ALLOWED_DIRECT_PATTERNS = [
    re.compile(rf"^{_SAFE_ENV_PREFIX}date(?:\s+.+)?\s*$"),
    re.compile(
        rf"^{_SAFE_ENV_PREFIX}{_OC_BINARY}\s+(?:"
        rf"(?:current|next|queue)(?:\s+.+)?"
        rf"|(?:resume)(?:\s+.+)"
        rf"|(?:done)(?:\s+.+)"
        rf"|(?:end-session)(?:\s+.+)"
        rf")\s*$"
    ),
    re.compile(rf"^{_SAFE_ENV_PREFIX}{_GIT_BINARY}\s+{_GIT_READ_ONLY_PATTERN}\s*$"),
    re.compile(rf"^{_SAFE_ENV_PREFIX}{_GIT_BINARY}\s+fetch(?:\s+--(?:all|prune|quiet))*\s*$"),
    re.compile(rf"^{_SAFE_ENV_PREFIX}{_GIT_BINARY}\s+pull\s+--rebase(?:\s+--autostash)?(?:\s+origin\s+(?:main|master))?\s*$"),
    re.compile(rf"^{_SAFE_ENV_PREFIX}{_GIT_BINARY}\s+remote\s+(?:-v|get-url\s+{_SHELL_TOKEN}|add\s+{_SHELL_TOKEN}\s+{_SHELL_TOKEN}|set-url\s+{_SHELL_TOKEN}\s+{_SHELL_TOKEN})\s*$"),
    re.compile(rf"^{_SAFE_ENV_PREFIX}{_GIT_BINARY}\s+push(?:\s+(?:-u|--set-upstream))?\s+origin\s+(?:main|master)\s*$"),
    re.compile(rf"^{_SAFE_ENV_PREFIX}{_GIT_BINARY}\s+worktree\s+(?:add|remove)(?:\s+.+)\s*$"),
    re.compile(rf"^{_SAFE_ENV_PREFIX}{_GIT_BINARY}\s+branch\s+(?:-d|--delete)(?:\s+.+)\s*$"),
    re.compile(rf"^{_SAFE_ENV_PREFIX}{_GIT_BINARY}\s+stash\s+(?:push(?:\s+.+)|list|show)\s*$"),
    re.compile(rf"^{_SAFE_ENV_PREFIX}{_GH_BINARY}\s+auth\s+status(?:\s+.+)?\s*$"),
    re.compile(rf"^{_SAFE_ENV_PREFIX}{_GH_BINARY}\s+pr\s+(?:view|checks)(?:\s+.+)?\s*$"),
    re.compile(rf"^{_SAFE_ENV_PREFIX}{_GH_BINARY}\s+repo\s+(?:view|create|edit)(?:\s+.+)?\s*$"),
    re.compile(rf"^{_SAFE_ENV_PREFIX}{_GH_BINARY}\s+api\s+user(?:\s+.+)?\s*$"),
    sqlite_direct_pattern(),
    re.compile(rf"^{_SAFE_ENV_PREFIX}npm\s+install\s+--yes(?:\s+--(?:no-audit|no-fund|silent|ignore-scripts))*\s*$"),
    re.compile(rf"^{_SAFE_ENV_PREFIX}npm\s+ci\s+--yes(?:\s+--(?:no-audit|no-fund|silent|ignore-scripts))*\s*$"),
    re.compile(rf"^{_SAFE_ENV_PREFIX}npm\s+init\s+-y\s*$"),
]


def is_direct_allowed_protected_main_command(command: str | None) -> bool:
    if not command:
        return False
    normalized = command.strip()
    if has_disallowed_shell_syntax(normalized):
        return False
    return any(pattern.match(normalized) for pattern in _ALLOWED_DIRECT_PATTERNS)


def direct_run_report(directory: Path, blocked_command: str) -> dict[str, object]:
    return {
        "result": "PASS",
        "mode": "direct_run",
        "directory": str(directory),
        "blocked_command": blocked_command,
        "note": (
            "This command is already allowed directly on protected main. "
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


def has_head_commit(directory: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=directory,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def parse_execute_command(command: str) -> tuple[dict[str, str], list[str]]:
    if has_disallowed_shell_syntax(command):
        raise ValueError("execute mode only supports a single command without shell chaining or redirection")
    argv = shlex.split(command)
    if not argv:
        raise ValueError("execute mode requires a command to run")
    env = os.environ.copy()
    while argv:
        token = argv[0]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", token):
            key, value = token.split("=", 1)
            env[key] = value
            argv.pop(0)
            continue
        if token == "env":
            argv.pop(0)
            continue
        break
    if not argv:
        raise ValueError("execute mode requires a command after environment assignments")
    return env, argv


def command_maintenance(args: list[str]) -> int:
    directory = Path.cwd()
    branch: str | None = None
    blocked_command: str | None = None
    json_output = False
    execute = False
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--json":
            json_output = True
            index += 1
            continue
        if token == "--execute":
            execute = True
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

    if execute:
        if not blocked_command:
            return usage()
        try:
            env, argv = parse_execute_command(blocked_command)
            result = subprocess.run(
                argv,
                cwd=directory,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        except (OSError, ValueError) as exc:
            report = {
                "result": "ERROR",
                "directory": str(directory),
                "command": blocked_command,
                "error": str(exc),
            }
            if json_output:
                print(json.dumps(report, indent=2))
            else:
                print(str(exc), file=sys.stderr)
            return 1

        report = {
            "result": "EXECUTED",
            "directory": str(directory),
            "command": blocked_command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        if json_output:
            print(json.dumps(report, indent=2))
        else:
            if result.stdout:
                print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)
        return result.returncode

    if is_direct_allowed_protected_main_command(blocked_command):
        report = direct_run_report(directory, blocked_command)
    else:
        repo_name = directory.name or "repo"
        blocked_slug = slugify(blocked_command or "maintenance")
        suggested_branch = branch or f"chore/{blocked_slug[:40]}"
        suggested_worktree = (directory.parent / f"{repo_name}-wt-maintenance").resolve()
        if has_head_commit(directory):
            create_command = f"git worktree add -b {shell_quote(suggested_branch)} {shell_quote(str(suggested_worktree))} HEAD"
            followup_command = f"git -C {shell_quote(str(suggested_worktree))} status --short --branch"
        else:
            create_command = (
                f'git -C {shell_quote(str(directory))} add . && '
                f'git -C {shell_quote(str(directory))} commit -m "Initial commit"'
            )
            followup_command = f"git -C {shell_quote(str(directory))} status --short --branch"
        report = {
            "result": "FAIL",
            "mode": "maintenance_worktree",
            "directory": str(directory),
            "suggested_worktree": str(suggested_worktree),
            "suggested_branch": suggested_branch,
            "blocked_command": blocked_command,
            "note": (
                "Guidance only: the blocked command was not executed. "
                "Create or use the suggested worktree and rerun the intended command there."
            ),
            "commands": [
                create_command,
                followup_command,
            ],
        }
    if json_output:
        print(json.dumps(report, indent=2))
        return 0 if report.get("mode") == "direct_run" else 3

    print(f"directory: {report['directory']}")
    if report.get("mode") == "direct_run":
        print(f"note: {report['note']}")
    else:
        print(f"suggested_worktree: {report['suggested_worktree']}")
        print(f"suggested_branch: {report['suggested_branch']}")
        print(f"note: {report['note']}")
    if blocked_command:
        print(f"blocked_command: {blocked_command}")
    print("commands:")
    for command in report["commands"]:
        print(f"- {command}")
    return 0 if report.get("mode") == "direct_run" else 3


def main(argv: list[str]) -> int:
    if not argv:
        return usage()
    command = argv[0].strip().lower()
    if command == "maintenance":
        return command_maintenance(argv[1:])
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
