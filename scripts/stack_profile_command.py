#!/usr/bin/env python3

import json
import os
import sys
import copy
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
from model_routing_command import CONFIG_PATH as MODEL_ROUTING_PATH, _merged_state  # type: ignore
from policy_command import PROFILE_MAP as POLICY_PROFILES  # type: ignore
from telemetry_command import (  # type: ignore
    PROFILE_MAP as TELEMETRY_PROFILES,
    load_state_from_dict as load_telemetry_state,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_STACK_PROFILE_PATH",
        "~/.config/opencode/opencode-stack-profile.json",
    )
).expanduser()
LEGACY_ENV_SET = "MY_OPENCODE_STACK_PROFILE_PATH" in os.environ
LAYERED_WRITE_PATH = resolve_write_path()
SECTION = "stack_profile"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def script(name: str) -> Path:
    return REPO_ROOT / "scripts" / name


PROFILES = {
    "focus": {
        "description": "Minimal interruptions for deep work.",
        "steps": [
            [sys.executable, str(script("notify_command.py")), "profile", "focus"],
            [sys.executable, str(script("telemetry_command.py")), "profile", "off"],
            [sys.executable, str(script("post_session_command.py")), "disable"],
            [sys.executable, str(script("policy_command.py")), "profile", "strict"],
            [
                sys.executable,
                str(script("model_routing_command.py")),
                "set-category",
                "deep",
            ],
        ],
    },
    "research": {
        "description": "High-signal telemetry and broad visibility for exploration.",
        "steps": [
            [sys.executable, str(script("notify_command.py")), "profile", "all"],
            [sys.executable, str(script("telemetry_command.py")), "profile", "local"],
            [sys.executable, str(script("post_session_command.py")), "enable"],
            [
                sys.executable,
                str(script("post_session_command.py")),
                "set",
                "command",
                "make selftest",
            ],
            [
                sys.executable,
                str(script("post_session_command.py")),
                "set",
                "run-on",
                "exit,manual",
            ],
            [sys.executable, str(script("policy_command.py")), "profile", "balanced"],
            [
                sys.executable,
                str(script("model_routing_command.py")),
                "set-category",
                "deep",
            ],
        ],
    },
    "quiet-ci": {
        "description": "Low-noise setup for CI-like validation loops.",
        "steps": [
            [sys.executable, str(script("notify_command.py")), "profile", "quiet"],
            [sys.executable, str(script("notify_command.py")), "disable", "complete"],
            [sys.executable, str(script("telemetry_command.py")), "profile", "off"],
            [sys.executable, str(script("post_session_command.py")), "enable"],
            [
                sys.executable,
                str(script("post_session_command.py")),
                "set",
                "command",
                "make validate",
            ],
            [
                sys.executable,
                str(script("post_session_command.py")),
                "set",
                "run-on",
                "manual",
            ],
            [sys.executable, str(script("policy_command.py")), "profile", "strict"],
            [
                sys.executable,
                str(script("model_routing_command.py")),
                "set-category",
                "quick",
            ],
        ],
    },
}

PROFILE_OUTCOMES = {
    "focus": {
        "telemetry": "off",
        "post_session": {"enabled": False},
        "policy": "strict",
        "model_routing": "deep",
    },
    "research": {
        "telemetry": "local",
        "post_session": {
            "enabled": True,
            "command": "make selftest",
            "run_on": ["exit", "manual"],
        },
        "policy": "balanced",
        "model_routing": "deep",
    },
    "quiet-ci": {
        "telemetry": "off",
        "post_session": {
            "enabled": True,
            "command": "make validate",
            "run_on": ["manual"],
        },
        "policy": "strict",
        "model_routing": "quick",
    },
}


def usage() -> int:
    print("usage: /stack status | /stack help | /stack apply <focus|research|quiet-ci>")
    return 2


def load_state() -> dict:
    global LAYERED_WRITE_PATH
    LAYERED_WRITE_PATH = resolve_write_path()

    if LEGACY_ENV_SET:
        if STATE_PATH.exists():
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return {"current": None, "updated_at": None, "description": None}

    config, _ = load_layered_config()
    section = config.get(SECTION)
    if isinstance(section, dict):
        return {
            "current": section.get("current"),
            "updated_at": section.get("updated_at"),
            "description": section.get("description"),
        }
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"current": None, "updated_at": None, "description": None}


