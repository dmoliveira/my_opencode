#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


PLAN_NAME_RE = re.compile(r"^(v\d+\.\d+)-flow-wave-plan\.md$")
EPIC_HEADING_RE = re.compile(r"^###\s+E\d+\s+(.+)$")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate wave completion docs from merged PR metadata"
    )
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--wave", required=True, help="Wave version like v2.2")
    parser.add_argument("--plan", default=None, help="Override plan file path")
    parser.add_argument(
        "--output", default=None, help="Override output completion file path"
    )
    parser.add_argument("--pr", action="append", default=[])
    parser.add_argument(
        "--pr-metadata-file",
        default=None,
        help="JSON array metadata to avoid live gh queries",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def wave_paths(
    repo_root: Path, wave: str, plan_override: str | None, output_override: str | None
) -> tuple[Path, Path]:
    plan_path = (
        Path(plan_override).resolve()
        if plan_override
        else repo_root / "docs" / "plan" / f"{wave}-flow-wave-plan.md"
    )
    output_path = (
        Path(output_override).resolve()
        if output_override
        else repo_root / "docs" / "plan" / f"{wave}-flow-wave-completion.md"
    )
    return plan_path, output_path


def load_pr_metadata_from_file(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("--pr-metadata-file must contain a JSON array")
    parsed: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("--pr-metadata-file array entries must be objects")
        parsed.append(item)
    return parsed


def gh_pr_metadata(pr_number: int, repo_root: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--json",
            "number,title,mergedAt,mergeCommit,url",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo_root,
    )
    if completed.returncode != 0:
        detail = (
            completed.stderr.strip() or completed.stdout.strip() or "gh pr view failed"
        )
        raise RuntimeError(f"unable to fetch PR #{pr_number}: {detail}")
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError(f"unexpected gh payload for PR #{pr_number}")
    return payload


def normalize_pr_row(item: dict[str, Any]) -> dict[str, str]:
    merge_commit = item.get("mergeCommit")
    oid = (
        str(merge_commit.get("oid"))
        if isinstance(merge_commit, dict) and merge_commit.get("oid")
        else ""
    )
    number = str(item.get("number", "")).strip()
    title = str(item.get("title", "")).strip()
    merged_at = str(item.get("mergedAt", "")).strip()
    url = str(item.get("url", "")).strip()
    if not number or not title or not merged_at or not url or not oid:
        raise ValueError(
            "PR metadata missing one of number/title/mergedAt/url/mergeCommit.oid"
        )
    return {
        "number": number,
        "title": title,
        "merged_at": merged_at,
        "url": url,
        "merge_commit": oid,
    }


def plan_scope_lines(plan_text: str) -> list[str]:
    scopes: list[str] = []
    for raw in plan_text.splitlines():
        match = EPIC_HEADING_RE.match(raw.strip())
        if not match:
            continue
        scopes.append(f"- {match.group(1).strip()}")
    return scopes


def build_markdown(
    wave: str, scope_lines: list[str], rows: list[dict[str, str]]
) -> str:
    lines = [
        f"# {wave} Flow Wave Completion",
        "",
        f"This document records closure evidence for the {wave} flow wave.",
        "",
        "## Scope Closed",
        "",
        *(scope_lines or ["- <populate from wave epics>"]),
        "",
        "## Included PRs",
        "",
        "| PR | Title | Merged At (UTC) | Merge Commit |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| [#{row['number']}]({row['url']}) | {row['title']} | {row['merged_at']} | `{row['merge_commit']}` |"
        )
    if not rows:
        lines.append("| <none> | <populate merged PRs> | <utc> | `<sha>` |")
    lines.extend(
        [
            "",
            "## Validation Baseline",
            "",
            "- `make validate`",
            "- `make selftest`",
            "- `make install-test`",
            "- `npm --prefix plugin/gateway-core run lint`",
            "- `pre-commit run --all-files`",
            "",
            f"{wave} closure criterion: all epic checklist items in `docs/plan/{wave}-flow-wave-plan.md` are marked done.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = (
        Path(args.repo_root).resolve()
        if args.repo_root
        else Path(__file__).resolve().parent.parent
    )
    plan_path, output_path = wave_paths(repo_root, args.wave, args.plan, args.output)
    if not plan_path.exists():
        print(f"plan file missing: {plan_path}", file=sys.stderr)
        return 2

    plan_name = plan_path.name
    if not PLAN_NAME_RE.match(plan_name):
        print(f"unexpected plan filename: {plan_name}", file=sys.stderr)
        return 2

    plan_text = plan_path.read_text(encoding="utf-8", errors="replace")
    scope_lines = plan_scope_lines(plan_text)

    if args.pr_metadata_file:
        source_items = load_pr_metadata_from_file(Path(args.pr_metadata_file).resolve())
    else:
        pr_values: list[int] = []
        for raw in args.pr:
            value = str(raw).strip()
            if not value:
                continue
            pr_values.append(int(value))
        source_items = [gh_pr_metadata(number, repo_root) for number in pr_values]

    rows = [normalize_pr_row(item) for item in source_items]
    markdown = build_markdown(args.wave, scope_lines, rows)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    payload = {
        "result": "PASS",
        "wave": args.wave,
        "plan_path": str(plan_path),
        "output_path": str(output_path),
        "scope_count": len(scope_lines),
        "pr_count": len(rows),
        "reason_codes": ["wave_completion_doc_generated"],
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"generated: {output_path}")
        print(f"scope_count: {len(scope_lines)}")
        print(f"pr_count: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
