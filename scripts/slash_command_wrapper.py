#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path


TRUSTED_SCRIPT_DIR = Path(__file__).resolve().parent

WRAPPER_SCRIPT_OVERRIDES = {
    "bg": "background_task_manager.py",
    "stack": "stack_profile_command.py",
    "nvim": "nvim_integration_command.py",
    "digest": "session_digest.py",
}


def resolve_backend_script(command_name: str) -> Path | None:
    normalized = command_name.strip().lower().replace("-", "_")
    if not normalized:
        return None
    candidates = []
    override = WRAPPER_SCRIPT_OVERRIDES.get(command_name.strip().lower())
    if override:
        candidates.append(override)
    candidates.extend([f"{normalized}_command.py", f"{normalized}.py"])
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        path = TRUSTED_SCRIPT_DIR / candidate
        if path.exists():
            return path.resolve()
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safely dispatch slash command backends"
    )
    parser.add_argument(
        "--script", required=True, help="Absolute path to backend python script"
    )
    parser.add_argument(
        "--fixed-before",
        action="append",
        default=[],
        help="Fixed argument inserted before parsed/literal args",
    )
    parser.add_argument(
        "--fixed-after",
        action="append",
        default=[],
        help="Fixed argument appended after parsed/literal args",
    )
    parser.add_argument(
        "--raw-args", default="", help="Raw argument string parsed with shlex"
    )
    parser.add_argument(
        "--literal", default=None, help="Single literal argument to append as-is"
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    script = Path(args.script).expanduser()
    if not script.is_absolute():
        print("error: wrapper requires an absolute script path", file=sys.stderr)
        return 2
    try:
        resolved_script = script.resolve(strict=True)
    except FileNotFoundError:
        print(f"error: wrapper script not found: {script}", file=sys.stderr)
        return 2
    if resolved_script.parent != TRUSTED_SCRIPT_DIR:
        print(
            f"error: wrapper rejected untrusted script path: {resolved_script}",
            file=sys.stderr,
        )
        return 2
    fixed_before = list(args.fixed_before)
    if resolved_script == Path(__file__).resolve():
        if not fixed_before:
            print(
                "error: wrapper dispatch requires command name in --fixed-before",
                file=sys.stderr,
            )
            return 2
        command_name = fixed_before.pop(0)
        dispatched = resolve_backend_script(command_name)
        if dispatched is None:
            print(
                f"error: wrapper has no backend mapping for command: {command_name}",
                file=sys.stderr,
            )
            return 2
        resolved_script = dispatched
    command = [sys.executable, str(resolved_script), *args.fixed_before]
    if fixed_before is not args.fixed_before:
        command = [sys.executable, str(resolved_script), *fixed_before]
    raw_args = str(args.raw_args or "").strip()
    if raw_args:
        command.extend(shlex.split(raw_args))
    if args.literal is not None:
        command.append(args.literal)
    command.extend(args.fixed_after)
    completed = subprocess.run(command, check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
