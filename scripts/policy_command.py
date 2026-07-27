#!/usr/bin/env python3

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config_layering import (  # type: ignore
    ConfigFileParticipant,
    edit_layered_config,
    load_layered_config,
    resolve_write_path,
)


POLICY_PATH = Path(
    os.environ.get("MY_OPENCODE_POLICY_PATH", "~/.config/opencode/opencode-policy.json")
).expanduser()
NOTIFY_PATH = Path(
    os.environ.get(
        "OPENCODE_NOTIFICATIONS_PATH", "~/.config/opencode/opencode-notifications.json"
    )
).expanduser()
POLICY_ENV_SET = "MY_OPENCODE_POLICY_PATH" in os.environ
NOTIFY_ENV_SET = "OPENCODE_NOTIFICATIONS_PATH" in os.environ
LAYERED_WRITE_PATH = resolve_write_path()
POLICY_SECTION = "policy"
NOTIFY_SECTION = "notify"

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
    global LAYERED_WRITE_PATH
    LAYERED_WRITE_PATH = resolve_write_path()

    if POLICY_ENV_SET:
        if POLICY_PATH.exists():
            return json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        return default_policy()

    data, _ = load_layered_config()
    section = data.get(POLICY_SECTION)
    if isinstance(section, dict):
        policy = default_policy()
        policy.update(section)
        if not policy.get("notify_config"):
            policy["notify_config"] = str(LAYERED_WRITE_PATH)
        return policy

    if POLICY_PATH.exists():
        return json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    return default_policy()


def default_policy() -> dict:
    return {
        "current": "balanced",
        "description": PROFILE_MAP["balanced"]["description"],
        "updated_at": None,
        "notify_config": str(LAYERED_WRITE_PATH),
    }


def print_status(policy: dict) -> int:
    current = policy.get("current", "balanced")
    print(f"profile: {current}")
    print(f"description: {policy.get('description')}")
    print(f"updated_at: {policy.get('updated_at')}")
    print(f"policy_config: {POLICY_PATH if POLICY_ENV_SET else LAYERED_WRITE_PATH}")
    print(
        f"notify_config: {policy.get('notify_config', str(NOTIFY_PATH if NOTIFY_ENV_SET else LAYERED_WRITE_PATH))}"
    )
    return 0


def apply_profile(name: str) -> int:
    global LAYERED_WRITE_PATH
    if name not in PROFILE_MAP:
        return usage()

    policy = {
        "current": name,
        "description": PROFILE_MAP[name]["description"],
        "updated_at": now_iso(),
        "notify_config": str(NOTIFY_PATH if NOTIFY_ENV_SET else LAYERED_WRITE_PATH),
    }
    notify = json.loads(json.dumps(PROFILE_MAP[name]["notify"]))
    participants: list[ConfigFileParticipant] = []

    def replace_policy(data: dict) -> None:
        data.clear()
        data.update(policy)

    def replace_notify(data: dict) -> None:
        data.clear()
        data.update(notify)

    if POLICY_ENV_SET:
        participants.append(ConfigFileParticipant(POLICY_PATH, replace_policy))
    if NOTIFY_ENV_SET:
        participants.append(ConfigFileParticipant(NOTIFY_PATH, replace_notify))

    def mutate_layered(config: dict) -> None:
        if not POLICY_ENV_SET:
            config[POLICY_SECTION] = policy
        if not NOTIFY_ENV_SET:
            config[NOTIFY_SECTION] = notify

    result = edit_layered_config(
        mutate_layered,
        direct_participants=tuple(participants),
    )
    LAYERED_WRITE_PATH = result.files[0].path

    print(f"profile: {name}")
    print(f"description: {PROFILE_MAP[name]['description']}")
    print(f"notify_config: {NOTIFY_PATH if NOTIFY_ENV_SET else LAYERED_WRITE_PATH}")
    print(f"policy_config: {POLICY_PATH if POLICY_ENV_SET else LAYERED_WRITE_PATH}")
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
