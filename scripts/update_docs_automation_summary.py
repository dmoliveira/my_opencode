#!/usr/bin/env python3

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path


ROW_RE = re.compile(r"^\|\s*v(0\.4\.\d+)\s*\|")


def parse_versions(index_text: str) -> list[str]:
    versions: list[str] = []
    for line in index_text.splitlines():
        match = ROW_RE.match(line.strip())
        if match:
            versions.append(match.group(1))
    return versions


def version_key(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    plan_dir = repo_root / "docs" / "plan"
    index_path = plan_dir / "v0.4-release-index.md"
    summary_path = plan_dir / "docs-automation-summary.md"
    workflow_path = repo_root / ".github" / "workflows" / "docs-automation.yml"

    index_text = index_path.read_text(encoding="utf-8")
    workflow_text = workflow_path.read_text(encoding="utf-8", errors="replace")
    versions = parse_versions(index_text)
    latest = sorted(versions, key=version_key)[-1] if versions else "none"
    target_signals = {
        "wiki_sync_job": "sync-wiki:" in workflow_text,
        "pages_deploy_job": "deploy-pages:" in workflow_text,
        "pages_artifact_path": "docs/pages" in workflow_text,
    }
    covered_targets = sum(1 for value in target_signals.values() if value)
    generated_at = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = [
        "# Docs Automation Summary",
        "",
        "Generated artifact that tracks docs-automation publication coverage.",
        "",
        f"- generated_at_utc: {generated_at}",
        f"- indexed_release_count: {len(versions)}",
        f"- latest_indexed_release: v{latest}",
        f"- publication_target_coverage: {covered_targets}/3",
        f"- target_wiki_sync_job: {'ok' if target_signals['wiki_sync_job'] else 'missing'}",
        f"- target_pages_deploy_job: {'ok' if target_signals['pages_deploy_job'] else 'missing'}",
        f"- target_pages_artifact_path: {'ok' if target_signals['pages_artifact_path'] else 'missing'}",
        "- index_source: docs/plan/v0.4-release-index.md",
        "- workflow_source: .github/workflows/docs-automation.yml",
        "",
        "## Latest Indexed Releases",
    ]
    for version in sorted(versions, key=version_key)[-5:]:
        lines.append(f"- v{version}")
    lines.append("")

    summary_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"updated: {summary_path}")
    print(f"generated_at_utc: {generated_at}")
    print(f"indexed_release_count: {len(versions)}")
    print(f"latest_indexed_release: v{latest}")
    print(f"publication_target_coverage: {covered_targets}/3")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
