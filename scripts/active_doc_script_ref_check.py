#!/usr/bin/env python3
"""Ensure active operator docs do not reference missing scripts/*.py files."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_DOCS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs" / "quickstart.md",
    REPO_ROOT / "docs" / "command-handbook.md",
]


def main() -> int:
    missing: list[tuple[Path, str]] = []
    pattern = re.compile(r"scripts/([A-Za-z0-9_\-]+\.py)")

    for doc in ACTIVE_DOCS:
        if not doc.exists():
            continue
        text = doc.read_text(encoding="utf-8", errors="ignore")
        for script_name in sorted(set(pattern.findall(text))):
            script_path = REPO_ROOT / "scripts" / script_name
            if not script_path.exists():
                missing.append((doc, script_name))

    if missing:
        print("active-doc-script-ref-check: FAIL")
        for doc, script_name in missing:
            print(f"- missing scripts/{script_name} referenced in {doc.relative_to(REPO_ROOT)}")
        return 1

    print("active-doc-script-ref-check: PASS")
    print(f"docs_checked: {len([d for d in ACTIVE_DOCS if d.exists()])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
