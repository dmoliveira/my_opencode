#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pr_review_analyzer import analyze_diff_text, analyze_git_range  # type: ignore


def usage() -> int:
    print(
        "usage: /pr-review [--base <ref>] [--head <ref>] [--diff-file <path>] [--json] | "
        "/pr-review checklist [--base <ref>] [--head <ref>] [--diff-file <path>] [--json] | "
        "/pr-review doctor [--json]"
    )
    return 2


def _parse_review_args(args: list[str]) -> tuple[dict[str, Any], int] | None:
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
        return None

    if diff_file is not None:
        if not diff_file.exists():
            return {
                "result": "FAIL",
                "code": "diff_file_not_found",
                "path": str(diff_file),
            }, 1
        report = analyze_diff_text(
            diff_file.read_text(encoding="utf-8"),
            base_ref=base_ref,
            head_ref=head_ref,
        )
    else:
        report = analyze_git_range(base_ref, head_ref)

    return {"json_output": json_output, "report": report}, 0


def _build_checklist(report: dict[str, Any]) -> dict[str, Any]:
    missing = set(report.get("missing_evidence", []))
    recommendation = str(report.get("recommendation") or "needs_review")
    blockers = report.get("blocking_reasons", [])
    blockers = blockers if isinstance(blockers, list) else []

    checks = [
        {
            "id": "risk_review",
            "status": "pass" if recommendation != "block" else "fail",
            "detail": "no blocker-level finding"
            if recommendation != "block"
            else "blockers detected",
        },
        {
            "id": "tests_evidence",
            "status": "pass" if "tests" not in missing else "warn",
            "detail": "tests updated"
            if "tests" not in missing
            else "missing test updates",
        },
        {
            "id": "readme_evidence",
            "status": "pass" if "README" not in missing else "warn",
            "detail": "README updated"
            if "README" not in missing
            else "README update missing",
        },
        {
            "id": "changelog_evidence",
            "status": "pass" if "CHANGELOG" not in missing else "warn",
            "detail": "CHANGELOG updated"
            if "CHANGELOG" not in missing
            else "CHANGELOG update missing",
        },
    ]

    return {
        "recommendation": recommendation,
        "blocking_reasons": blockers,
        "checks": checks,
        "next_actions": [
            "address all fail checks before merge",
            "resolve warn checks or justify them in PR description",
        ],
    }


def _emit_review(report: dict[str, Any], *, json_output: bool) -> int:
    checklist = _build_checklist(report)
    payload = dict(report)
    payload["checklist"] = checklist

    if json_output:
        print(json.dumps(payload, indent=2))
    else:
        print(f"recommendation: {payload.get('recommendation', 'unknown')}")
        print(f"files_changed: {payload.get('files_changed', 0)}")
        print(f"findings: {payload.get('summary', {}).get('findings', 0)}")
        for finding in payload.get("findings", [])[:5]:
            print(
                f"- {finding.get('severity')}/{finding.get('confidence')} {finding.get('category')}: {finding.get('title')}"
            )
        for check in checklist.get("checks", []):
            print(
                f"- checklist[{check.get('id')}]: {check.get('status')} ({check.get('detail')})"
            )

    return 0 if payload.get("result") == "PASS" else 1


def command_review(args: list[str]) -> int:
    parsed = _parse_review_args(args)
    if parsed is None:
        return usage()
    payload, code = parsed
    if code != 0:
        json_output = (
            bool(payload.get("json_output")) if isinstance(payload, dict) else False
        )
        if json_output:
            print(json.dumps(payload, indent=2))
        else:
            print(payload.get("code", "review_failed"))
        return code
    return _emit_review(payload["report"], json_output=bool(payload["json_output"]))


def command_checklist(args: list[str]) -> int:
    parsed = _parse_review_args(args)
    if parsed is None:
        return usage()
    payload, code = parsed
    if code != 0:
        json_output = (
            bool(payload.get("json_output")) if isinstance(payload, dict) else False
        )
        if json_output:
            print(json.dumps(payload, indent=2))
        else:
            print(payload.get("code", "checklist_failed"))
        return code

    report = payload["report"]
    checklist = _build_checklist(report)
    json_output = bool(payload["json_output"])
    if json_output:
        print(json.dumps({"result": "PASS", "checklist": checklist}, indent=2))
    else:
        print(f"recommendation: {checklist['recommendation']}")
        for check in checklist["checks"]:
            print(f"- {check['id']}: {check['status']} ({check['detail']})")
    return 0


def command_doctor(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    json_output = "--json" in args
    analyzer_exists = (SCRIPT_DIR / "pr_review_analyzer.py").exists()
    rubric_exists = (
        SCRIPT_DIR.parent / "instructions" / "pr_review_rubric.md"
    ).exists()

    warnings: list[str] = []
    problems: list[str] = []
    if not analyzer_exists:
        problems.append("missing scripts/pr_review_analyzer.py")
    if not rubric_exists:
        warnings.append("missing instructions/pr_review_rubric.md")

    report = {
        "result": "PASS" if not problems else "FAIL",
        "analyzer_exists": analyzer_exists,
        "rubric_exists": rubric_exists,
        "warnings": warnings,
        "problems": problems,
        "quick_fixes": [
            "/pr-review --base main --head HEAD --json",
            "/pr-review checklist --base main --head HEAD --json",
        ],
    }
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"result: {report['result']}")
        print(f"analyzer_exists: {report['analyzer_exists']}")
        print(f"rubric_exists: {report['rubric_exists']}")
        for warning in warnings:
            print(f"- warning: {warning}")
        for problem in problems:
            print(f"- problem: {problem}")
    return 0 if report["result"] == "PASS" else 1


def main(argv: list[str]) -> int:
    if not argv:
        return command_review([])

    command = argv[0]
    rest = argv[1:]

    if command in {"help", "--help", "-h"}:
        return usage()
    if command == "checklist":
        return command_checklist(rest)
    if command == "doctor":
        return command_doctor(rest)

    return command_review(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
