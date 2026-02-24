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
from flow_reason_codes import (  # type: ignore
    DIFF_FILE_NOT_FOUND,
    REVIEW_CHECKLIST_GENERATED,
    REVIEW_REPORT_INVALID,
)


def usage() -> int:
    print(
        "usage: /review local [--base <ref>] [--head <ref>] [--diff-file <path>] [--json] | "
        "/review apply-checklist [--base <ref>] [--head <ref>] [--diff-file <path>] [--json] | "
        "/review doctor [--json]"
    )
    return 2


def _parse_local_args(args: list[str]) -> tuple[dict[str, Any], int] | None:
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
        return None

    if diff_file is not None:
        if not diff_file.exists():
            return {
                "result": "FAIL",
                "reason_code": DIFF_FILE_NOT_FOUND,
                "path": str(diff_file),
                "json_output": as_json,
            }, 1
        report = analyze_diff_text(
            diff_file.read_text(encoding="utf-8"),
            base_ref=base_ref,
            head_ref=head_ref,
        )
    else:
        report = analyze_git_range(base_ref, head_ref)

    return {"report": report, "json_output": as_json}, 0


def _local_sections(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    missing = {
        str(item)
        for item in report.get("missing_evidence", [])
        if isinstance(item, str)
    }
    recommendation = str(report.get("recommendation") or "needs_review")
    blockers = report.get("blocking_reasons", [])
    blockers = blockers if isinstance(blockers, list) else []
    changed_areas = {
        str(area) for area in report.get("changed_areas", []) if isinstance(area, str)
    }

    correctness = {
        "status": "pass" if recommendation != "block" else "fail",
        "detail": "no blocker-level findings"
        if recommendation != "block"
        else "blockers detected in review findings",
    }
    risk = {
        "status": "pass" if not blockers else "fail",
        "detail": "no blocking risks" if not blockers else "; ".join(blockers[:2]),
    }
    tests = {
        "status": "pass" if "tests" not in missing else "warn",
        "detail": "tests evidence present"
        if "tests" not in missing
        else "missing test evidence for source changes",
    }
    docs = {
        "status": "pass"
        if "README" not in missing and "CHANGELOG" not in missing
        else "warn",
        "detail": "docs evidence present"
        if "README" not in missing and "CHANGELOG" not in missing
        else "missing README/CHANGELOG evidence",
    }
    migration = {
        "status": "warn"
        if "config" in changed_areas or "command_surface" in changed_areas
        else "pass",
        "detail": "command/config surface changed; verify migration notes"
        if "config" in changed_areas or "command_surface" in changed_areas
        else "no migration-sensitive surface detected",
    }
    return {
        "correctness": correctness,
        "risk": risk,
        "tests": tests,
        "docs": docs,
        "migration": migration,
    }


def _remediation_hints(sections: dict[str, dict[str, Any]]) -> list[str]:
    hints: list[str] = []
    for name in ("correctness", "risk", "tests", "docs", "migration"):
        section = sections.get(name, {})
        status = str(section.get("status") or "")
        if status == "fail":
            hints.append(f"address {name} blockers before PR merge")
        elif status == "warn":
            hints.append(f"capture explicit {name} evidence in PR summary")
    if not hints:
        hints.append("no remediation required")
    return hints


def command_local(args: list[str]) -> int:
    parsed = _parse_local_args(args)
    if parsed is None:
        return usage()
    payload, code = parsed
    if code != 0:
        as_json = (
            bool(payload.get("json_output")) if isinstance(payload, dict) else False
        )
        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            print(payload.get("reason_code", "review_failed"))
        return code

    report = payload.get("report") if isinstance(payload, dict) else None
    if not isinstance(report, dict):
        failure = {"result": "FAIL", "reason_code": REVIEW_REPORT_INVALID}
        if bool(payload.get("json_output")) if isinstance(payload, dict) else False:
            print(json.dumps(failure, indent=2))
        else:
            print("review report invalid")
        return 1

    sections = _local_sections(report)
    hints = _remediation_hints(sections)
    output = {
        "result": str(report.get("result") or "PASS"),
        "recommendation": report.get("recommendation"),
        "sections": sections,
        "remediation_hints": hints,
        "blocking_reasons": report.get("blocking_reasons", []),
        "findings": report.get("findings", []),
        "summary": report.get("summary", {}),
        "changed_areas": report.get("changed_areas", []),
        "missing_evidence": report.get("missing_evidence", []),
    }
    as_json = bool(payload.get("json_output"))
    if as_json:
        print(json.dumps(output, indent=2))
    else:
        print(f"recommendation: {output.get('recommendation')}")
        for name in ("correctness", "risk", "tests", "docs", "migration"):
            section = sections.get(name, {})
            print(f"- {name}: {section.get('status')} ({section.get('detail')})")
        for hint in hints:
            print(f"- remediation: {hint}")
    return 0 if output.get("result") == "PASS" else 1


def command_doctor(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    as_json = "--json" in args
    analyzer_exists = (SCRIPT_DIR / "pr_review_analyzer.py").exists()
    report = {
        "result": "PASS" if analyzer_exists else "FAIL",
        "analyzer_exists": analyzer_exists,
        "quick_fixes": [
            "/review local --base main --head HEAD --json",
            "/review doctor --json",
        ],
    }
    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print(f"result: {report['result']}")
        print(f"analyzer_exists: {report['analyzer_exists']}")
    return 0 if report["result"] == "PASS" else 1


def command_apply_checklist(args: list[str]) -> int:
    parsed = _parse_local_args(args)
    if parsed is None:
        return usage()
    payload, code = parsed
    if code != 0:
        as_json = (
            bool(payload.get("json_output")) if isinstance(payload, dict) else False
        )
        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            print(payload.get("reason_code", "review_failed"))
        return code

    report = payload.get("report") if isinstance(payload, dict) else None
    if not isinstance(report, dict):
        failure = {"result": "FAIL", "reason_code": REVIEW_REPORT_INVALID}
        if bool(payload.get("json_output")) if isinstance(payload, dict) else False:
            print(json.dumps(failure, indent=2))
        else:
            print("review report invalid")
        return 1

    sections = _local_sections(report)
    as_json = bool(payload.get("json_output")) if isinstance(payload, dict) else False
    checklist_lines = [
        "## Local Review Checklist",
        f"- [{'x' if sections['correctness']['status'] == 'pass' else ' '}] Correctness: {sections['correctness']['detail']}",
        f"- [{'x' if sections['risk']['status'] == 'pass' else ' '}] Risk: {sections['risk']['detail']}",
        f"- [{'x' if sections['tests']['status'] == 'pass' else ' '}] Tests: {sections['tests']['detail']}",
        f"- [{'x' if sections['docs']['status'] == 'pass' else ' '}] Docs: {sections['docs']['detail']}",
        f"- [{'x' if sections['migration']['status'] == 'pass' else ' '}] Migration: {sections['migration']['detail']}",
    ]
    checklist_markdown = "\n".join(checklist_lines)
    output = {
        "result": "PASS",
        "reason_code": REVIEW_CHECKLIST_GENERATED,
        "checklist_markdown": checklist_markdown,
        "sections": sections,
    }
    if as_json:
        print(json.dumps(output, indent=2))
    else:
        print(checklist_markdown)
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        return usage()
    command = argv[0]
    rest = argv[1:]
    if command in {"help", "--help", "-h"}:
        return usage()
    if command == "doctor":
        return command_doctor(rest)
    if command == "local":
        return command_local(rest)
    if command == "apply-checklist":
        return command_apply_checklist(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