def apply_state(profile: str, description: str) -> None:
    global LAYERED_WRITE_PATH
    LAYERED_WRITE_PATH = resolve_write_path()
    payload = {
        "current": profile,
        "description": description,
        "updated_at": now_iso(),
    }

    outcome = PROFILE_OUTCOMES[profile]
    participants: list[ConfigFileParticipant] = []
    telemetry_path_raw = os.environ.get("OPENCODE_TELEMETRY_PATH", "").strip()
    post_path_raw = os.environ.get("MY_OPENCODE_SESSION_CONFIG_PATH", "").strip()
    policy_path_raw = os.environ.get("MY_OPENCODE_POLICY_PATH", "").strip()
    notify_path_raw = os.environ.get("OPENCODE_NOTIFICATIONS_PATH", "").strip()
    telemetry_path = Path(telemetry_path_raw).expanduser() if telemetry_path_raw else None
    post_path = Path(post_path_raw).expanduser() if post_path_raw else None
    policy_path = Path(policy_path_raw).expanduser() if policy_path_raw else None
    notify_path = Path(notify_path_raw).expanduser() if notify_path_raw else None
    telemetry_profile = TELEMETRY_PROFILES[outcome["telemetry"]]
    policy_name = outcome["policy"]
    policy_profile = POLICY_PROFILES[policy_name]
    notify_payload = copy.deepcopy(policy_profile["notify"])
    policy_payload = {
        "current": policy_name,
        "description": policy_profile["description"],
        "updated_at": now_iso(),
        "notify_config": str(notify_path or resolve_write_path()),
    }

    def mutate_routing(data: dict) -> None:
        state = _merged_state(data)
        state["active_category"] = outcome["model_routing"]
        data.clear()
        data.update(
            {
                "active_category": state.get("active_category", "balanced"),
                "system_defaults": state.get("system_defaults", {}),
                "latest_trace": state.get("latest_trace", {}),
            }
        )

    participants.append(ConfigFileParticipant(MODEL_ROUTING_PATH, mutate_routing))

    def mutate_telemetry(data: dict) -> None:
        telemetry = load_telemetry_state(data)
        telemetry["enabled"] = telemetry_profile["enabled"]
        telemetry["events"] = copy.deepcopy(telemetry_profile["events"])
        data.clear()
        data.update(telemetry)

    def mutate_post(data: dict) -> None:
        post = data.get("post_session")
        post_state = dict(post) if isinstance(post, dict) else {
            "enabled": False,
            "command": "",
            "timeout_ms": 120000,
            "run_on": ["exit"],
        }
        post_state.update(copy.deepcopy(outcome["post_session"]))
        data.clear()
        data["post_session"] = post_state

    def replace_policy(data: dict) -> None:
        data.clear()
        data.update(policy_payload)

    def replace_notify(data: dict) -> None:
        data.clear()
        data.update(copy.deepcopy(notify_payload))

    if telemetry_path is not None:
        participants.append(ConfigFileParticipant(telemetry_path, mutate_telemetry))
    if post_path is not None:
        participants.append(ConfigFileParticipant(post_path, mutate_post))
    if policy_path is not None:
        participants.append(ConfigFileParticipant(policy_path, replace_policy))
    if notify_path is not None:
        participants.append(ConfigFileParticipant(notify_path, replace_notify))
    if LEGACY_ENV_SET:
        def replace_stack_state(data: dict) -> None:
            data.clear()
            data.update(payload)

        participants.append(
            ConfigFileParticipant(STATE_PATH, replace_stack_state)
        )

    def mutate_layered(config: dict) -> None:
        if telemetry_path is None:
            telemetry_raw = config.get("telemetry")
            telemetry = load_telemetry_state(
                telemetry_raw if isinstance(telemetry_raw, dict) else {}
            )
            telemetry["enabled"] = telemetry_profile["enabled"]
            telemetry["events"] = copy.deepcopy(telemetry_profile["events"])
            config["telemetry"] = telemetry
        if post_path is None:
            post = config.get("post_session")
            post_state = dict(post) if isinstance(post, dict) else {
                "enabled": False,
                "command": "",
                "timeout_ms": 120000,
                "run_on": ["exit"],
            }
            post_state.update(copy.deepcopy(outcome["post_session"]))
            config["post_session"] = post_state
        if notify_path is None:
            config["notify"] = copy.deepcopy(notify_payload)
        if policy_path is None:
            config["policy"] = policy_payload
        if not LEGACY_ENV_SET:
            config[SECTION] = payload

    result = edit_layered_config(
        mutate_layered,
        direct_participants=tuple(participants),
    )
    LAYERED_WRITE_PATH = result.files[0].path


def print_status() -> int:
    state = load_state()
    print(f"profile: {state.get('current')}")
    print(f"description: {state.get('description')}")
    print(f"updated_at: {state.get('updated_at')}")
    print(f"state_path: {STATE_PATH if LEGACY_ENV_SET else LAYERED_WRITE_PATH}")
    return 0


def apply_profile(profile: str) -> int:
    entry = PROFILES.get(profile)
    if not entry:
        return usage()

    apply_state(profile, entry["description"])
    print(f"profile: {profile}")
    print(f"description: {entry['description']}")
    print(f"state_path: {STATE_PATH if LEGACY_ENV_SET else LAYERED_WRITE_PATH}")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] == "status":
        return print_status()
    if argv[0] == "help":
        return usage()
    if argv[0] == "apply":
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
