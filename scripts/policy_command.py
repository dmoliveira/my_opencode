#!/usr/bin/env python3

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


POLICY_PATH = Path(
    os.environ.get("MY_OPENCODE_POLICY_PATH", "~/.config/opencode/opencode-policy.json")
).expanduser()
NOTIFY_PATH = Path(
    os.environ.get(
        "OPENCODE_NOTIFICATIONS_PATH", "~/.config/opencode/opencode-notifications.json"
    )
).expanduser()

EVENTS = ("complete", "error", "permission", "question")

PROFILE_MAP = {
    "strict": {
        "description": "Only high-signal prompts with visual emphasis.",
        "notify": {
            "enabled": True,
            "sound": {"enabled": False},
            "visual": {"enabled": True},
            "events": {
                "complete": False,
                "error": True,
                "permission": True,
                "question": True,
            },
            "channels": {
                "complete": {"sound": False, "visual": False},
                "error": {"sound": False, "visual": True},
                "permission": {"sound": False, "visual": True},
                "question": {"sound": False, "visual": True},
            },
        },
    },
    "balanced": {
        "description": "Visual for all events, sound only for risk events.",
        "notify": {
            "enabled": True,
            "sound": {"enabled": True},
            "visual": {"enabled": True},
            "events": {name: True for name in EVENTS},
            "channels": {
                "complete": {"sound": False, "visual": True},
                "error": {"sound": True, "visual": True},
                "permission": {"sound": True, "visual": True},
                "question": {"sound": False, "visual": True},
            },
        },
    },
    "fast": {
        "description": "All channels, all events, immediate feedback.",
        "notify": {
            "enabled": True,
            "sound": {"enabled": True},
            "visual": {"enabled": True},
            "events": {name: True for name in EVENTS},
            "channels": {name: {"sound": True, "visual": True} for name in EVENTS},
        },
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def usage() -> int:
    print(
        "usage: /policy status | /policy help | /policy profile <strict|balanced|fast>"
    )
    return 2


def load_policy() -> dict:
    if not POLICY_PATH.exists():
        return {
            "current": "balanced",
            "description": PROFILE_MAP["balanced"]["description"],
            "updated_at": None,
            "notify_config": str(NOTIFY_PATH),
        }
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def save_policy(data: dict) -> None:
    POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
    POLICY_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def save_notify_config(profile_name: str) -> None:
    cfg = PROFILE_MAP[profile_name]["notify"]
    NOTIFY_PATH.parent.mkdir(parents=True, exist_ok=True)
    NOTIFY_PATH.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def print_status(policy: dict) -> int:
    current = policy.get("current", "balanced")
    print(f"profile: {current}")
    print(f"description: {policy.get('description')}")
    print(f"updated_at: {policy.get('updated_at')}")
    print(f"policy_config: {POLICY_PATH}")
    print(f"notify_config: {policy.get('notify_config', str(NOTIFY_PATH))}")
    return 0


def apply_profile(name: str) -> int:
    if name not in PROFILE_MAP:
        return usage()

    save_notify_config(name)
    policy = {
        "current": name,
        "description": PROFILE_MAP[name]["description"],
        "updated_at": now_iso(),
        "notify_config": str(NOTIFY_PATH),
    }
    save_policy(policy)

    print(f"profile: {name}")
    print(f"description: {PROFILE_MAP[name]['description']}")
    print(f"notify_config: {NOTIFY_PATH}")
    print(f"policy_config: {POLICY_PATH}")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] == "status":
        return print_status(load_policy())

    if argv[0] == "help":
        return usage()

    if argv[0] == "profile":
        if len(argv) < 2:
            return usage()
        return apply_profile(argv[1])

    return usage()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
