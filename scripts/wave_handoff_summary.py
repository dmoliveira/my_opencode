#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


WAVE_PLAN_RE = re.compile(r"^(v\d+\.\d+)-.*plan\.md$")
WAVE_COMPLETION_RE = re.compile(r"^(v\d+\.\d+)-flow-wave-completion\.md$")


def plan_complete(text: str) -> bool:
    has_done = bool(re.search(r"^\s*- \[[xX]\]", text, flags=re.MULTILINE))
    has_pending = bool(re.search(r"^\s*- \[ \]", text, flags=re.MULTILINE))
    return has_done and not has_pending


def wave_version(wave: str) -> tuple[int, int]:
    try:
        major_raw, minor_raw = wave.lstrip("v").split(".", 1)
        return int(major_raw), int(minor_raw)
    except ValueError:
        return (0, 0)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize wave transition handoff state"
    )
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = (
        Path(args.repo_root).resolve()
        if args.repo_root
        else Path(__file__).resolve().parent.parent
    )
    plan_dir = repo_root / "docs" / "plan"

    plans: dict[str, Path] = {}
    completions: dict[str, Path] = {}
    for path in sorted(plan_dir.glob("v*.md")):
        plan_match = WAVE_PLAN_RE.match(path.name)
        if plan_match:
            plans[plan_match.group(1)] = path
            continue
        completion_match = WAVE_COMPLETION_RE.match(path.name)
        if completion_match:
            completions[completion_match.group(1)] = path

    active_waves: list[str] = []
    completed_waves: list[str] = []
    for wave, plan_path in plans.items():
        if int(wave.lstrip("v").split(".", 1)[0]) < 2:
            continue
        text = plan_path.read_text(encoding="utf-8", errors="replace")
        if plan_complete(text):
            completed_waves.append(wave)
        else:
            active_waves.append(wave)

    active_waves = sorted(active_waves, key=wave_version)
    completed_waves = sorted(completed_waves, key=wave_version)
    latest_active = active_waves[-1] if active_waves else None
    latest_completed = completed_waves[-1] if completed_waves else None
    next_actions: list[str] = []
    if latest_completed and latest_completed not in completions:
        next_actions.append(
            f"python3 scripts/update_wave_completion_doc.py --wave {latest_completed} --pr <number>"
        )
    if latest_completed and latest_active is None:
        major, minor = wave_version(latest_completed)
        next_actions.append(
            f"scaffold docs/plan/v{major}.{minor + 1}-flow-wave-plan.md"
        )
    if latest_active:
        next_actions.append(
            f"continue execution from docs/plan/{latest_active}-flow-wave-plan.md"
        )
    if not next_actions:
        next_actions.append("no immediate wave handoff action")

    payload = {
        "result": "PASS",
        "active_waves": active_waves,
        "completed_waves": completed_waves,
        "latest_active_wave": latest_active,
        "latest_completed_wave": latest_completed,
        "completion_docs_present": sorted(completions),
        "next_actions": next_actions,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"latest_active_wave: {latest_active}")
        print(f"latest_completed_wave: {latest_completed}")
        for action in next_actions:
            print(f"- {action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
