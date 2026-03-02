#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


PR_LINE_RE = re.compile(r"^-\s+#\d+\b", flags=re.MULTILINE)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scores release-note quality signals for operator triage"
    )
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--note", action="append", default=[])
    parser.add_argument("--min-score", type=int, default=80)
    parser.add_argument("--enforce-threshold", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def gather_notes(repo_root: Path, explicit: list[str]) -> list[Path]:
    if explicit:
        return [Path(item).resolve() for item in explicit]
    return sorted((repo_root / "docs" / "plan").glob("release-notes-*.md"))


def note_quality(path: Path, min_score: int) -> dict[str, object]:
    text = path.read_text(encoding="utf-8", errors="replace")
    has_milestone_sources = "## Milestone Sources" in text
    has_included_prs = "## Included PRs" in text
    has_validation = "## Validation Evidence" in text
    has_lint_evidence = (
        "npm --prefix plugin/gateway-core run lint" in text
        or "npm run lint (in plugin/gateway-core)" in text
    )
    pr_entry_count = len(PR_LINE_RE.findall(text))
    has_pr_entries = pr_entry_count > 0
    checks = {
        "milestone_sources": has_milestone_sources,
        "included_prs": has_included_prs,
        "validation_evidence": has_validation,
        "lint_evidence": has_lint_evidence,
        "pr_entries": has_pr_entries,
    }
    passed = sum(1 for value in checks.values() if value)
    score = passed * 20
    reason_codes: list[str] = []
    if score < min_score:
        reason_codes.append("release_note_quality_below_threshold")
    if not has_lint_evidence:
        reason_codes.append("release_note_missing_lint_evidence")
    if not has_validation:
        reason_codes.append("release_note_missing_validation_section")
    return {
        "path": str(path),
        "score": score,
        "min_score": min_score,
        "checks": checks,
        "pr_entry_count": pr_entry_count,
        "reason_codes": reason_codes,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = (
        Path(args.repo_root).resolve()
        if args.repo_root
        else Path(__file__).resolve().parent.parent
    )
    notes = gather_notes(repo_root, args.note)
    entries: list[dict[str, object]] = []
    for path in notes:
        if not path.exists():
            entries.append(
                {
                    "path": str(path),
                    "score": 0,
                    "min_score": args.min_score,
                    "checks": {},
                    "pr_entry_count": 0,
                    "reason_codes": ["release_note_missing_file"],
                }
            )
            continue
        entries.append(note_quality(path, args.min_score))

    average_score = (
        int(sum(int(item["score"]) for item in entries) / len(entries))
        if entries
        else 0
    )
    below_threshold = [
        item
        for item in entries
        if int(item.get("score", 0)) < int(item.get("min_score", 0))
    ]
    reason_codes = sorted(
        {
            str(code)
            for item in entries
            for code in item.get("reason_codes", [])  # type: ignore[arg-type]
        }
    )
    result = "FAIL" if (args.enforce_threshold and below_threshold) else "PASS"
    payload = {
        "result": result,
        "reason_codes": reason_codes,
        "average_score": average_score,
        "note_count": len(entries),
        "below_threshold_count": len(below_threshold),
        "notes": entries,
        "quick_fixes": [
            "ensure release notes include Milestone Sources, Included PRs, and Validation Evidence sections",
            "add npm --prefix plugin/gateway-core run lint to validation evidence",
            "python3 scripts/release_note_quality_check.py --json",
        ],
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"result: {payload['result']}")
        print(f"average_score: {payload['average_score']}")
        print(f"note_count: {payload['note_count']}")
        print(f"below_threshold_count: {payload['below_threshold_count']}")
    return 0 if payload["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
