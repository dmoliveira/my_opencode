#!/usr/bin/env python3
"""Validate README repo-layout script paths exist."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"


def main() -> int:
    text = README.read_text(encoding="utf-8")
    pattern = re.compile(r"^- `((?:scripts/|plugin/)[^`]+)`", re.M)
    rel_paths = sorted(set(pattern.findall(text)))

    missing: list[str] = []
    for rel in rel_paths:
        if not (REPO_ROOT / rel).exists():
            missing.append(rel)

    if missing:
        print("readme-layout-check: FAIL")
        for rel in missing:
            print(f"- missing path referenced in README: {rel}")
        return 1

    print("readme-layout-check: PASS")
    print(f"paths_checked: {len(rel_paths)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
