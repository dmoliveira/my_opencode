#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    plan_dir = repo_root / "docs" / "plan"
    note_files = sorted(plan_dir.glob("release-notes-*.md"))

    missing_validation_heading: list[str] = []
    for note_path in note_files:
        text = note_path.read_text(encoding="utf-8", errors="replace")
        if "## Validation Evidence" not in text:
            missing_validation_heading.append(str(note_path))

    payload = {
        "result": "PASS" if not missing_validation_heading else "FAIL",
        "reason_codes": []
        if not missing_validation_heading
        else ["release_notes_validation_heading_missing"],
        "checked_file_count": len(note_files),
        "missing_validation_heading": missing_validation_heading,
        "quick_fixes": [
            "ensure release-note artifacts include a '## Validation Evidence' section",
            "python3 scripts/release_note_validation_check.py",
        ],
    }
    print(json.dumps(payload, indent=2))
    return 0 if payload["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
