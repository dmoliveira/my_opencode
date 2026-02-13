#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SEVERITY_SCORE = {"S0": 0, "S1": 1, "S2": 2, "S3": 3}
CONFIDENCE_SCORE = {"C0": 0, "C1": 1, "C2": 2, "C3": 3}

SECURITY_PATTERNS = [
    re.compile(r"\beval\s*\("),
    re.compile(r"\bos\.system\s*\("),
    re.compile(r"\bshell\s*=\s*True\b"),
]

DATA_LOSS_PATTERNS = [
    re.compile(r"\brm\s+-rf\b"),
    re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bTRUNCATE\b", re.IGNORECASE),
]

HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass
class DiffEntry:
    path: str
    added: list[tuple[int, str]]
    removed: list[tuple[int, str]]


def usage() -> int:
    print(
        "usage: /pr-review-analyzer analyze [--base <ref>] [--head <ref>] [--diff-file <path>] [--json]"
    )
    return 2


def _normalize_path(raw: str) -> str:
    if raw.startswith("a/") or raw.startswith("b/"):
        return raw[2:]
    return raw


def parse_diff(diff_text: str) -> list[DiffEntry]:
    entries: list[DiffEntry] = []
    current: DiffEntry | None = None
    current_line = 0

    for raw in diff_text.splitlines():
        line = raw.rstrip("\n")

        if line.startswith("diff --git "):
            parts = line.split()
            path = _normalize_path(parts[3]) if len(parts) >= 4 else "unknown"
            current = DiffEntry(path=path, added=[], removed=[])
            entries.append(current)
            current_line = 0
            continue

        if current is None:
            continue

        if line.startswith("+++ "):
            plus_path = line[4:].strip()
            if plus_path != "/dev/null":
                current.path = _normalize_path(plus_path)
            continue

        hunk = HUNK_RE.match(line)
        if hunk:
            current_line = int(hunk.group(1))
            continue

        if line.startswith("+") and not line.startswith("+++"):
            if current_line <= 0:
                current_line = 1
            current.added.append((current_line, line[1:]))
            current_line += 1
            continue

        if line.startswith("-") and not line.startswith("---"):
            if current_line <= 0:
                current_line = 1
            current.removed.append((current_line, line[1:]))
            continue

        if not line.startswith("\\") and current_line > 0:
            current_line += 1

    return [entry for entry in entries if entry.path and entry.path != "unknown"]


def _is_test_file(path: str) -> bool:
    return (
        path.startswith("tests/")
        or path.endswith("_test.py")
        or path.endswith("selftest.py")
    )


def _is_docs_file(path: str) -> bool:
    return (
        path == "README.md"
        or path == "CHANGELOG.md"
        or path.startswith("instructions/")
    )


def _changed_areas(paths: set[str]) -> list[str]:
    areas: set[str] = set()
    for path in paths:
        if path.startswith("scripts/"):
            areas.add("scripts")
        if _is_test_file(path):
            areas.add("tests")
        if _is_docs_file(path):
            areas.add("docs")
        if path == "opencode.json":
            areas.add("config")
        if "command" in path:
            areas.add("command_surface")
    return sorted(areas)


def _make_finding(
    *,
    finding_id: str,
    category: str,
    severity: str,
    confidence: str,
    title: str,
    rationale: str,
    action: str,
    refs: list[str],
    hard_evidence: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "category": category,
        "severity": severity,
        "confidence": confidence,
        "title": title,
        "rationale": rationale,
        "recommended_action": action,
        "file_refs": refs,
        "hard_evidence": hard_evidence or [],
    }


