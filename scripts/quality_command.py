#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config_layering import load_layered_config, resolve_write_path, save_config  # type: ignore


PROFILES: dict[str, dict[str, Any]] = {
    "off": {
        "profile": "off",
        "ts": {"lint": False, "typecheck": False, "tests": False},
        "py": {"selftest": False},
    },
    "fast": {
        "profile": "fast",
        "ts": {"lint": True, "typecheck": True, "tests": False},
        "py": {"selftest": True},
    },
    "strict": {
        "profile": "strict",
        "ts": {"lint": True, "typecheck": True, "tests": True},
        "py": {"selftest": True},
    },
}


# Prints command usage information.
def usage() -> int:
    print(
        "usage: /quality status [--json] | /quality profile <off|fast|strict> [--json] | /quality doctor [--json]"
    )
    return 2


# Emits payload in JSON or compact text format.
def emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


# Returns normalized quality section with defaults.
def normalized_quality(config: dict[str, Any]) -> dict[str, Any]:
    raw_any = config.get("quality")
    raw = raw_any if isinstance(raw_any, dict) else {}

    profile = str(raw.get("profile") or "fast")
    if profile not in PROFILES:
        profile = "fast"

    ts_any = raw.get("ts")
    ts = ts_any if isinstance(ts_any, dict) else {}
    py_any = raw.get("py")
    py = py_any if isinstance(py_any, dict) else {}

    return {
        "profile": profile,
        "ts": {
            "lint": bool(ts.get("lint", PROFILES[profile]["ts"]["lint"])),
            "typecheck": bool(
                ts.get("typecheck", PROFILES[profile]["ts"]["typecheck"])
            ),
            "tests": bool(ts.get("tests", PROFILES[profile]["ts"]["tests"])),
        },
        "py": {
            "selftest": bool(py.get("selftest", PROFILES[profile]["py"]["selftest"])),
        },
    }


# Applies quality profile and persists config.
def command_profile(args: list[str]) -> int:
    as_json = "--json" in args
    args = [arg for arg in args if arg != "--json"]
    if len(args) != 1:
        return usage()
    profile = args[0].strip().lower()
    if profile not in PROFILES:
        return usage()

    config, _ = load_layered_config()
    config["quality"] = PROFILES[profile]
    write_path = resolve_write_path()
    save_config(config, write_path)

    emit(
        {
            "result": "PASS",
            "profile": profile,
            "quality": PROFILES[profile],
            "config": str(write_path),
        },
        as_json=as_json,
    )
    return 0


# Shows active quality profile and toggles.
def command_status(args: list[str]) -> int:
    as_json = "--json" in args
    args = [arg for arg in args if arg != "--json"]
    if args:
        return usage()
    config, _ = load_layered_config()
    quality = normalized_quality(config)
    emit(
        {
            "result": "PASS",
            "quality": quality,
            "config": str(resolve_write_path()),
        },
        as_json=as_json,
    )
    return 0


# Validates quality configuration shape and profile.
def command_doctor(args: list[str]) -> int:
    as_json = "--json" in args
    args = [arg for arg in args if arg != "--json"]
    if args:
        return usage()
    config, _ = load_layered_config()
    quality = normalized_quality(config)
    profile = quality.get("profile")
    ok = profile in PROFILES
    emit(
        {
            "result": "PASS" if ok else "FAIL",
            "profile": profile,
            "quality": quality,
            "config": str(resolve_write_path()),
            "quick_fixes": [
                "/quality profile fast",
                "/quality profile strict",
                "/quality profile off",
            ],
        },
        as_json=as_json,
    )
    return 0 if ok else 1


# Dispatches quality command subcommands.
def main(argv: list[str]) -> int:
    if not argv:
        return command_status([])
    cmd, *rest = argv
    if cmd in {"help", "--help", "-h"}:
        return usage()
    if cmd == "status":
        return command_status(rest)
    if cmd == "profile":
        return command_profile(rest)
    if cmd == "doctor":
        return command_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
