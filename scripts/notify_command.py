#!/usr/bin/env python3

import json
import os
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config_layering import (  # type: ignore
    load_layered_config,
    resolve_write_path,
    save_config as save_config_file,
)


DEFAULT_CONFIG_PATH = Path(
    os.environ.get(
        "OPENCODE_NOTIFICATIONS_PATH", "~/.config/opencode/opencode-notifications.json"
    )
).expanduser()
LEGACY_ENV_SET = "OPENCODE_NOTIFICATIONS_PATH" in os.environ
CONFIG_PATH = resolve_write_path()
SECTION = "notify"

EVENTS = ("complete", "error", "permission", "question")
CHANNELS = ("sound", "visual")
SOUND_THEMES = ("classic", "minimal", "retro", "urgent", "chime")
ICON_MODES = ("nerd+emoji", "emoji")
REPO_ROOT = SCRIPT_DIR.parent

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
        "sound": {
            "enabled": True,
            "theme": "classic",
            "eventThemes": {name: "default" for name in EVENTS},
            "customFiles": {name: "" for name in EVENTS},
        },
        "visual": {"enabled": True},
        "icons": {"enabled": True, "version": "v1", "mode": "nerd+emoji"},
        "events": {name: True for name in EVENTS},
        "channels": {name: {"sound": True, "visual": True} for name in EVENTS},
    }