def analyze_diff_text(
    diff_text: str, *, base_ref: str, head_ref: str
) -> dict[str, Any]:
    entries = parse_diff(diff_text)
    changed_paths = {entry.path for entry in entries}
    findings: list[dict[str, Any]] = []
    missing_evidence: list[str] = []

    source_paths = {
        path
        for path in changed_paths
        if path.startswith("scripts/") and not _is_test_file(path)
    }
    has_tests = any(_is_test_file(path) for path in changed_paths)
    has_readme = "README.md" in changed_paths
    has_changelog = "CHANGELOG.md" in changed_paths

    security_hits: list[tuple[str, int, str]] = []
    destructive_hits: list[tuple[str, int, str]] = []
    for entry in entries:
        for line_no, text in entry.added:
            for pattern in SECURITY_PATTERNS:
                if pattern.search(text):
                    security_hits.append((entry.path, line_no, text.strip()))
            for pattern in DATA_LOSS_PATTERNS:
                if pattern.search(text):
                    destructive_hits.append((entry.path, line_no, text.strip()))

    if security_hits:
        refs = [f"{path}:{line}" for path, line, _ in security_hits[:3]]
        evidence = [
            f"{path}:{line} `{snippet}`" for path, line, snippet in security_hits[:2]
        ]
        findings.append(
            _make_finding(
                finding_id="security_unsafe_execution",
                category="security",
                severity="S3",
                confidence="C2",
                title="Unsafe command/input execution pattern detected",
                rationale="Added code introduces a known unsafe execution pattern.",
                action="Replace with a validated safe execution path and document guardrails.",
                refs=refs,
                hard_evidence=evidence,
            )
        )

    if destructive_hits:
        refs = [f"{path}:{line}" for path, line, _ in destructive_hits[:3]]
        evidence = [
            f"{path}:{line} `{snippet}`" for path, line, snippet in destructive_hits[:2]
        ]
        findings.append(
            _make_finding(
                finding_id="data_loss_destructive_operation",
                category="data_loss",
                severity="S3",
                confidence="C2",
                title="Potential destructive data operation detected",
                rationale="Diff contains destructive operation patterns that may be non-reversible.",
                action="Add explicit safeguards and rollback verification before merge.",
                refs=refs,
                hard_evidence=evidence,
            )
        )

    migration_files = {
        path
        for path in changed_paths
        if path == "opencode.json"
        or path.startswith("instructions/")
        or path.endswith("_command.py")
    }
    if migration_files:
        sorted_files = sorted(migration_files)
        findings.append(
            _make_finding(
                finding_id="migration_contract_change",
                category="migration_impact",
                severity="S2",
                confidence="C2",
                title="Command/config contract surface changed",
                rationale="Diff updates command/config surfaces that can affect operator workflows.",
                action="Confirm compatibility notes and migration guidance are explicit.",
                refs=[f"{path}:1" for path in sorted_files[:3]],
            )
        )

    if source_paths and not has_tests:
        missing_evidence.append("tests")
        target = sorted(source_paths)[0]
        findings.append(
            _make_finding(
                finding_id="missing_test_evidence",
                category="test_coverage",
                severity="S2",
                confidence="C2",
                title="Source changes without matching test updates",
                rationale="Executable source changed but no test files were touched.",
                action="Add or update tests that cover modified behavior and failure paths.",
                refs=[f"{target}:1"],
            )
        )

    if source_paths and (not has_readme or not has_changelog):
        if not has_readme:
            missing_evidence.append("README")
        if not has_changelog:
            missing_evidence.append("CHANGELOG")
        target = sorted(source_paths)[0]
        findings.append(
            _make_finding(
                finding_id="missing_docs_changelog_evidence",
                category="docs_changelog",
                severity="S2",
                confidence="C2",
                title="Operational docs/changelog updates are missing",
                rationale="Behavioral changes are present without complete release/operator documentation updates.",
                action="Update README and CHANGELOG with usage impact and verification notes.",
                refs=[f"{target}:1"],
            )
        )

    findings.sort(
        key=lambda item: (
            -SEVERITY_SCORE.get(str(item.get("severity")), 0),
            -CONFIDENCE_SCORE.get(str(item.get("confidence")), 0),
            str(item.get("id") or ""),
        )
    )

    blocker = any(
        SEVERITY_SCORE.get(str(item.get("severity")), 0) >= SEVERITY_SCORE["S3"]
        and CONFIDENCE_SCORE.get(str(item.get("confidence")), 0)
        >= CONFIDENCE_SCORE["C2"]
        and bool(item.get("hard_evidence"))
        for item in findings
    )

    s2_c2_count = sum(
        1
        for item in findings
        if str(item.get("severity")) == "S2"
        and CONFIDENCE_SCORE.get(str(item.get("confidence")), 0)
        >= CONFIDENCE_SCORE["C2"]
    )

    if blocker:
        recommendation = "block"
    elif s2_c2_count >= 2:
        recommendation = "changes_requested"
    elif s2_c2_count >= 1:
        recommendation = "needs_review"
    else:
        recommendation = "approve"

    category_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    for item in findings:
        category = str(item.get("category") or "unknown")
        severity = str(item.get("severity") or "S0")
        category_counts[category] = category_counts.get(category, 0) + 1
        severity_counts[severity] = severity_counts.get(severity, 0) + 1

    blocking_reasons = [
        item.get("title")
        for item in findings
        if item.get("hard_evidence") and str(item.get("severity")) == "S3"
    ]

    return {
        "result": "PASS",
        "base_ref": base_ref,
        "head_ref": head_ref,
        "files_changed": len(changed_paths),
        "changed_areas": _changed_areas(changed_paths),
        "summary": {
            "findings": len(findings),
            "category_counts": category_counts,
            "severity_counts": severity_counts,
        },
        "recommendation": recommendation,
        "blocking_reasons": blocking_reasons,
        "missing_evidence": sorted(set(missing_evidence)),
        "findings": findings,
    }


def analyze_git_range(base_ref: str, head_ref: str) -> dict[str, Any]:
    result = subprocess.run(
        ["git", "diff", "--unified=0", f"{base_ref}...{head_ref}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return {
            "result": "FAIL",
            "code": "git_diff_failed",
            "detail": result.stderr.strip() or "failed to read git diff range",
            "base_ref": base_ref,
            "head_ref": head_ref,
        }
    return analyze_diff_text(result.stdout, base_ref=base_ref, head_ref=head_ref)


def main(argv: list[str]) -> int:
    if not argv:
        return usage()

    command = argv[0]
    args = argv[1:]
    if command not in {"analyze", "help", "--help", "-h"}:
        return usage()
    if command in {"help", "--help", "-h"}:
        return usage()

    json_output = "--json" in args
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
            report = {
                "result": "FAIL",
                "code": "diff_file_not_found",
                "path": str(diff_file),
            }
            print(json.dumps(report, indent=2) if json_output else report["code"])
            return 1
        report = analyze_diff_text(
            diff_file.read_text(encoding="utf-8"),
            base_ref=base_ref,
            head_ref=head_ref,
        )
    else:
        report = analyze_git_range(base_ref, head_ref)

    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"recommendation: {report.get('recommendation', 'unknown')}")
        print(f"files_changed: {report.get('files_changed', 0)}")
        print(f"findings: {report.get('summary', {}).get('findings', 0)}")
        for finding in report.get("findings", [])[:5]:
            print(
                f"- {finding.get('severity')}/{finding.get('confidence')} {finding.get('category')}: {finding.get('title')}"
            )

    return 0 if report.get("result") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
