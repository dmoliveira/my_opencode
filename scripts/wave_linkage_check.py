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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Checks wave plan/completion doc linkage"
    )
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def wave_major(wave: str) -> int:
    try:
        return int(wave.lstrip("v").split(".", 1)[0])
    except ValueError:
        return 0


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

    findings: list[dict[str, str | int]] = []
    for wave, completion_path in completions.items():
        if wave_major(wave) < 2:
            continue
        plan_path = plans.get(wave)
        if plan_path is None:
            findings.append(
                {
                    "reason_code": "wave_plan_missing_for_completion",
                    "path": str(completion_path),
                    "line": 1,
                    "message": f"completion doc exists but matching plan is missing for {wave}",
                }
            )
            continue
        completion_text = completion_path.read_text(encoding="utf-8", errors="replace")
        plan_name = plan_path.name
        if plan_name not in completion_text:
            findings.append(
                {
                    "reason_code": "wave_completion_missing_plan_reference",
                    "path": str(completion_path),
                    "line": 1,
                    "message": f"completion doc should reference {plan_name}",
                }
            )

    for wave, plan_path in plans.items():
        if wave_major(wave) < 2:
            continue
        plan_text = plan_path.read_text(encoding="utf-8", errors="replace")
        if not plan_complete(plan_text):
            continue
        if wave not in completions:
            findings.append(
                {
                    "reason_code": "wave_completion_missing_for_completed_plan",
                    "path": str(plan_path),
                    "line": 1,
                    "message": f"completed wave plan is missing completion doc for {wave}",
                }
            )

    payload = {
        "result": "PASS" if not findings else "FAIL",
        "reason_codes": sorted({str(item["reason_code"]) for item in findings}),
        "findings": findings,
        "plan_count": len(plans),
        "completion_count": len(completions),
        "quick_fixes": [
            "add missing wave completion docs for completed plans",
            "ensure completion docs reference matching plan filenames",
            "python3 scripts/wave_linkage_check.py --json",
        ],
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"result: {payload['result']}")
        print(f"plan_count: {payload['plan_count']}")
        print(f"completion_count: {payload['completion_count']}")
        for finding in findings:
            print(
                f"- {finding['reason_code']} {finding['path']}:{finding['line']} {finding['message']}"
            )
    return 0 if payload["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
