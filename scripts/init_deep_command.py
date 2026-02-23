#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path


SKIP_DIRS = {
    ".git",
    ".opencode",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    ".venv",
    "venv",
}


def usage() -> int:
    print("usage: /init-deep [--max-depth <n>] [--create-new] [--json]")
    return 2


def has_code_content(directory: Path) -> bool:
    patterns = ["*.py", "*.ts", "*.tsx", "*.js", "*.jsx", "*.rs", "*.go", "*.java"]
    for pattern in patterns:
        if any(directory.glob(pattern)):
            return True
    return False


def iter_directories(root: Path, max_depth: int) -> list[Path]:
    result = [root]
    queue: list[tuple[Path, int]] = [(root, 0)]
    while queue:
        current, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        try:
            children = sorted(current.iterdir())
        except PermissionError:
            continue
        for child in children:
            if not child.is_dir():
                continue
            if child.name in SKIP_DIRS or child.name.startswith("."):
                continue
            queue.append((child, depth + 1))
            if has_code_content(child):
                result.append(child)
    return result


def render_template(root: Path, directory: Path) -> str:
    rel = directory.relative_to(root)
    scope = "." if str(rel) == "." else str(rel)
    return (
        "# AGENTS\n\n"
        f"Scope: `{scope}`\n\n"
        "## Working Agreement\n"
        "- Follow existing conventions in this scope first.\n"
        "- Keep changes minimal and validated before handoff.\n"
        "- Prefer canonical slash commands and avoid legacy aliases.\n\n"
        "## Local Notes\n"
        "- Add module-specific constraints and gotchas here.\n"
    )


def main(argv: list[str]) -> int:
    as_json = False
    create_new = False
    max_depth = 2

    idx = 0
    while idx < len(argv):
        token = argv[idx]
        if token == "--json":
            as_json = True
            idx += 1
            continue
        if token == "--create-new":
            create_new = True
            idx += 1
            continue
        if token == "--max-depth":
            if idx + 1 >= len(argv):
                return usage()
            try:
                max_depth = max(0, int(argv[idx + 1]))
            except ValueError:
                return usage()
            idx += 2
            continue
        if token in {"help", "-h", "--help"}:
            return usage()
        return usage()

    root = Path.cwd()
    created: list[str] = []
    skipped_existing: list[str] = []

    for directory in iter_directories(root, max_depth):
        agents_path = directory / "AGENTS.md"
        if agents_path.exists() and not create_new:
            skipped_existing.append(str(agents_path.relative_to(root)))
            continue
        agents_path.write_text(render_template(root, directory), encoding="utf-8")
        created.append(str(agents_path.relative_to(root)))

    payload = {
        "result": "PASS",
        "root": str(root),
        "max_depth": max_depth,
        "create_new": create_new,
        "created_count": len(created),
        "created": created,
        "skipped_existing_count": len(skipped_existing),
        "skipped_existing": skipped_existing,
        "quick_fixes": [
            "/session handoff --json",
            "/doctor run",
        ],
    }

    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"result: {payload['result']}")
        print(f"created_count: {payload['created_count']}")
        for item in created:
            print(f"- created: {item}")
        if skipped_existing:
            print(f"skipped_existing_count: {len(skipped_existing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
