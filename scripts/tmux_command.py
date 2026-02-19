#!/usr/bin/env python3

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config_layering import (  # type: ignore
    load_layered_config,
    resolve_write_path,
    save_config as save_config_file,
)

SECTION = "tmux_visual"
RUNTIME_CACHE = (
    Path.home()
    / ".config"
    / "opencode"
    / "my_opencode"
    / "runtime"
    / "gateway-pane-session-cache.json"
)
DEFAULT_STATE = {
    "enabled": False,
    "layout": "split-3",
    "max_panes": 3,
    "require_safe_panes": True,
}
ALLOWED_LAYOUTS = {"split-2", "split-3", "grid-4"}


def usage() -> int:
    print(
        "usage: /tmux status [--json] | /tmux config <enabled|layout|max-panes|safe-panes> <value> | /tmux doctor [--json] | /tmux help"
    )
    return 2


def normalize_state(raw: Any) -> dict[str, Any]:
    state = dict(DEFAULT_STATE)
    if not isinstance(raw, dict):
        return state
    state["enabled"] = bool(raw.get("enabled", state["enabled"]))
    layout = str(raw.get("layout") or state["layout"]).strip()
    if layout in ALLOWED_LAYOUTS:
        state["layout"] = layout
    try:
        max_panes = int(raw.get("max_panes", state["max_panes"]))
        if max_panes >= 1:
            state["max_panes"] = max_panes
    except (TypeError, ValueError):
        pass
    state["require_safe_panes"] = bool(
        raw.get("require_safe_panes", state["require_safe_panes"])
    )
    return state


def load_state() -> tuple[dict[str, Any], dict[str, Any], Path]:
    config, _ = load_layered_config()
    write_path = resolve_write_path()
    state = normalize_state(config.get(SECTION))
    return config, state, write_path


def save_state(config: dict[str, Any], state: dict[str, Any], write_path: Path) -> None:
    config[SECTION] = state
    save_config_file(config, write_path)


def _runtime_cache_summary() -> dict[str, Any]:
    if not RUNTIME_CACHE.exists():
        return {
            "path": str(RUNTIME_CACHE),
            "exists": False,
            "pane_count": 0,
            "updated_at": None,
        }
    try:
        payload = json.loads(RUNTIME_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {
            "path": str(RUNTIME_CACHE),
            "exists": True,
            "pane_count": 0,
            "updated_at": None,
            "parse_error": True,
        }
    panes_any = payload.get("panes") if isinstance(payload, dict) else {}
    panes = panes_any if isinstance(panes_any, dict) else {}
    return {
        "path": str(RUNTIME_CACHE),
        "exists": True,
        "pane_count": len(panes),
        "updated_at": payload.get("updated_at") if isinstance(payload, dict) else None,
    }


def status_payload(state: dict[str, Any], write_path: Path) -> dict[str, Any]:
    tmux_available = shutil.which("tmux") is not None
    enabled = bool(state.get("enabled"))
    runtime_mode = "tmux" if enabled and tmux_available else "headless_fallback"
    reason = "tmux_mode_ready"
    if not enabled:
        reason = "tmux_mode_disabled"
    elif not tmux_available:
        reason = "tmux_binary_missing"
    return {
        "enabled": enabled,
        "layout": state.get("layout"),
        "max_panes": state.get("max_panes"),
        "require_safe_panes": bool(state.get("require_safe_panes")),
        "tmux_available": tmux_available,
        "runtime_mode": runtime_mode,
        "reason_code": reason,
        "pane_session_cache": _runtime_cache_summary(),
        "config": str(write_path),
    }


def command_status(argv: list[str]) -> int:
    if any(arg not in ("--json",) for arg in argv):
        return usage()
    as_json = "--json" in argv
    _, state, write_path = load_state()
    payload = status_payload(state, write_path)
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"enabled: {payload['enabled']}")
        print(f"runtime_mode: {payload['runtime_mode']}")
        print(f"reason_code: {payload['reason_code']}")
        print(f"tmux_available: {payload['tmux_available']}")
        print(f"layout: {payload['layout']}")
        print(f"max_panes: {payload['max_panes']}")
        print(f"pane_cache_entries: {payload['pane_session_cache']['pane_count']}")
        print(f"config: {payload['config']}")
    return 0


def command_config(argv: list[str]) -> int:
    if len(argv) != 2:
        return usage()
    key = argv[0].strip().lower()
    value = argv[1].strip()
    config, state, write_path = load_state()

    if key == "enabled":
        if value not in {"true", "false"}:
            return usage()
        state["enabled"] = value == "true"
    elif key == "layout":
        if value not in ALLOWED_LAYOUTS:
            return usage()
        state["layout"] = value
    elif key == "max-panes":
        try:
            parsed = int(value)
        except ValueError:
            return usage()
        if parsed < 1:
            return usage()
        state["max_panes"] = parsed
    elif key == "safe-panes":
        if value not in {"true", "false"}:
            return usage()
        state["require_safe_panes"] = value == "true"
    else:
        return usage()

    save_state(config, state, write_path)
    print(f"config: {write_path}")
    print(f"updated: {key}")
    return 0


def command_doctor(argv: list[str]) -> int:
    if any(arg not in ("--json",) for arg in argv):
        return usage()
    as_json = "--json" in argv
    _, state, write_path = load_state()
    payload = status_payload(state, write_path)
    warnings: list[str] = []
    if payload["enabled"] and not payload["tmux_available"]:
        warnings.append("tmux binary is not available; using headless fallback mode")
    if int(payload["max_panes"]) > 6:
        warnings.append(
            "max_panes is high; consider 2-4 panes for stable visual orchestration"
        )
    result = "PASS" if not warnings else "WARN"
    report = {
        "result": result,
        "warnings": warnings,
        "status": payload,
    }
    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print(f"result: {result}")
        for warning in warnings:
            print(f"warning: {warning}")
        print(f"runtime_mode: {payload['runtime_mode']}")
        print(f"config: {payload['config']}")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        return usage()
    cmd = argv[0].strip().lower()
    rest = argv[1:]
    if cmd == "help":
        return usage()
    if cmd == "status":
        return command_status(rest)
    if cmd == "config":
        return command_config(rest)
    if cmd == "doctor":
        return command_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
