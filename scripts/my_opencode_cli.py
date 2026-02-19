#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
INSTALL_SCRIPT = REPO_ROOT / "install.sh"
DOCTOR_SCRIPT = SCRIPT_DIR / "doctor_command.py"
CLI_VERSION = "0.1.0"


def _run(command: Sequence[str], *, env: dict[str, str] | None = None) -> int:
    proc = subprocess.run(list(command), check=False, env=env)
    return int(proc.returncode)


def cmd_install(args: argparse.Namespace) -> int:
    env = os.environ.copy()
    if args.repo_url:
        env["REPO_URL"] = args.repo_url
    if args.install_dir:
        env["INSTALL_DIR"] = args.install_dir
    if args.repo_ref:
        env["REPO_REF"] = args.repo_ref

    command = ["bash", str(INSTALL_SCRIPT), "--non-interactive"]
    if args.skip_self_check:
        command.append("--skip-self-check")

    if args.dry_run:
        print(" ".join(command))
        return 0
    return _run(command, env=env)


def cmd_doctor(args: argparse.Namespace) -> int:
    command = [sys.executable, str(DOCTOR_SCRIPT), "run"]
    if args.json:
        command.append("--json")
    return _run(command)


def cmd_run(args: argparse.Namespace) -> int:
    binary = args.opencode_binary or shutil.which("opencode")
    if not binary:
        print("error: opencode binary not found", file=sys.stderr)
        return 1
    command = [binary, *args.opencode_args]
    return _run(command)


def cmd_version(_: argparse.Namespace) -> int:
    print(f"my_opencode-cli {CLI_VERSION}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="my_opencode packaged CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    install = sub.add_parser("install", help="Install my_opencode config")
    install.add_argument("--repo-url", default="", help="Repository URL override")
    install.add_argument("--repo-ref", default="", help="Repository ref override")
    install.add_argument("--install-dir", default="", help="Install target directory")
    install.add_argument("--skip-self-check", action="store_true")
    install.add_argument("--dry-run", action="store_true")
    install.set_defaults(func=cmd_install)

    doctor = sub.add_parser("doctor", help="Run diagnostics")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    run = sub.add_parser("run", help="Run opencode with passthrough args")
    run.add_argument("--opencode-binary", default="", help="Override opencode binary")
    run.add_argument("opencode_args", nargs=argparse.REMAINDER)
    run.set_defaults(func=cmd_run)

    version = sub.add_parser("version", help="Show CLI version")
    version.set_defaults(func=cmd_version)
    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
