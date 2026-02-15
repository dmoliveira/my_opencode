#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config_layering import load_layered_config, resolve_write_path, save_config  # type: ignore
from gateway_plugin_bridge import (  # type: ignore
    cleanup_orphan_loop,
    gateway_loop_state_path,
    gateway_plugin_spec,
    load_gateway_loop_state,
    plugin_enabled,
    set_plugin_enabled,
)


# Prints usage for gateway command.
def usage() -> int:
    print(
        "usage: /gateway status [--json] | /gateway enable [--json] | /gateway disable [--json] | /gateway doctor [--json]"
    )
    return 2


# Emits payload in JSON or compact text form.
def emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


# Loads writable layered config data and path.
def load_config() -> tuple[dict[str, Any], Path]:
    config, _ = load_layered_config()
    return config, resolve_write_path()


# Returns gateway plugin package path under local config.
def plugin_dir(home: Path) -> Path:
    return home / ".config" / "opencode" / "my_opencode" / "plugin" / "gateway-core"


# Returns gateway-core hook diagnostics for source and dist artifacts.
def hook_diagnostics(pdir: Path) -> dict[str, Any]:
    src_index = pdir / "src" / "index.ts"
    src_hook_files = [
        pdir / "src" / "hooks" / "autopilot-loop" / "index.ts",
        pdir / "src" / "hooks" / "continuation" / "index.ts",
        pdir / "src" / "hooks" / "safety" / "index.ts",
    ]
    dist_index = pdir / "dist" / "index.js"
    dist_hook_files = [
        pdir / "dist" / "hooks" / "autopilot-loop" / "index.js",
        pdir / "dist" / "hooks" / "continuation" / "index.js",
        pdir / "dist" / "hooks" / "safety" / "index.js",
    ]

    content = ""
    if dist_index.exists():
        try:
            content = dist_index.read_text(encoding="utf-8")
        except OSError:
            content = ""

    autopilot_loop_content = ""
    autopilot_loop_path = pdir / "dist" / "hooks" / "autopilot-loop" / "index.js"
    if autopilot_loop_path.exists():
        try:
            autopilot_loop_content = autopilot_loop_path.read_text(encoding="utf-8")
        except OSError:
            autopilot_loop_content = ""

    continuation_content = ""
    continuation_path = pdir / "dist" / "hooks" / "continuation" / "index.js"
    if continuation_path.exists():
        try:
            continuation_content = continuation_path.read_text(encoding="utf-8")
        except OSError:
            continuation_content = ""

    safety_content = ""
    safety_path = pdir / "dist" / "hooks" / "safety" / "index.js"
    if safety_path.exists():
        try:
            safety_content = safety_path.read_text(encoding="utf-8")
        except OSError:
            safety_content = ""

    return {
        "source_index_exists": src_index.exists(),
        "source_hooks_exist": all(path.exists() for path in src_hook_files),
        "dist_index_exists": dist_index.exists(),
        "dist_hooks_exist": all(path.exists() for path in dist_hook_files),
        "dist_exposes_tool_execute_before": '"tool.execute.before"' in content,
        "dist_exposes_chat_message": '"chat.message"' in content,
        "dist_autopilot_handles_slashcommand": "tool.execute.before"
        in autopilot_loop_content
        and "slashcommand" in autopilot_loop_content,
        "dist_continuation_handles_session_idle": "session.idle"
        in continuation_content,
        "dist_safety_handles_session_deleted": "session.deleted" in safety_content,
        "dist_safety_handles_session_error": "session.error" in safety_content,
    }


# Computes gateway runtime status payload.
def status_payload(
    config: dict[str, Any],
    home: Path,
    cwd: Path,
    *,
    cleanup_orphans: bool = False,
    orphan_max_age_hours: int = 12,
) -> dict[str, Any]:
    pdir = plugin_dir(home)
    cleanup: dict[str, Any] | None = None
    if cleanup_orphans:
        cleanup_path, changed, reason = cleanup_orphan_loop(
            cwd, max_age_hours=orphan_max_age_hours
        )
        cleanup = {
            "attempted": True,
            "changed": changed,
            "reason": reason,
            "state_path": str(cleanup_path) if cleanup_path else None,
        }
    loop_state = load_gateway_loop_state(cwd)
    payload = {
        "result": "PASS",
        "enabled": plugin_enabled(config, home),
        "plugin_spec": gateway_plugin_spec(home),
        "plugin_dir": str(pdir),
        "plugin_dir_exists": pdir.exists(),
        "plugin_dist_exists": (pdir / "dist" / "index.js").exists(),
        "bun_available": shutil.which("bun") is not None,
        "npm_available": shutil.which("npm") is not None,
        "hook_diagnostics": hook_diagnostics(pdir),
        "loop_state_path": str(gateway_loop_state_path(cwd)),
        "loop_state": loop_state if loop_state else None,
    }
    if cleanup is not None:
        payload["orphan_cleanup"] = cleanup
    return payload


