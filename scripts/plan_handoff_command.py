#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from typing import Any


PHASES: dict[str, dict[str, Any]] = {
    "plan": {
        "intent": "Validate a continuity-safe execution plan before mutation.",
        "commands": [
            "/task ready --json",
            '/autopilot-objective --goal "<goal>"',
            "/autopilot-status",
        ],
    },
    "execute": {
        "intent": "Run bounded execution while preserving resumability.",
        "commands": [
            '/autopilot-go "<goal>"',
            "/autopilot-status",
            "/checkpoint-list",
        ],
    },
    "resume": {
        "intent": "Recover deterministically after interruption.",
        "commands": [
            "/resume-status",
            "/resume-now",
            "/autopilot-resume",
        ],
    },
    "handoff": {
        "intent": "Publish current progress for the next execution cycle.",
        "commands": [
            "/autopilot-report",
            '/digest run --reason "manual"',
            "/task ready --json",
        ],
    },
    "stop": {
        "intent": "End the active loop with explicit operator intent.",
        "commands": [
            '/autopilot-stop --reason "manual_handoff"',
            "/checkpoint-show",
            "/autopilot-doctor",
        ],
    },
}


def build_status_payload() -> dict[str, Any]:
    return {
        "result": "PASS",
        "mode": "compatibility_profile",
        "canonical_runtime": ["autopilot", "task", "resume", "checkpoint"],
        "available_phases": list(PHASES.keys()),
        "notes": [
            "Thin compatibility surface only; no second planner runtime.",
            "Use existing canonical commands as source of truth.",
        ],
    }


def build_phase_payload(phase: str) -> dict[str, Any]:
    phase_payload = PHASES[phase]
    return {
        "result": "PASS",
        "phase": phase,
        "intent": phase_payload["intent"],
        "commands": phase_payload["commands"],
        "mode": "compatibility_profile",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="plan_handoff_command.py",
        description="Thin @plan-style continuity compatibility over canonical command surfaces.",
    )
    parser.add_argument(
        "phase",
        nargs="?",
        default="status",
        choices=["status", *PHASES.keys()],
        help="status or one of the continuity phases",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.phase == "status":
        payload = build_status_payload()
        if args.json:
            print(json.dumps(payload, indent=2))
            return 0
        print("plan-handoff compatibility profile")
        print("mode: compatibility_profile")
        print("canonical_runtime: autopilot, task, resume, checkpoint")
        print("available_phases: " + ", ".join(payload["available_phases"]))
        return 0

    payload = build_phase_payload(args.phase)
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"phase: {payload['phase']}")
    print(f"intent: {payload['intent']}")
    print("commands:")
    for command in payload["commands"]:
        print(f"- {command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
