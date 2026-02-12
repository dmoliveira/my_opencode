#!/usr/bin/env python3

import json
import os
import sys
from pathlib import Path


DEFAULT_CONFIG_PATH = Path(
    os.environ.get(
        "OPENCODE_NOTIFICATIONS_PATH", "~/.config/opencode/opencode-notifications.json"
    )
).expanduser()

EVENTS = ("complete", "error", "permission", "question")
CHANNELS = ("sound", "visual")

PROFILE_MAP = {
    "all": {
        "enabled": True,
        "sound": True,
        "visual": True,
        "events": {name: True for name in EVENTS},
        "channels": {name: {"sound": True, "visual": True} for name in EVENTS},
    },
    "quiet": {
        "enabled": True,
        "sound": False,
        "visual": True,
        "events": {name: True for name in EVENTS},
        "channels": {name: {"sound": False, "visual": True} for name in EVENTS},
    },
    "focus": {
        "enabled": True,
        "sound": False,
        "visual": True,
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
    "sound-only": {
        "enabled": True,
        "sound": True,
        "visual": False,
        "events": {name: True for name in EVENTS},
        "channels": {name: {"sound": True, "visual": False} for name in EVENTS},
    },
    "visual-only": {
        "enabled": True,
        "sound": False,
        "visual": True,
        "events": {name: True for name in EVENTS},
        "channels": {name: {"sound": False, "visual": True} for name in EVENTS},
    },
}


def default_state() -> dict:
    return {
        "enabled": True,
        "sound": {"enabled": True},
        "visual": {"enabled": True},
        "events": {name: True for name in EVENTS},
        "channels": {name: {"sound": True, "visual": True} for name in EVENTS},
    }


def to_bool(value, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    return fallback


def load_config(config_path: Path) -> dict:
    if not config_path.exists():
        return default_state()

    data = json.loads(config_path.read_text(encoding="utf-8"))
    state = default_state()

    state["enabled"] = to_bool(data.get("enabled"), state["enabled"])

    if isinstance(data.get("sound"), dict):
        state["sound"]["enabled"] = to_bool(
            data["sound"].get("enabled"), state["sound"]["enabled"]
        )

    if isinstance(data.get("visual"), dict):
        state["visual"]["enabled"] = to_bool(
            data["visual"].get("enabled"), state["visual"]["enabled"]
        )

    if isinstance(data.get("events"), dict):
        for event in EVENTS:
            if event in data["events"]:
                state["events"][event] = to_bool(
                    data["events"][event], state["events"][event]
                )

    if isinstance(data.get("channels"), dict):
        for event in EVENTS:
            entry = data["channels"].get(event)
            if not isinstance(entry, dict):
                continue
            for channel in CHANNELS:
                if channel in entry:
                    state["channels"][event][channel] = to_bool(
                        entry[channel], state["channels"][event][channel]
                    )

    return state


def write_config(config_path: Path, state: dict) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "enabled": state["enabled"],
        "sound": {"enabled": state["sound"]["enabled"]},
        "visual": {"enabled": state["visual"]["enabled"]},
        "events": state["events"],
        "channels": state["channels"],
    }
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def usage() -> int:
    print(
        "usage: /notify status | /notify help | /notify profile <all|quiet|focus|sound-only|visual-only> | /notify enable <all|sound|visual|complete|error|permission|question> | /notify disable <all|sound|visual|complete|error|permission|question> | /notify channel <complete|error|permission|question> <sound|visual> <on|off>"
    )
    return 2


def print_status(config_path: Path, state: dict) -> int:
    print(f"all: {'enabled' if state['enabled'] else 'disabled'}")
    print(f"sound: {'enabled' if state['sound']['enabled'] else 'disabled'}")
    print(f"visual: {'enabled' if state['visual']['enabled'] else 'disabled'}")
    print("events:")
    for event in EVENTS:
        enabled = state["events"][event]
        print(
            f"- {event}: {'enabled' if enabled else 'disabled'} [sound={'on' if state['channels'][event]['sound'] else 'off'}, visual={'on' if state['channels'][event]['visual'] else 'off'}]"
        )
    print(f"config: {config_path}")
    return 0


def apply_profile(state: dict, profile: str) -> int:
    if profile not in PROFILE_MAP:
        return usage()

    selected = PROFILE_MAP[profile]
    state["enabled"] = selected["enabled"]
    state["sound"]["enabled"] = selected["sound"]
    state["visual"]["enabled"] = selected["visual"]

    for event in EVENTS:
        state["events"][event] = selected["events"][event]
        state["channels"][event]["sound"] = selected["channels"][event]["sound"]
        state["channels"][event]["visual"] = selected["channels"][event]["visual"]

    print(f"profile: {profile}")
    return 0


def set_toggle(state: dict, action: str, target: str) -> int:
    value = action == "enable"

    if target == "all":
        state["enabled"] = value
        print(f"all: {'enabled' if value else 'disabled'}")
        return 0

    if target in CHANNELS:
        state[target]["enabled"] = value
        print(f"{target}: {'enabled' if value else 'disabled'}")
        return 0

    if target in EVENTS:
        state["events"][target] = value
        print(f"{target}: {'enabled' if value else 'disabled'}")
        return 0

    return usage()


def set_channel(state: dict, event: str, channel: str, value_text: str) -> int:
    if (
        event not in EVENTS
        or channel not in CHANNELS
        or value_text not in ("on", "off")
    ):
        return usage()
    value = value_text == "on"
    state["channels"][event][channel] = value
    print(f"{event}.{channel}: {'on' if value else 'off'}")
    return 0


def main(argv: list[str]) -> int:
    config_path = DEFAULT_CONFIG_PATH
    state = load_config(config_path)

    if not argv or argv[0] == "status":
        return print_status(config_path, state)

    if argv[0] == "help":
        return usage()

    if argv[0] == "profile":
        if len(argv) < 2:
            return usage()
        code = apply_profile(state, argv[1])
        if code != 0:
            return code
        write_config(config_path, state)
        print(f"config: {config_path}")
        return 0

    if argv[0] in ("enable", "disable"):
        if len(argv) < 2:
            return usage()
        code = set_toggle(state, argv[0], argv[1])
        if code != 0:
            return code
        write_config(config_path, state)
        print(f"config: {config_path}")
        return 0

    if argv[0] == "channel":
        if len(argv) < 4:
            return usage()
        code = set_channel(state, argv[1], argv[2], argv[3])
        if code != 0:
            return code
        write_config(config_path, state)
        print(f"config: {config_path}")
        return 0

    return usage()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
