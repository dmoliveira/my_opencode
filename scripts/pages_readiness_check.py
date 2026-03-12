#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent

REASON_CODE_MAP: dict[str, dict[str, str]] = {
    "github_pages_site_uninitialized": {
        "severity": "high",
        "hint": "run: gh api -X POST repos/<owner>/<repo>/pages -f build_type=workflow",
    },
    "github_pages_api_unavailable": {
        "severity": "medium",
        "hint": "verify gh auth, repo access, and GitHub API availability",
    },
    "github_pages_build_type_mismatch": {
        "severity": "medium",
        "hint": "switch the Pages site to workflow publishing in repository settings or via gh api",
    },
    "docs_automation_workflow_pages_missing": {
        "severity": "high",
        "hint": "restore GitHub Pages deployment steps in .github/workflows/docs-automation.yml",
    },
}


def workflow_has_pages_support(repo_root: Path) -> bool:
    workflow_path = repo_root / ".github" / "workflows" / "docs-automation.yml"
    text = workflow_path.read_text(encoding="utf-8", errors="replace")
    return (
        "actions/configure-pages@" in text
        and "actions/deploy-pages@" in text
        and "docs/pages" in text
    )


def resolve_repo_name(repo_root: Path) -> str:
    proc = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner"],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo_root,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            proc.stderr.strip() or proc.stdout.strip() or "gh repo view failed"
        )
    payload = json.loads(proc.stdout)
    repo = str(payload.get("nameWithOwner") or "").strip()
    if not repo:
        raise RuntimeError("gh repo view returned empty nameWithOwner")
    return repo


def fetch_pages_payload(
    repo_root: Path, repo: str
) -> tuple[dict[str, Any] | None, str | None, int | None]:
    proc = subprocess.run(
        ["gh", "api", f"repos/{repo}/pages"],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo_root,
    )
    if proc.returncode == 0:
        return json.loads(proc.stdout), None, None
    detail = (
        proc.stderr.strip() or proc.stdout.strip() or "gh api repos/<repo>/pages failed"
    )
    status = 404 if "HTTP 404" in detail or "Not Found" in detail else None
    return None, detail, status


def evaluate_pages_readiness(
    *,
    repo_root: Path,
    repo: str,
    pages_payload: dict[str, Any] | None,
    fetch_error: str | None,
    fetch_status: int | None,
) -> dict[str, Any]:
    workflow_ready = workflow_has_pages_support(repo_root)
    reason_codes: list[str] = []
    remediation: list[str] = []

    if not workflow_ready:
        reason_codes.append("docs_automation_workflow_pages_missing")
    if fetch_status == 404:
        reason_codes.append("github_pages_site_uninitialized")
    elif pages_payload is None:
        reason_codes.append("github_pages_api_unavailable")
    elif str(pages_payload.get("build_type") or "") != "workflow":
        reason_codes.append("github_pages_build_type_mismatch")

    for code in reason_codes:
        hint = REASON_CODE_MAP[code]["hint"]
        if code == "github_pages_site_uninitialized":
            hint = hint.replace("<owner>/<repo>", repo)
        if hint not in remediation:
            remediation.append(hint)

    return {
        "result": "PASS" if not reason_codes else "FAIL",
        "repo": repo,
        "workflow_ready": workflow_ready,
        "workflow_path": str(
            repo_root / ".github" / "workflows" / "docs-automation.yml"
        ),
        "reason_codes": reason_codes,
        "reason_code_map": REASON_CODE_MAP,
        "remediation": remediation,
        "pages_url": None if pages_payload is None else pages_payload.get("html_url"),
        "build_type": None
        if pages_payload is None
        else pages_payload.get("build_type"),
        "api_error": fetch_error,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check whether GitHub Pages is initialized and ready for docs automation"
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--repo", default=None, help="Override owner/name for gh api lookups"
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    try:
        repo = args.repo or resolve_repo_name(repo_root)
        pages_payload, fetch_error, fetch_status = fetch_pages_payload(repo_root, repo)
        payload = evaluate_pages_readiness(
            repo_root=repo_root,
            repo=repo,
            pages_payload=pages_payload,
            fetch_error=fetch_error,
            fetch_status=fetch_status,
        )
    except Exception as exc:
        payload = {
            "result": "FAIL",
            "repo": args.repo,
            "workflow_ready": workflow_has_pages_support(repo_root),
            "workflow_path": str(
                repo_root / ".github" / "workflows" / "docs-automation.yml"
            ),
            "reason_codes": ["github_pages_api_unavailable"],
            "reason_code_map": REASON_CODE_MAP,
            "remediation": [REASON_CODE_MAP["github_pages_api_unavailable"]["hint"]],
            "pages_url": None,
            "build_type": None,
            "api_error": str(exc),
        }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
    return 0 if payload["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
