#!/usr/bin/env python3

from __future__ import annotations

import json
import re
from pathlib import Path


REASON_CODE_MAP: dict[str, dict[str, str]] = {
    "docs_automation_workflow_jobs_missing": {
        "severity": "high",
        "hint": "restore sync-wiki and deploy-pages jobs in docs automation workflow",
    },
    "docs_automation_pages_path_missing": {
        "severity": "high",
        "hint": "ensure docs/pages artifact path is uploaded by docs automation workflow",
    },
    "docs_hub_wiki_link_missing": {
        "severity": "medium",
        "hint": "add repository wiki link to docs/pages/index.html",
    },
    "docs_hub_support_link_missing": {
        "severity": "medium",
        "hint": "add support link to docs/pages/index.html",
    },
    "docs_automation_summary_out_of_sync": {
        "severity": "medium",
        "hint": "regenerate docs automation summary via make docs-automation-summary-update",
    },
}


def version_key(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def latest_index_version(index_text: str) -> str | None:
    versions = re.findall(r"\|\s*v(0\.4\.\d+)\s*\|", index_text)
    if not versions:
        return None
    return sorted(versions, key=version_key)[-1]


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    workflow_path = repo_root / ".github" / "workflows" / "docs-automation.yml"
    pages_path = repo_root / "docs" / "pages" / "index.html"
    index_path = repo_root / "docs" / "plan" / "v0.4-release-index.md"
    summary_path = repo_root / "docs" / "plan" / "docs-automation-summary.md"

    reason_codes: list[str] = []
    remediation: list[str] = []

    workflow_text = workflow_path.read_text(encoding="utf-8", errors="replace")
    if "sync-wiki:" not in workflow_text or "deploy-pages:" not in workflow_text:
        reason_codes.append("docs_automation_workflow_jobs_missing")
        remediation.append(
            "ensure docs-automation workflow defines sync-wiki and deploy-pages jobs"
        )

    if "docs/pages" not in workflow_text:
        reason_codes.append("docs_automation_pages_path_missing")
        remediation.append(
            "ensure docs-automation workflow uploads docs/pages artifact"
        )

    pages_text = pages_path.read_text(encoding="utf-8", errors="replace")
    if "github.com/dmoliveira/my_opencode/wiki" not in pages_text:
        reason_codes.append("docs_hub_wiki_link_missing")
        remediation.append("ensure docs/pages/index.html links to the repository wiki")

    if "buy.stripe.com/8x200i8bSgVe3Vl3g8bfO00" not in pages_text:
        reason_codes.append("docs_hub_support_link_missing")
        remediation.append("ensure docs/pages/index.html includes support link")

    index_text = index_path.read_text(encoding="utf-8", errors="replace")
    latest = latest_index_version(index_text)
    summary_text = summary_path.read_text(encoding="utf-8", errors="replace")
    if latest is None or f"latest_indexed_release: v{latest}" not in summary_text:
        reason_codes.append("docs_automation_summary_out_of_sync")
        remediation.append("run: make docs-automation-summary-update")

    payload = {
        "result": "PASS" if not reason_codes else "FAIL",
        "reason_codes": reason_codes,
        "reason_code_map": {
            code: REASON_CODE_MAP.get(
                code,
                {"severity": "unknown", "hint": "inspect checker output"},
            )
            for code in reason_codes
        }
        if reason_codes
        else REASON_CODE_MAP,
        "remediation": remediation,
        "latest_indexed_release": f"v{latest}" if latest is not None else None,
        "summary_path": str(summary_path),
    }
    print(json.dumps(payload, indent=2))
    return 0 if payload["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
