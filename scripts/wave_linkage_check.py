#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


WAVE_PLAN_RE = re.compile(r"^(v\d+\.\d+)-.*plan\.md$")
WAVE_COMPLETION_RE = re.compile(r"^(v\d+\.\d+)-flow-wave-completion\.md$")
REASON_CODE_MAP: dict[str, dict[str, str]] = {
    "wave_plan_missing_for_completion": {
        "severity": "high",
        "hint": "restore or add matching wave plan file for completion artifact",
    },
    "wave_completion_missing_plan_reference": {
        "severity": "medium",
        "hint": "add matching plan filename reference in completion doc closure criterion",
    },
    "wave_completion_missing_for_completed_plan": {
        "severity": "high",
        "hint": "generate and commit wave completion artifact for completed plan",
    },
    "wave_multiple_active_plans_detected": {
        "severity": "medium",
        "hint": "close current active wave before marking a second wave plan as active",
    },
}


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


def wave_version(wave: str) -> tuple[int, int]:
    try:
        major_raw, minor_raw = wave.lstrip("v").split(".", 1)
        return int(major_raw), int(minor_raw)
    except ValueError:
        return (0, 0)


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
    active_plans: list[str] = []
    completed_plans: list[str] = []
    eligible_waves = sorted(
        (wave for wave in plans if wave_major(wave) >= 2), key=wave_version
    )
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
            active_plans.append(wave)
            continue
        completed_plans.append(wave)
        if wave not in completions:
            findings.append(
                {
                    "reason_code": "wave_completion_missing_for_completed_plan",
                    "path": str(plan_path),
                    "line": 1,
                    "message": f"completed wave plan is missing completion doc for {wave}",
                }
            )

    if len(active_plans) > 1:
        findings.append(
            {
                "reason_code": "wave_multiple_active_plans_detected",
                "path": str(plan_dir),
                "line": 1,
                "message": f"multiple active wave plans detected: {', '.join(sorted(active_plans, key=wave_version))}",
            }
        )

    reason_codes = sorted({str(item["reason_code"]) for item in findings})
    findings_by_reason: dict[str, dict[str, object]] = {}
    for reason_code in reason_codes:
        matching = [item for item in findings if item["reason_code"] == reason_code]
        findings_by_reason[reason_code] = {
            "count": len(matching),
            "paths": [str(item["path"]) for item in matching],
            "messages": [str(item["message"]) for item in matching],
            "severity": REASON_CODE_MAP.get(reason_code, {}).get("severity", "unknown"),
            "hint": REASON_CODE_MAP.get(reason_code, {}).get(
                "hint", "inspect findings"
            ),
        }

    latest_completed_wave = (
        max(completed_plans, key=wave_version) if completed_plans else None
    )
    latest_active_wave = max(active_plans, key=wave_version) if active_plans else None
    transition_status = "stable"
    if len(active_plans) > 1:
        transition_status = "conflict"
    elif latest_completed_wave and not latest_active_wave:
        transition_status = "handoff_recommended"
    elif latest_completed_wave and latest_active_wave:
        transition_status = "active"

    transition = {
        "status": transition_status,
        "latest_completed_wave": latest_completed_wave,
        "latest_active_wave": latest_active_wave,
        "active_wave_count": len(active_plans),
        "completed_wave_count": len(completed_plans),
    }

    payload = {
        "result": "PASS" if not findings else "FAIL",
        "reason_codes": reason_codes,
        "reason_code_map": {
            code: REASON_CODE_MAP.get(
                code, {"severity": "unknown", "hint": "inspect findings"}
            )
            for code in reason_codes
        }
        if reason_codes
        else REASON_CODE_MAP,
        "findings_by_reason": findings_by_reason,
        "findings": findings,
        "plan_count": len(plans),
        "completion_count": len(completions),
        "eligible_wave_count": len(eligible_waves),
        "active_waves": sorted(active_plans, key=wave_version),
        "completed_waves": sorted(completed_plans, key=wave_version),
        "transition": transition,
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
