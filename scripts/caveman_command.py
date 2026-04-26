#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from concise_mode_runtime import (  # type: ignore
    current_session_id,
    DEFAULT_CONCISE_MODE,
    VALID_CONCISE_MODES,
    effective_concise_mode,
    find_skill_path,
    normalize_mode,
    set_active_mode,
    set_default_mode,
)


def usage() -> int:
    print(
        "usage: /caveman status [--json] | /caveman doctor [--json] | /caveman set <off|lite|full|ultra|review|commit> [--json] | /caveman off [--json] | /caveman default <off|lite|full|ultra> [--json] | /caveman review [--json] | /caveman commit [--json] | /caveman compress [--json]"
    )
    return 2


def emit(payload: dict[str, Any], *, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("result") == "PASS" else 1
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            print(f"{key}: {json.dumps(value)}")
        else:
            print(f"{key}: {value}")
    return 0 if payload.get("result") == "PASS" else 1


def status_payload(cwd: Path) -> dict[str, Any]:
    info = effective_concise_mode(cwd)
    return {
        "result": "PASS",
        "effective_mode": info["effective_mode"],
        "effective_source": info["effective_source"],
        "default_mode": info["default_mode"],
        "default_enabled": info["default_enabled"],
        "active_state": info["active_state"],
        "sidecar_path": info["sidecar_path"],
        "sidecar_exists": info["sidecar_exists"],
        "state_path": info["state_path"],
        "state_exists": info["state_exists"],
        "valid_modes": info["valid_modes"],
    }


def doctor_payload(cwd: Path) -> dict[str, Any]:
    status = status_payload(cwd)
    skill_path = find_skill_path(cwd)
    problems: list[str] = []
    quick_fixes: list[str] = []
    if skill_path is None:
        problems.append("shared concise-mode skill not found; runtime will use fallback rules")
        quick_fixes.append("ensure sibling agents_md checkout is available or add skills/concise-mode/SKILL.md")
    if status["effective_mode"] != DEFAULT_CONCISE_MODE and not status["state_exists"] and not status["sidecar_exists"]:
        problems.append("effective concise mode is active without persisted state or sidecar config")
        quick_fixes.append("run /caveman set off then /caveman set <mode> again")
    return {
        "result": "PASS" if not problems else "WARN",
        "status": status,
        "skill_path": skill_path,
        "problems": problems,
        "quick_fixes": quick_fixes,
    }


def run_compress(as_json: bool) -> int:
    command = [sys.executable, str(SCRIPT_DIR / "memory_lifecycle_command.py"), "compress"]
    if as_json:
        command.append("--json")
    completed = subprocess.run(command, check=False, text=True, capture_output=True)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="")
    return int(completed.returncode)


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    args = [arg for arg in argv if arg != "--json"]
    if not args:
        return usage()
    action = args[0].strip().lower()
    cwd = Path.cwd()
    session_id = current_session_id()

    if action == "status" and len(args) == 1:
        return emit(status_payload(cwd), as_json=as_json)
    if action == "doctor" and len(args) == 1:
        return emit(doctor_payload(cwd), as_json=as_json)
    if action == "off" and len(args) == 1:
        if not session_id:
            return emit({"result": "FAIL", "reason": "missing_session_id", "hint": "run /caveman off from an active OpenCode session"}, as_json=as_json)
        return emit({"result": "PASS", "action": "off", **set_active_mode(cwd, "off", source="caveman_command", session_id=session_id)}, as_json=as_json)
    if action in {"lite", "full", "ultra", "review", "commit"} and len(args) == 1:
        if not session_id:
            return emit({"result": "FAIL", "reason": "missing_session_id", "hint": f"run /caveman {action} from an active OpenCode session"}, as_json=as_json)
        return emit({"result": "PASS", "action": "set", **set_active_mode(cwd, action, source="caveman_command", session_id=session_id)}, as_json=as_json)
    if action == "set" and len(args) == 2:
        mode = normalize_mode(args[1])
        if mode != args[1].strip().lower():
            return emit({"result": "FAIL", "reason": "invalid_mode", "valid_modes": list(VALID_CONCISE_MODES)}, as_json=as_json)
        if not session_id:
            return emit({"result": "FAIL", "reason": "missing_session_id", "hint": "run /caveman set <mode> from an active OpenCode session"}, as_json=as_json)
        return emit({"result": "PASS", "action": "set", **set_active_mode(cwd, mode, source="caveman_command", session_id=session_id)}, as_json=as_json)
    if action == "default" and len(args) == 2:
        mode = normalize_mode(args[1])
        if mode not in {"off", "lite", "full", "ultra"}:
            return emit({"result": "FAIL", "reason": "invalid_default_mode", "valid_modes": ["off", "lite", "full", "ultra"]}, as_json=as_json)
        return emit({"result": "PASS", "action": "default", **set_default_mode(cwd, mode, enabled=mode != "off")}, as_json=as_json)
    if action == "compress" and len(args) == 1:
        return run_compress(as_json)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
