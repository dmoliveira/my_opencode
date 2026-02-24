#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def usage() -> int:
    print(
        "usage: /changes explain [--base <ref>] [--head <ref>] [--diff-file <path>] [--json]"
    )
    return 2


def _run_git(args: list[str]) -> tuple[int, str, str]:
    completed = subprocess.run(
        ["git", "--no-pager", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _parse_paths(diff_text: str) -> list[str]:
    paths: list[str] = []
    for line in diff_text.splitlines():
        if not line.startswith("diff --git "):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        raw = parts[3]
        if raw.startswith("b/"):
            raw = raw[2:]
        paths.append(raw)
    deduped: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return deduped


def _classify(paths: list[str]) -> dict[str, bool]:
    return {
        "scripts": any(path.startswith("scripts/") for path in paths),
        "docs": any(path.startswith("docs/") or path == "README.md" for path in paths),
        "tests": any(
            path.startswith("tests/")
            or path.endswith("_test.py")
            or path.endswith("selftest.py")
            for path in paths
        ),
        "config": any(path == "opencode.json" for path in paths),
    }


def _narrative(paths: list[str]) -> dict[str, Any]:
    categories = _classify(paths)
    why: list[str] = []
    risk: list[str] = []
    verify: list[str] = [
        "make validate",
        "make selftest",
        "make install-test",
        "pre-commit run --all-files",
    ]

    if categories["scripts"]:
        why.append("implementation behavior changed in command/runtime scripts")
    if categories["docs"]:
        why.append("operator docs and command references were aligned with behavior")
    if categories["config"]:
        why.append("slash command surface metadata was updated")
    if not why:
        why.append("changes are localized and low-impact")

    if categories["config"]:
        risk.append("command surface changed; verify command-doc parity")
    if categories["scripts"] and not categories["tests"]:
        risk.append("runtime changes without direct test-file edits")
    if not risk:
        risk.append("no high-risk migration signals detected")

    summary = (
        f"Updated {len(paths)} files across "
        f"{', '.join([name for name, enabled in categories.items() if enabled]) or 'general'} scope."
    )
    return {
        "summary": summary,
        "why": why,
        "risk": risk,
        "verify": verify,
        "paths": paths,
        "categories": categories,
    }


def command_explain(args: list[str]) -> int:
    as_json = "--json" in args
    base_ref = "main"
    head_ref = "HEAD"
    diff_file: Path | None = None

    index = 0
    while index < len(args):
        token = args[index]
        if token == "--json":
            index += 1
            continue
        if token == "--base" and index + 1 < len(args):
            base_ref = args[index + 1].strip()
            index += 2
            continue
        if token == "--head" and index + 1 < len(args):
            head_ref = args[index + 1].strip()
            index += 2
            continue
        if token == "--diff-file" and index + 1 < len(args):
            diff_file = Path(args[index + 1]).expanduser()
            index += 2
            continue
        return usage()

    if diff_file is not None:
        if not diff_file.exists():
            payload = {
                "result": "FAIL",
                "reason_code": "diff_file_not_found",
                "path": str(diff_file),
            }
            print(json.dumps(payload, indent=2) if as_json else payload["reason_code"])
            return 1
        diff_text = diff_file.read_text(encoding="utf-8", errors="replace")
    else:
        code, out, err = _run_git(["diff", f"{base_ref}...{head_ref}"])
        if code != 0:
            payload = {
                "result": "FAIL",
                "reason_code": "git_diff_failed",
                "detail": err.strip() or "unable to build diff",
            }
            print(json.dumps(payload, indent=2) if as_json else payload["reason_code"])
            return 1
        diff_text = out

    paths = _parse_paths(diff_text)
    payload = {
        "result": "PASS",
        **_narrative(paths),
        "base": base_ref,
        "head": head_ref,
    }
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(payload["summary"])
        print("why:")
        for line in payload["why"]:
            print(f"- {line}")
        print("risk:")
        for line in payload["risk"]:
            print(f"- {line}")
        print("verify:")
        for line in payload["verify"]:
            print(f"- {line}")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        return usage()
    command = argv[0]
    rest = argv[1:]
    if command in {"help", "--help", "-h"}:
        return usage()
    if command == "explain":
        return command_explain(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