# Enables gateway plugin spec in opencode config.
def command_enable(as_json: bool) -> int:
    home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    config, cfg_path = load_config()
    set_plugin_enabled(config, home, True)
    save_config(config, cfg_path)
    payload = status_payload(config, home, Path.cwd())
    payload["config"] = str(cfg_path)
    emit(payload, as_json=as_json)
    return 0


# Disables gateway plugin spec in opencode config.
def command_disable(as_json: bool) -> int:
    home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    config, cfg_path = load_config()
    set_plugin_enabled(config, home, False)
    save_config(config, cfg_path)
    payload = status_payload(config, home, Path.cwd())
    payload["config"] = str(cfg_path)
    emit(payload, as_json=as_json)
    return 0


# Shows gateway plugin status.
def command_status(as_json: bool) -> int:
    home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    config, _ = load_config()
    emit(
        status_payload(config, home, Path.cwd(), cleanup_orphans=True),
        as_json=as_json,
    )
    return 0


# Runs gateway plugin diagnostics with quick fixes.
def command_doctor(as_json: bool) -> int:
    home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    config, _ = load_config()
    status = status_payload(config, home, Path.cwd(), cleanup_orphans=True)

    problems: list[str] = []
    warnings: list[str] = []
    if not status["plugin_dir_exists"]:
        warnings.append("gateway plugin directory is missing")
    if not status["plugin_dist_exists"]:
        warnings.append("gateway plugin is not built (dist/index.js missing)")
    if status["enabled"] and not status["plugin_dist_exists"]:
        problems.append("gateway plugin enabled without built dist assets")
    if status["enabled"] and not status["bun_available"]:
        warnings.append("gateway plugin is enabled but bun is not available")

    hooks_any = status.get("hook_diagnostics")
    hooks = hooks_any if isinstance(hooks_any, dict) else {}
    if hooks and hooks.get("source_index_exists") is not True:
        warnings.append("gateway-core source index is missing")
    if hooks and hooks.get("source_hooks_exist") is not True:
        warnings.append("gateway-core source hook files are incomplete")
    if status["plugin_dist_exists"] and hooks:
        required_dist_flags = [
            "dist_exposes_tool_execute_before",
            "dist_exposes_chat_message",
            "dist_autopilot_handles_slashcommand",
            "dist_continuation_handles_session_idle",
            "dist_safety_handles_session_deleted",
            "dist_safety_handles_session_error",
        ]
        missing = [flag for flag in required_dist_flags if hooks.get(flag) is not True]
        if missing:
            problems.append(
                "gateway-core dist is missing required hook capabilities: "
                + ", ".join(missing)
            )

    report = {
        "result": "PASS" if not problems else "FAIL",
        "status": status,
        "warnings": warnings,
        "problems": problems,
        "quick_fixes": [
            "/gateway disable",
            "/gateway enable",
            "run npm run build in plugin/gateway-core",
            "install bun if file plugins must auto-install",
        ],
    }
    emit(report, as_json=as_json)
    return 0 if not problems else 1


# Dispatches gateway command subcommands.
def main(argv: list[str]) -> int:
    args = list(argv)
    as_json = False
    if "--json" in args:
        args.remove("--json")
        as_json = True
    if not args:
        return command_status(as_json)
    cmd = args.pop(0)
    if args:
        return usage()
    if cmd in {"help", "--help", "-h"}:
        return usage()
    if cmd == "status":
        return command_status(as_json)
    if cmd == "enable":
        return command_enable(as_json)
    if cmd == "disable":
        return command_disable(as_json)
    if cmd == "doctor":
        return command_doctor(as_json)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
