#!/usr/bin/env python3

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config_layering import (  # type: ignore
    load_layered_config,
    resolve_write_path,
    save_config as save_config_file,
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


def save_state(profile: str, description: str) -> None:
    global LAYERED_WRITE_PATH
    LAYERED_WRITE_PATH = resolve_write_path()
    payload = {
        "current": profile,
        "description": description,
        "updated_at": now_iso(),
    }

    if LEGACY_ENV_SET:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return

    config, _ = load_layered_config()
    config[SECTION] = payload
    save_config_file(config, LAYERED_WRITE_PATH)


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

    for step in entry["steps"]:
        result = subprocess.run(
            step,
            capture_output=True,
            text=True,
            check=False,
            env=os.environ.copy(),
            cwd=REPO_ROOT,
        )
        if result.returncode != 0:
            print(f"error: step failed: {' '.join(step)}")
            if result.stdout.strip():
                print(result.stdout.strip())
            if result.stderr.strip():
                print(result.stderr.strip())
            return result.returncode

    save_state(profile, entry["description"])
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
