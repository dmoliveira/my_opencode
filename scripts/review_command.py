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
from reviewer_policy import (  # type: ignore
    diagnose_reviewer_policy,
    env_reviewer_values,
    parse_reviewer_flags,
    resolve_reviewer_policy,
)


def usage() -> int:
    print(
        "usage: /review local [--base <ref>] [--head <ref>] [--diff-file <path>] [--json] | "
        "/review apply-checklist [--base <ref>] [--head <ref>] [--diff-file <path>] [--write <path>] [--include-findings] [--json] | "
        "/review doctor [--allow-reviewer <login> ...] [--deny-reviewer <login> ...] [--json]"
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
    as_json = "--json" in args
    args = [arg for arg in args if arg != "--json"]
    allow_cli = parse_reviewer_flags(args, "--allow-reviewer")
    deny_cli = parse_reviewer_flags(args, "--deny-reviewer")
    if args:
        return usage()

    allow_env = env_reviewer_values("MY_OPENCODE_SHIP_REVIEWER_ALLOW")
    deny_env = env_reviewer_values("MY_OPENCODE_SHIP_REVIEWER_DENY")
    allow_reviewers, deny_reviewers, source = resolve_reviewer_policy(
        allow_cli,
        deny_cli,
        allow_env,
        deny_env,
    )
    policy_diagnostics = diagnose_reviewer_policy(
        allow_list=allow_reviewers,
        deny_list=deny_reviewers,
        source=source,
    )

    analyzer_exists = (SCRIPT_DIR / "pr_review_analyzer.py").exists()
    warnings_any = policy_diagnostics.get("warnings", [])
    warnings = warnings_any if isinstance(warnings_any, list) else []
    quick_fixes = [
        "/review local --base main --head HEAD --json",
        "/review doctor --json",
    ]
    if warnings:
        quick_fixes.append(
            "remove overlap between --allow-reviewer and --deny-reviewer (deny wins on conflicts)"
        )

    report = {
        "result": "PASS" if analyzer_exists else "FAIL",
        "analyzer_exists": analyzer_exists,
        "policy_diagnostics": policy_diagnostics,
        "warnings": warnings,
        "quick_fixes": quick_fixes,
    }
    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print(f"result: {report['result']}")
        print(f"analyzer_exists: {report['analyzer_exists']}")
    return 0 if report["result"] == "PASS" else 1


def command_apply_checklist(args: list[str]) -> int:
    write_path: Path | None = None
    include_findings = False
    filtered_args: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--write":
            if index + 1 >= len(args):
                return usage()
            write_path = Path(args[index + 1]).expanduser()
            index += 2
            continue
        if token == "--include-findings":
            include_findings = True
            index += 1
            continue
        filtered_args.append(token)
        index += 1

    parsed = _parse_local_args(filtered_args)
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
    finding_summaries: list[str] = []
    if include_findings:
        findings_any = report.get("findings", [])
        findings = findings_any if isinstance(findings_any, list) else []
        if findings:
            checklist_lines.extend(["", "## Findings"])
            for finding in findings[:8]:
                if not isinstance(finding, dict):
                    continue
                severity = str(finding.get("severity") or "info")
                area = str(finding.get("area") or "general")
                message = str(finding.get("message") or "")
                if message:
                    line = f"- [{severity}] {area}: {message}"
                    checklist_lines.append(line)
                    finding_summaries.append(line)
    checklist_markdown = "\n".join(checklist_lines)
    if write_path is not None:
        write_path.parent.mkdir(parents=True, exist_ok=True)
        write_path.write_text(checklist_markdown + "\n", encoding="utf-8")
    output = {
        "result": "PASS",
        "reason_code": REVIEW_CHECKLIST_GENERATED,
        "checklist_markdown": checklist_markdown,
        "sections": sections,
        "include_findings": include_findings,
        "finding_summaries": finding_summaries,
        "written_path": str(write_path.resolve()) if write_path is not None else None,
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
