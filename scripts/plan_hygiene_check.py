#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


WORKLOG_ROW_RE = re.compile(
    r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$"
)
EVIDENCE_RE = re.compile(r"(https?://\S+|#[0-9]+)")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    reason_code: str
    message: str


def discover_plan_files(repo_root: Path) -> list[Path]:
    return sorted((repo_root / "docs" / "plan").glob("*plan*.md"))


def plan_is_active(text: str) -> bool:
    return "- [ ]" in text


def parse_utc(value: str) -> datetime | None:
    candidate = value.strip()
    if not UTC_RE.match(candidate):
        return None
    try:
        return datetime.strptime(candidate, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def collect_findings(path: Path, *, stale_cutoff: datetime) -> list[Finding]:
    findings: list[Finding] = []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for idx, raw in enumerate(lines, start=1):
        row_match = WORKLOG_ROW_RE.match(raw.strip())
        if not row_match:
            continue
        utc_value, task, status, notes = [part.strip() for part in row_match.groups()]
        if status.lower() != "done":
            continue
        completed_at = parse_utc(utc_value)
        if completed_at is None or completed_at > stale_cutoff:
            continue
        if EVIDENCE_RE.search(notes):
            continue
        findings.append(
            Finding(
                path=path,
                line=idx,
                reason_code="plan_hygiene_missing_closure_evidence",
                message=f"stale done worklog row '{task}' is missing closure evidence link",
            )
        )
    return findings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Checks plan worklog hygiene for stale done rows"
    )
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--plan", action="append", default=[])
    parser.add_argument("--stale-hours", type=int, default=12)
    parser.add_argument("--include-completed", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = (
        Path(args.repo_root).resolve()
        if args.repo_root
        else Path(__file__).resolve().parent.parent
    )
    if args.plan:
        plan_paths = [Path(item).resolve() for item in args.plan]
    else:
        plan_paths = discover_plan_files(repo_root)

    stale_cutoff = datetime.now(tz=UTC) - timedelta(hours=max(args.stale_hours, 0))
    findings: list[Finding] = []
    scanned_paths: list[str] = []
    skipped_completed: list[str] = []
    loaded: list[tuple[Path, str, bool]] = []
    for plan_path in plan_paths:
        if not plan_path.exists():
            findings.append(
                Finding(
                    path=plan_path,
                    line=1,
                    reason_code="plan_hygiene_missing_file",
                    message="plan file not found",
                )
            )
            continue
        text = plan_path.read_text(encoding="utf-8", errors="replace")
        loaded.append((plan_path, text, plan_is_active(text)))

    fallback_completed_path: str | None = None
    candidates: list[tuple[Path, str, bool]]
    if args.include_completed:
        candidates = loaded
    else:
        active = [item for item in loaded if item[2]]
        completed = [item for item in loaded if not item[2]]
        if active:
            candidates = active
            skipped_completed.extend(str(path) for path, _, _ in completed)
        elif completed:
            most_recent = max(completed, key=lambda item: item[0].stat().st_mtime)
            candidates = [most_recent]
            fallback_completed_path = str(most_recent[0])
            skipped_completed.extend(
                str(path) for path, _, _ in completed if path != most_recent[0]
            )
        else:
            candidates = []

    for plan_path, _, _ in candidates:
        scanned_paths.append(str(plan_path))
        findings.extend(collect_findings(plan_path, stale_cutoff=stale_cutoff))

    payload = {
        "result": "PASS" if not findings else "FAIL",
        "reason_codes": sorted({finding.reason_code for finding in findings}),
        "findings": [
            {
                "path": str(finding.path),
                "line": finding.line,
                "reason_code": finding.reason_code,
                "message": finding.message,
            }
            for finding in findings
        ],
        "scanned_plan_count": len(scanned_paths),
        "scanned_paths": scanned_paths,
        "skipped_completed_paths": skipped_completed,
        "stale_cutoff_utc": stale_cutoff.isoformat().replace("+00:00", "Z"),
        "fallback_completed_scan": fallback_completed_path,
        "quick_fixes": [
            "add PR/issue links to done worklog notes in stale plan rows",
            "python3 scripts/plan_hygiene_check.py --json",
        ],
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"result: {payload['result']}")
        print(f"scanned_plan_count: {payload['scanned_plan_count']}")
        print(f"stale_cutoff_utc: {payload['stale_cutoff_utc']}")
        for finding in payload["findings"]:
            print(
                f"- {finding['path']}:{finding['line']} "
                f"{finding['reason_code']} {finding['message']}"
            )
    return 0 if payload["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