def to_bool(value, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    return fallback


def normalize_label(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


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
        theme = normalize_label(data["sound"].get("theme")).lower()
        if theme in SOUND_THEMES:
            state["sound"]["theme"] = theme
        if isinstance(data["sound"].get("eventThemes"), dict):
            for event in EVENTS:
                event_theme = normalize_label(
                    data["sound"]["eventThemes"].get(event)
                ).lower()
                if event_theme == "default" or event_theme in SOUND_THEMES:
                    state["sound"]["eventThemes"][event] = event_theme
        if isinstance(data["sound"].get("customFiles"), dict):
            for event in EVENTS:
                custom = normalize_label(data["sound"]["customFiles"].get(event))
                if custom or data["sound"]["customFiles"].get(event) == "":
                    state["sound"]["customFiles"][event] = custom
        theme = normalize_label(data["sound"].get("theme")).lower()
        if theme in SOUND_THEMES:
            state["sound"]["theme"] = theme
        if isinstance(data["sound"].get("eventThemes"), dict):
            for event in EVENTS:
                event_theme = normalize_label(
                    data["sound"]["eventThemes"].get(event)
                ).lower()
                if event_theme == "default" or event_theme in SOUND_THEMES:
                    state["sound"]["eventThemes"][event] = event_theme
        if isinstance(data["sound"].get("customFiles"), dict):
            for event in EVENTS:
                custom = normalize_label(data["sound"]["customFiles"].get(event))
                if custom or data["sound"]["customFiles"].get(event) == "":
                    state["sound"]["customFiles"][event] = custom

    if isinstance(data.get("visual"), dict):
        state["visual"]["enabled"] = to_bool(
            data["visual"].get("enabled"), state["visual"]["enabled"]
        )

    if isinstance(data.get("icons"), dict):
        state["icons"]["enabled"] = to_bool(
            data["icons"].get("enabled"), state["icons"]["enabled"]
        )
        version = normalize_label(data["icons"].get("version"))
        if version:
            state["icons"]["version"] = version
        mode = normalize_label(data["icons"].get("mode")).lower()
        if mode in ICON_MODES:
            state["icons"]["mode"] = mode

    if isinstance(data.get("icons"), dict):
        state["icons"]["enabled"] = to_bool(
            data["icons"].get("enabled"), state["icons"]["enabled"]
        )
        version = normalize_label(data["icons"].get("version"))
        if version:
            state["icons"]["version"] = version
        mode = normalize_label(data["icons"].get("mode")).lower()
        if mode in ICON_MODES:
            state["icons"]["mode"] = mode

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


def load_state() -> dict:
    global CONFIG_PATH
    CONFIG_PATH = resolve_write_path()

    if LEGACY_ENV_SET:
        return load_config(DEFAULT_CONFIG_PATH)

    data, _ = load_layered_config()
    section = data.get(SECTION)
    if isinstance(section, dict):
        return load_config_from_dict(section)

    if DEFAULT_CONFIG_PATH.exists():
        return load_config(DEFAULT_CONFIG_PATH)
    return default_state()


def load_config_from_dict(data: dict) -> dict:
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
        "sound": {
            "enabled": state["sound"]["enabled"],
            "theme": state["sound"]["theme"],
            "eventThemes": state["sound"]["eventThemes"],
            "customFiles": state["sound"]["customFiles"],
        },
        "visual": {"enabled": state["visual"]["enabled"]},
        "icons": {
            "enabled": state["icons"]["enabled"],
            "version": state["icons"]["version"],
            "mode": state["icons"]["mode"],
        },
        "events": state["events"],
        "channels": state["channels"],
    }
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def save_state(state: dict) -> None:
    global CONFIG_PATH
    CONFIG_PATH = resolve_write_path()
    if LEGACY_ENV_SET:
        write_config(DEFAULT_CONFIG_PATH, state)
        return

    data, _ = load_layered_config()
    data[SECTION] = {
        "enabled": state["enabled"],
        "sound": {
            "enabled": state["sound"]["enabled"],
            "theme": state["sound"]["theme"],
            "eventThemes": state["sound"]["eventThemes"],
            "customFiles": state["sound"]["customFiles"],
        },
        "visual": {"enabled": state["visual"]["enabled"]},
        "icons": {
            "enabled": state["icons"]["enabled"],
            "version": state["icons"]["version"],
            "mode": state["icons"]["mode"],
        },
        "events": state["events"],
        "channels": state["channels"],
    }
    save_config_file(data, CONFIG_PATH)


def usage() -> int:
    print(
        "usage: /notify status | /notify help | /notify doctor [--json] [--verbose] | /notify profile <all|quiet|focus|sound-only|visual-only> | /notify enable <all|sound|visual|icons|complete|error|permission|question> | /notify disable <all|sound|visual|icons|complete|error|permission|question> | /notify channel <complete|error|permission|question> <sound|visual> <on|off> | /notify sound-theme <classic|minimal|retro|urgent|chime> | /notify event-sound <complete|error|permission|question> <default|classic|minimal|retro|urgent|chime> | /notify icon-version <version>"
    )
    return 2


def terminal_notifier_path() -> str:
    return shutil.which("terminal-notifier") or ""


def resolve_icon_path(state: dict, event: str) -> Path:
    return (
        REPO_ROOT
        / "assets"
        / "notify-icons"
        / state["icons"]["version"]
        / f"{event}.png"
    )


def resolve_custom_sound_path(raw_path: str, cwd: Path) -> Path:
    expanded = os.path.expanduser(raw_path)
    path = Path(expanded)
    if path.is_absolute():
        return path
    return (cwd / path).resolve()


def collect_doctor(config_path: Path, state: dict, verbose: bool = False) -> dict:
    problems: list[str] = []
    warnings: list[str] = []

    if not config_path.exists():
        warnings.append("notification config file not found yet (using defaults)")

    if not state["enabled"]:
        warnings.append("global notifications are disabled")

    if not state["sound"]["enabled"] and not state["visual"]["enabled"]:
        warnings.append("both sound and visual channels are disabled")

    enabled_events = [name for name in EVENTS if state["events"][name]]
    if not enabled_events:
        warnings.append("all events are disabled")

    for event in EVENTS:
        if state["events"][event] and not (
            state["channels"][event]["sound"] or state["channels"][event]["visual"]
        ):
            warnings.append(
                f"event {event} is enabled but both per-event channels are off"
            )

    report = {
        "result": "PASS" if not problems else "FAIL",
        "config": str(config_path),
        "enabled": state["enabled"],
        "sound_enabled": state["sound"]["enabled"],
        "sound_theme": state["sound"]["theme"],
        "visual_enabled": state["visual"]["enabled"],
        "icons_enabled": state["icons"]["enabled"],
        "icon_version": state["icons"]["version"],
        "icon_mode": state["icons"]["mode"],
        "events": state["events"],
        "channels": state["channels"],
        "warnings": warnings,
        "problems": problems,
        "quick_fixes": [
            "run /notify profile focus for low-noise defaults",
            "run /notify enable visual or /notify enable sound",
            "run /notify enable permission or /notify enable error",
        ]
        if warnings or problems
        else [],
    }

    if verbose:
        icon_files = {}
        for event in EVENTS:
            icon_path = resolve_icon_path(state, event)
            icon_files[event] = {
                "path": str(icon_path),
                "exists": icon_path.exists(),
            }

        sound_files = {}
        cwd = Path.cwd()
        for event in EVENTS:
            custom_raw = normalize_label(state["sound"]["customFiles"].get(event, ""))
            custom_path = (
                resolve_custom_sound_path(custom_raw, cwd) if custom_raw else None
            )
            sound_files[event] = {
                "theme_override": state["sound"]["eventThemes"].get(event, "default"),
                "custom": {
                    "configured": bool(custom_raw),
                    "path": str(custom_path) if custom_path else "",
                    "exists": bool(custom_path and custom_path.exists()),
                },
            }

        report["runtime"] = {
            "platform": sys.platform,
            "terminal_notifier": {
                "path": terminal_notifier_path(),
                "available": bool(terminal_notifier_path()),
            },
            "osascript_available": bool(shutil.which("osascript")),
            "notify_send_available": bool(shutil.which("notify-send")),
            "icon_files": icon_files,
            "sound_files": sound_files,
        }

    return report


def print_doctor(
    config_path: Path, state: dict, json_output: bool, verbose: bool
) -> int:
    report = collect_doctor(config_path, state, verbose=verbose)

    if json_output:
        print(json.dumps(report, indent=2))
        return 0 if report["result"] == "PASS" else 1

    print("notify doctor")
    print("-----------")
    print(f"config: {report['config']}")
    print(f"global: {'enabled' if report['enabled'] else 'disabled'}")
    print(f"sound: {'enabled' if report['sound_enabled'] else 'disabled'}")
    print(f"sound theme: {state['sound']['theme']}")
    print(f"visual: {'enabled' if report['visual_enabled'] else 'disabled'}")
    print(
        f"icons: {'enabled' if state['icons']['enabled'] else 'disabled'} [version={state['icons']['version']}, mode={state['icons']['mode']}]"
    )
    print("events:")
    for event in EVENTS:
        print(
            f"- {event}: {'enabled' if state['events'][event] else 'disabled'} [sound={'on' if state['channels'][event]['sound'] else 'off'}, visual={'on' if state['channels'][event]['visual'] else 'off'}]"
        )

    if verbose:
        runtime = report.get("runtime", {})
        print("\nruntime:")
        print(f"- platform: {runtime.get('platform', '')}")
        notifier = runtime.get("terminal_notifier", {})
        print(
            f"- terminal-notifier: {'available' if notifier.get('available') else 'missing'}"
            + (f" ({notifier.get('path')})" if notifier.get("path") else "")
        )
        print(
            f"- osascript: {'available' if runtime.get('osascript_available') else 'missing'}"
        )
        print(
            f"- notify-send: {'available' if runtime.get('notify_send_available') else 'missing'}"
        )
        print("- icon files:")
        icon_files = runtime.get("icon_files", {})
        for event in EVENTS:
            entry = icon_files.get(event, {})
            print(
                f"  - {event}: {'present' if entry.get('exists') else 'missing'}"
                f" [{entry.get('path', '')}]"
            )

    if report["warnings"]:
        print("\nwarnings:")
        for item in report["warnings"]:
            print(f"- {item}")

    if report["problems"]:
        print("\nproblems:")
        for item in report["problems"]:
            print(f"- {item}")
        print("\nresult: FAIL")
        return 1

    print("\nresult: PASS")
    return 0


def print_status(config_path: Path, state: dict) -> int:
    print(f"all: {'enabled' if state['enabled'] else 'disabled'}")
    print(f"sound: {'enabled' if state['sound']['enabled'] else 'disabled'}")
    print(f"sound theme: {state['sound']['theme']}")
    print(f"visual: {'enabled' if state['visual']['enabled'] else 'disabled'}")
    print(
        f"icons: {'enabled' if state['icons']['enabled'] else 'disabled'} [version={state['icons']['version']}, mode={state['icons']['mode']}]"
    )
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

    if target == "icons":
        state["icons"]["enabled"] = value
        print(f"icons: {'enabled' if value else 'disabled'}")
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


def set_sound_theme(state: dict, theme: str) -> int:
    normalized = theme.strip().lower()
    if normalized not in SOUND_THEMES:
        return usage()
    state["sound"]["theme"] = normalized
    print(f"sound.theme: {normalized}")
    return 0


def set_event_sound_theme(state: dict, event: str, theme: str) -> int:
    normalized_event = event.strip().lower()
    normalized_theme = theme.strip().lower()
    if normalized_event not in EVENTS:
        return usage()
    if normalized_theme != "default" and normalized_theme not in SOUND_THEMES:
        return usage()
    state["sound"]["eventThemes"][normalized_event] = normalized_theme
    print(f"sound.eventThemes.{normalized_event}: {normalized_theme}")
    return 0


def set_icon_version(state: dict, version: str) -> int:
    normalized = version.strip()
    if not normalized:
        return usage()
    state["icons"]["version"] = normalized
    print(f"icons.version: {normalized}")
    return 0


def main(argv: list[str]) -> int:
    state = load_state()
    config_path = DEFAULT_CONFIG_PATH if LEGACY_ENV_SET else CONFIG_PATH

    if not argv or argv[0] == "status":
        return print_status(config_path, state)

    if argv[0] == "help":
        return usage()

    if argv[0] == "doctor":
        flags = set(argv[1:])
        allowed_flags = {"--json", "--verbose"}
        if not flags.issubset(allowed_flags):
            return usage()
        return print_doctor(
            config_path,
            state,
            json_output="--json" in flags,
            verbose="--verbose" in flags,
        )

    if argv[0] == "profile":
        if len(argv) < 2:
            return usage()
        code = apply_profile(state, argv[1])
        if code != 0:
            return code
        save_state(state)
        print(f"config: {DEFAULT_CONFIG_PATH if LEGACY_ENV_SET else CONFIG_PATH}")
        return 0

    if argv[0] in ("enable", "disable"):
        if len(argv) < 2:
            return usage()
        code = set_toggle(state, argv[0], argv[1])
        if code != 0:
            return code
        save_state(state)
        print(f"config: {DEFAULT_CONFIG_PATH if LEGACY_ENV_SET else CONFIG_PATH}")
        return 0

    if argv[0] == "channel":
        if len(argv) < 4:
            return usage()
        code = set_channel(state, argv[1], argv[2], argv[3])
        if code != 0:
            return code
        save_state(state)
        print(f"config: {DEFAULT_CONFIG_PATH if LEGACY_ENV_SET else CONFIG_PATH}")
        return 0

    if argv[0] == "sound-theme":
        if len(argv) < 2:
            return usage()
        code = set_sound_theme(state, argv[1])
        if code != 0:
            return code
        save_state(state)
        print(f"config: {DEFAULT_CONFIG_PATH if LEGACY_ENV_SET else CONFIG_PATH}")
        return 0

    if argv[0] == "event-sound":
        if len(argv) < 3:
            return usage()
        code = set_event_sound_theme(state, argv[1], argv[2])
        if code != 0:
            return code
        save_state(state)
        print(f"config: {DEFAULT_CONFIG_PATH if LEGACY_ENV_SET else CONFIG_PATH}")
        return 0

    if argv[0] == "icon-version":
        if len(argv) < 2:
            return usage()
        code = set_icon_version(state, argv[1])
        if code != 0:
            return code
        save_state(state)
        print(f"config: {DEFAULT_CONFIG_PATH if LEGACY_ENV_SET else CONFIG_PATH}")
        return 0

    return usage()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
