#!/usr/bin/env python3

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_DIGEST_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_DIGEST_PATH", "~/.config/opencode/digests/last-session.json"
    )
).expanduser()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_text(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def collect_git_snapshot(cwd: Path) -> dict:
    branch = run_text(["git", "-C", str(cwd), "branch", "--show-current"])
    status = run_text(["git", "-C", str(cwd), "status", "--short"])
    ahead_behind = run_text(["git", "-C", str(cwd), "status", "--short", "--branch"])

    status_lines = [line for line in status.splitlines() if line.strip()]
    return {
        "branch": branch or None,
        "status_count": len(status_lines),
        "status_preview": status_lines[:20],
        "branch_header": ahead_behind.splitlines()[0] if ahead_behind else None,
    }


def build_digest(reason: str, cwd: Path) -> dict:
    return {
        "timestamp": now_iso(),
        "reason": reason,
        "cwd": str(cwd),
        "git": collect_git_snapshot(cwd),
    }


def write_digest(path: Path, digest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(digest, indent=2) + "\n", encoding="utf-8")


def run_hook(command: str, digest_path: Path) -> int:
    env = os.environ.copy()
    env["MY_OPENCODE_DIGEST_PATH"] = str(digest_path)
    result = subprocess.run(command, shell=True, env=env, check=False)
    return result.returncode


def print_summary(path: Path, digest: dict) -> None:
    print(f"digest: {path}")
    print(f"timestamp: {digest.get('timestamp')}")
    print(f"reason: {digest.get('reason')}")
    print(f"cwd: {digest.get('cwd')}")
    git = digest.get("git", {}) if isinstance(digest.get("git"), dict) else {}
    print(f"branch: {git.get('branch')}")
    print(f"changes: {git.get('status_count')}")


def usage() -> int:
    print(
        'usage: /digest run [--reason <idle|exit|manual>] [--path <digest.json>] [--hook "command"] | /digest show [--path <digest.json>]'
    )
    return 2


def parse_option(argv: list[str], name: str) -> str | None:
    if name not in argv:
        return None
    index = argv.index(name)
    if index + 1 >= len(argv):
        return None
    return argv[index + 1]


def command_run(argv: list[str]) -> int:
    reason = parse_option(argv, "--reason") or "manual"
    path_value = parse_option(argv, "--path")
    hook_value = parse_option(argv, "--hook")

    path = Path(path_value).expanduser() if path_value else DEFAULT_DIGEST_PATH
    cwd = Path.cwd()

    digest = build_digest(reason=reason, cwd=cwd)
    write_digest(path, digest)
    print_summary(path, digest)

    if hook_value:
        code = run_hook(hook_value, path)
        print(f"hook: exited with code {code}")
        return code

    return 0


def command_show(argv: list[str]) -> int:
    path_value = parse_option(argv, "--path")
    path = Path(path_value).expanduser() if path_value else DEFAULT_DIGEST_PATH
    if not path.exists():
        print(f"error: digest file not found: {path}")
        return 1

    digest = json.loads(path.read_text(encoding="utf-8"))
    print_summary(path, digest)

    preview = digest.get("git", {}).get("status_preview", [])
    if preview:
        print("status preview:")
        for line in preview:
            print(f"- {line}")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        return usage()

    command = argv[0]
    rest = argv[1:]

    if command == "help":
        return usage()
    if command == "run":
        return command_run(rest)
    if command == "show":
        return command_show(rest)
    return usage()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
