#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
from pathlib import Path


RELEASE_NOTES_RE = re.compile(r"^release-notes-\d{4}-\d{2}-\d{2}-v0-4-(\d+)\.md$")
MILESTONE_RE = re.compile(r"^v0\.4\.(\d+)-flow-milestones-changelog\.md$")

LEGACY_FALLBACKS: dict[str, tuple[str, str]] = {
    "0.4.1": (
        "docs/plan/v0.4.0-flow-milestones-changelog.md",
        "docs/plan/release-notes-2026-02-24-v0-4-0.md",
    ),
}


def _version_key(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def _collect_files(plan_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    milestones: dict[str, str] = {}
    notes: dict[str, str] = {}

    for path in plan_dir.glob("v0.4.*-flow-milestones-changelog.md"):
        match = MILESTONE_RE.match(path.name)
        if not match:
            continue
        patch = match.group(1)
        version = f"0.4.{patch}"
        milestones[version] = f"docs/plan/{path.name}"

    for path in plan_dir.glob("release-notes-*-v0-4-*.md"):
        match = RELEASE_NOTES_RE.match(path.name)
        if not match:
            continue
        patch = match.group(1)
        version = f"0.4.{patch}"
        notes[version] = f"docs/plan/{path.name}"

    return milestones, notes


def _build_index(milestones: dict[str, str], notes: dict[str, str]) -> str:
    versions = sorted(
        set(milestones) | set(notes) | set(LEGACY_FALLBACKS), key=_version_key
    )
    lines = [
        "# v0.4.x Release Index",
        "",
        "This index links each v0.4.x milestone changelog and release-note draft for quick operator lookup.",
        "",
        "| Release | Milestone Changelog | Release Notes |",
        "| --- | --- | --- |",
    ]
    for version in versions:
        fallback = LEGACY_FALLBACKS.get(version, ("(missing)", "(missing)"))
        milestone = milestones.get(version, fallback[0])
        note = notes.get(version, fallback[1])
        lines.append(f"| v{version} | `{milestone}` | `{note}` |")

    lines.extend(
        [
            "",
            "Use this file as the canonical jump table when preparing the next milestone rollup or auditing release evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Regenerate the v0.4 release index")
    parser.add_argument("--repo-root", type=Path, help="Override repository root for testing")
    return parser.parse_args(argv)


def _resolve_repo_root(override: Path | None) -> Path:
    repo_root = (override or Path(__file__).resolve().parent.parent).resolve()
    plan_dir = (repo_root / "docs" / "plan").resolve()
    if not repo_root.is_dir() or not plan_dir.is_dir() or not plan_dir.is_relative_to(repo_root):
        raise SystemExit("--repo-root must contain a repository-scoped docs/plan directory")
    return repo_root


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = _resolve_repo_root(args.repo_root)
    plan_dir = repo_root / "docs" / "plan"
    output = plan_dir / "v0.4-release-index.md"

    milestones, notes = _collect_files(plan_dir)
    content = _build_index(milestones, notes)
    output.write_text(content, encoding="utf-8")
    print(f"updated: {output}")
    print(f"entries: {len(set(milestones) | set(notes))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
