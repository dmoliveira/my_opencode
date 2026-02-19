#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from typing import Any


SKILLS: dict[str, dict[str, Any]] = {
    "playwright": {
        "name": "playwright",
        "summary": "Browser automation skill that keeps Playwright as the default provider.",
        "triggers": [
            "web UI validation",
            "end-to-end browser flow",
            "visual interaction checks",
            "repro steps requiring real browser execution",
        ],
        "boundaries": [
            "Use only for browser-driven work; skip for backend-only tasks.",
            "Keep provider stable-first: Playwright before optional alternatives.",
            "If browser prerequisites are missing, report exact install hint and fallback path.",
        ],
        "reuse_commands": [
            "/browser profile playwright",
            "/browser doctor --json",
            '/autopilot-go --goal "run browser task end-to-end"',
        ],
        "fallback": "When Playwright is unavailable, capture readiness blockers and continue with non-browser checks until dependencies are installed.",
    },
    "frontend-ui-ux": {
        "name": "frontend-ui-ux",
        "summary": "Frontend delivery skill focused on deliberate UI/UX quality with existing workflows.",
        "triggers": [
            "new UI screen",
            "layout redesign",
            "component UX polish",
            "responsive behavior fixes",
        ],
        "boundaries": [
            "Reuse existing design system patterns when present.",
            "Avoid generic boilerplate visuals and weak default styling.",
            "Validate desktop and mobile behavior before claiming completion.",
        ],
        "reuse_commands": [
            '/autopilot-objective --goal "ship frontend UX improvement"',
            "/browser profile playwright",
            "/browser doctor --json",
        ],
        "fallback": "If visual execution is blocked, deliver code + static reasoning and list the exact browser/runtime blocker with next action.",
    },
    "git-master": {
        "name": "git-master",
        "summary": "Git workflow skill for safe branch hygiene, review, and PR-first delivery.",
        "triggers": [
            "prepare commit",
            "open pull request",
            "triage branch drift",
            "review readiness before merge",
        ],
        "boundaries": [
            "Never use destructive git operations unless explicitly requested.",
            "Prefer small commits, PR review checks, and reproducible validation evidence.",
            "Keep local worktree cleanup and main sync in the finish loop.",
        ],
        "reuse_commands": [
            "/pr-review checklist --json",
            "/pr-review --json",
            "/release-train status",
        ],
        "fallback": "If remote/credential operations fail, continue local validation and report exact git/gh error with next command to unblock.",
    },
}


def usage() -> int:
    print("usage: /skill-contract <playwright|frontend-ui-ux|git-master> [--json]")
    return 2


def main(argv: list[str]) -> int:
    if not argv:
        return usage()

    json_output = "--json" in argv
    args = [arg for arg in argv if arg != "--json"]
    if len(args) != 1:
        return usage()

    skill_name = args[0].strip().lower()
    payload = SKILLS.get(skill_name)
    if payload is None:
        return usage()

    if json_output:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"skill: {payload['name']}")
    print(f"summary: {payload['summary']}")
    print("triggers:")
    for item in payload["triggers"]:
        print(f"- {item}")
    print("boundaries:")
    for item in payload["boundaries"]:
        print(f"- {item}")
    print("reuse_commands:")
    for item in payload["reuse_commands"]:
        print(f"- {item}")
    print(f"fallback: {payload['fallback']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
