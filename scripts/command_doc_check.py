#!/usr/bin/env python3
"""Validate command-handbook references against opencode command map."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HANDBOOK = REPO_ROOT / "docs" / "command-handbook.md"
CONFIG = REPO_ROOT / "opencode.json"


def load_known_commands() -> set[str]:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    command_map = payload.get("command", {})
    return set(command_map) if isinstance(command_map, dict) else set()


def parse_referenced_heads() -> set[str]:
    heads: set[str] = set()
    inside_block = False
    pattern = re.compile(r"^/([a-z0-9][a-z0-9\-]*)\b")
    for line in HANDBOOK.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("```"):
            inside_block = not inside_block
            continue
        if not inside_block:
            continue
        match = pattern.match(line.strip())
        if match:
            heads.add(match.group(1))
    return heads


def main() -> int:
    if not HANDBOOK.exists():
        print("command-doc-check: FAIL")
        print("- missing docs/command-handbook.md")
        return 1

    known = load_known_commands()
    referenced = parse_referenced_heads()
    unknown = sorted(item for item in referenced if item not in known)

    if unknown:
        print("command-doc-check: FAIL")
        for item in unknown:
            print(f"- unknown command in handbook: /{item}")
        return 1

    print("command-doc-check: PASS")
    print(f"references_checked: {len(referenced)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
