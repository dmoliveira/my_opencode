#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from pathlib import Path

from docs_automation_sync_check import collect_docs_automation_status

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


def format_reason_groups(reason_groups: dict[str, dict[str, object]]) -> str:
    if not reason_groups:
        return "none"
    parts: list[str] = []
    for group in reason_groups.values():
        label = str(group.get("area_label", group.get("area", "other"))).strip().lower()
        count = int(group.get("count", 0))
        severity = str(group.get("highest_severity", "unknown"))
        parts.append(f"{label}({count}, {severity})")
    return ", ".join(parts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Regenerate docs automation summary artifact")
    parser.add_argument("--repo-root", type=Path, help="Override repository root for testing")
    return parser.parse_args()


def render_summary(
    generated_at: str,
    latest: str,
    versions: list[str],
    covered_targets: int,
    target_signals: dict[str, bool],
    status: dict[str, object],
) -> str:
    quick_fixes = [str(item) for item in status.get("quick_fixes", [])]
    lines = [
        "# Docs Automation Summary",
        "",
        "Generated artifact that tracks docs-automation publication coverage.",
        "",
        "## Remediation Summary",
        f"- result: {status['result']}",
        f"- summary_status: {status['summary_status']}",
        f"- highest_severity: {status['highest_severity']}",
        f"- issue_count: {len(status['reason_codes'])}",
        f"- reason_groups: {format_reason_groups(status['reason_groups'])}",
        f"- recommended_next_step: {status['recommended_next_step']}",
    ]
    if quick_fixes:
        lines.append("")
        lines.append("## Suggested Fixes")
        for item in quick_fixes:
            lines.append(f"- {item}")
    lines.extend(
        [
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
    )
    for version in sorted(versions, key=version_key)[-5:]:
        lines.append(f"- v{version}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    repo_root = (args.repo_root or Path(__file__).resolve().parent.parent).resolve()
    plan_dir = repo_root / "docs" / "plan"
    index_path = plan_dir / "v0.4-release-index.md"
    summary_path = plan_dir / "docs-automation-summary.md"
    workflow_path = repo_root / ".github" / "workflows" / "docs-automation.yml"

    index_text = index_path.read_text(encoding="utf-8", errors="replace")
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

    initial_status = collect_docs_automation_status(repo_root)
    provisional_summary = render_summary(
        generated_at,
        latest,
        versions,
        covered_targets,
        target_signals,
        initial_status,
    )
    final_status = collect_docs_automation_status(
        repo_root,
        summary_text_override=provisional_summary,
    )
    final_summary = render_summary(
        generated_at,
        latest,
        versions,
        covered_targets,
        target_signals,
        final_status,
    )

    summary_path.write_text(final_summary, encoding="utf-8")
    print(f"updated: {summary_path}")
    print(f"generated_at_utc: {generated_at}")
    print(f"indexed_release_count: {len(versions)}")
    print(f"latest_indexed_release: v{latest}")
    print(f"publication_target_coverage: {covered_targets}/3")
    print(f"summary_status: {final_status['summary_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
