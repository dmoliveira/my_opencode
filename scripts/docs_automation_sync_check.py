#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

REASON_CODE_MAP: dict[str, dict[str, str]] = {
    "docs_automation_workflow_jobs_missing": {
        "severity": "high",
        "hint": "restore sync-wiki and deploy-pages jobs in docs automation workflow",
        "area": "workflow",
        "area_label": "Workflow",
    },
    "docs_automation_pages_path_missing": {
        "severity": "high",
        "hint": "ensure docs/pages artifact path is uploaded by docs automation workflow",
        "area": "workflow",
        "area_label": "Workflow",
    },
    "docs_hub_wiki_link_missing": {
        "severity": "medium",
        "hint": "add repository wiki link to docs/pages/index.html",
        "area": "pages",
        "area_label": "Docs Hub",
    },
    "docs_hub_support_link_missing": {
        "severity": "medium",
        "hint": "add support link to docs/pages/index.html",
        "area": "pages",
        "area_label": "Docs Hub",
    },
    "docs_automation_summary_out_of_sync": {
        "severity": "medium",
        "hint": "regenerate docs automation summary via make docs-automation-summary-update",
        "area": "summary",
        "area_label": "Summary",
    },
}

SEVERITY_RANK = {"unknown": 0, "low": 1, "medium": 2, "high": 3}


def version_key(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def latest_index_version(index_text: str) -> str | None:
    versions = re.findall(r"\|\s*v(0\.4\.\d+)\s*\|", index_text)
    if not versions:
        return None
    return sorted(versions, key=version_key)[-1]


def severity_rank(value: str) -> int:
    return SEVERITY_RANK.get(value, 0)


def _add_finding(
    findings: list[dict[str, Any]],
    remediation: list[str],
    reason_code: str,
    path: Path,
    message: str,
) -> None:
    findings.append(
        {
            "reason_code": reason_code,
            "path": str(path),
            "line": 1,
            "message": message,
        }
    )
    hint = REASON_CODE_MAP.get(reason_code, {}).get("hint")
    if hint and hint not in remediation:
        remediation.append(hint)


def _build_findings_by_reason(
    findings: list[dict[str, Any]], reason_codes: list[str]
) -> dict[str, dict[str, Any]]:
    findings_by_reason: dict[str, dict[str, Any]] = {}
    for reason_code in reason_codes:
        matching = [item for item in findings if item["reason_code"] == reason_code]
        metadata = REASON_CODE_MAP.get(reason_code, {})
        findings_by_reason[reason_code] = {
            "count": len(matching),
            "paths": [str(item["path"]) for item in matching],
            "messages": [str(item["message"]) for item in matching],
            "severity": metadata.get("severity", "unknown"),
            "hint": metadata.get("hint", "inspect checker output"),
            "area": metadata.get("area", "other"),
            "area_label": metadata.get("area_label", "Other"),
        }
    return findings_by_reason


def _build_reason_groups(
    reason_codes: list[str], findings_by_reason: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for reason_code in reason_codes:
        metadata = findings_by_reason[reason_code]
        area = str(metadata.get("area", "other"))
        row = grouped.setdefault(
            area,
            {
                "area": area,
                "area_label": metadata.get("area_label", area.title()),
                "count": 0,
                "reason_codes": [],
                "highest_severity": "unknown",
                "messages": [],
            },
        )
        row["count"] = int(row["count"]) + int(metadata.get("count", 0))
        row["reason_codes"].append(reason_code)
        row["messages"].extend(metadata.get("messages", []))
        current = str(row.get("highest_severity", "unknown"))
        incoming = str(metadata.get("severity", "unknown"))
        if severity_rank(incoming) > severity_rank(current):
            row["highest_severity"] = incoming
    return dict(sorted(grouped.items()))


def collect_docs_automation_status(
    repo_root: Path, summary_text_override: str | None = None
) -> dict[str, Any]:
    workflow_path = repo_root / ".github" / "workflows" / "docs-automation.yml"
    pages_path = repo_root / "docs" / "pages" / "index.html"
    index_path = repo_root / "docs" / "plan" / "v0.4-release-index.md"
    summary_path = repo_root / "docs" / "plan" / "docs-automation-summary.md"

    findings: list[dict[str, Any]] = []
    remediation: list[str] = []

    workflow_text = workflow_path.read_text(encoding="utf-8", errors="replace")
    if "sync-wiki:" not in workflow_text or "deploy-pages:" not in workflow_text:
        _add_finding(
            findings,
            remediation,
            "docs_automation_workflow_jobs_missing",
            workflow_path,
            "docs-automation workflow must define sync-wiki and deploy-pages jobs",
        )

    if "docs/pages" not in workflow_text:
        _add_finding(
            findings,
            remediation,
            "docs_automation_pages_path_missing",
            workflow_path,
            "docs-automation workflow must upload docs/pages as the Pages artifact path",
        )

    pages_text = pages_path.read_text(encoding="utf-8", errors="replace")
    if "github.com/dmoliveira/my_opencode/wiki" not in pages_text:
        _add_finding(
            findings,
            remediation,
            "docs_hub_wiki_link_missing",
            pages_path,
            "docs hub should link to the repository wiki",
        )

    if "buy.stripe.com/8x200i8bSgVe3Vl3g8bfO00" not in pages_text:
        _add_finding(
            findings,
            remediation,
            "docs_hub_support_link_missing",
            pages_path,
            "docs hub should include the support link",
        )

    index_text = index_path.read_text(encoding="utf-8", errors="replace")
    latest = latest_index_version(index_text)
    summary_text = summary_text_override
    if summary_text is None:
        summary_text = summary_path.read_text(encoding="utf-8", errors="replace")
    if latest is None or f"latest_indexed_release: v{latest}" not in summary_text:
        _add_finding(
            findings,
            remediation,
            "docs_automation_summary_out_of_sync",
            summary_path,
            "docs automation summary must reflect the latest indexed release",
        )

    reason_codes = sorted({str(item["reason_code"]) for item in findings})
    findings_by_reason = _build_findings_by_reason(findings, reason_codes)
    reason_groups = _build_reason_groups(reason_codes, findings_by_reason)
    highest_severity = "none"
    if reason_codes:
        highest_severity = max(
            (str(findings_by_reason[code]["severity"]) for code in reason_codes),
            key=severity_rank,
        )
    summary_status = "ok" if not reason_codes else "action_required"
    recommended_next_step = (
        "none"
        if not remediation
        else (
            "run: make docs-automation-summary-update"
            if "docs_automation_summary_out_of_sync" in reason_codes and len(reason_codes) == 1
            else "run: make docs-automation-check"
        )
    )
    quick_fixes = remediation[:3]

    payload = {
        "result": "PASS" if not reason_codes else "FAIL",
        "summary_status": summary_status,
        "highest_severity": highest_severity,
        "reason_codes": reason_codes,
        "reason_code_map": (
            {code: REASON_CODE_MAP.get(code, {"severity": "unknown", "hint": "inspect checker output"}) for code in reason_codes}
            if reason_codes
            else REASON_CODE_MAP
        ),
        "reason_groups": reason_groups,
        "findings_by_reason": findings_by_reason,
        "findings": findings,
        "remediation": remediation,
        "recommended_next_step": recommended_next_step,
        "quick_fixes": quick_fixes,
        "latest_indexed_release": f"v{latest}" if latest is not None else None,
        "summary_path": str(summary_path),
        "workflow_path": str(workflow_path),
        "pages_path": str(pages_path),
        "repo_root": str(repo_root),
    }
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check docs automation workflow/pages/summary synchronization")
    parser.add_argument("--repo-root", type=Path, help="Override repository root for testing")
    parser.add_argument("--json", action="store_true", help="Emit JSON output (default)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = (args.repo_root or Path(__file__).resolve().parent.parent).resolve()
    payload = collect_docs_automation_status(repo_root)
    print(json.dumps(payload, indent=2))
    return 0 if payload["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
