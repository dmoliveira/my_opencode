#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config_layering import load_layered_config, resolve_write_path, save_config  # type: ignore
from gateway_reason_codes import (  # type: ignore
    BRIDGE_STATE_IGNORED_IN_PLUGIN_MODE,
    GATEWAY_PLUGIN_DISABLED,
    GATEWAY_PLUGIN_NOT_READY,
    GATEWAY_PLUGIN_READY,
    GATEWAY_PLUGIN_RUNTIME_UNAVAILABLE,
    LOOP_STATE_AVAILABLE,
)
from gateway_plugin_bridge import (  # type: ignore
    cleanup_orphan_loop,
    gateway_plugin_entries,
    gateway_loop_state_path,
    gateway_plugin_spec,
    load_gateway_loop_state,
    plugin_enabled,
    set_plugin_enabled,
)


# Prints usage for gateway command.
def usage() -> int:
    print(
        "usage: /gateway status [--json] | /gateway enable [--force] [--json] | /gateway disable [--json] | /gateway doctor [--json] | /gateway tune memory [--json]"
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


def gateway_event_audit_enabled() -> bool:
    raw = os.environ.get("MY_OPENCODE_GATEWAY_EVENT_AUDIT", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def gateway_event_audit_path(cwd: Path) -> Path:
    raw = os.environ.get("MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH", "").strip()
    if raw:
        return Path(raw).expanduser()
    return cwd / ".opencode" / "gateway-events.jsonl"


def gateway_event_counters(cwd: Path) -> dict[str, Any]:
    path = gateway_event_audit_path(cwd)
    if not path.exists():
        return {
            "audit_path": str(path),
            "total_events": 0,
            "context_warnings_triggered": 0,
            "compactions_triggered": 0,
            "global_process_pressure_warnings": 0,
            "recent_window_minutes": 30,
            "recent_context_warnings": 0,
            "recent_compactions": 0,
            "recent_global_process_pressure_warnings": 0,
            "last_triggered_at": None,
        }

    total_events = 0
    context_warnings = 0
    compactions = 0
    global_pressure_warnings = 0
    recent_context_warnings = 0
    recent_compactions = 0
    recent_global_pressure_warnings = 0
    recent_window_minutes = 30
    now_utc = datetime.now(UTC)
    last_triggered_at: str | None = None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                total_events += 1
                reason_code = str(payload.get("reason_code") or "")
                event_time: datetime | None = None
                for key in ("timestamp", "ts", "time"):
                    event_time = parse_iso(payload.get(key))
                    if event_time is not None:
                        break
                in_recent_window = False
                if event_time is not None:
                    delta_seconds = (now_utc - event_time).total_seconds()
                    in_recent_window = (
                        0 <= delta_seconds <= (recent_window_minutes * 60)
                    )
                if reason_code == "context_warning_appended":
                    context_warnings += 1
                    if in_recent_window:
                        recent_context_warnings += 1
                elif reason_code == "session_compacted_preemptively":
                    compactions += 1
                    if in_recent_window:
                        recent_compactions += 1
                elif reason_code == "global_process_pressure_warning_appended":
                    global_pressure_warnings += 1
                    if in_recent_window:
                        recent_global_pressure_warnings += 1
                if reason_code in {
                    "context_warning_appended",
                    "session_compacted_preemptively",
                    "global_process_pressure_warning_appended",
                }:
                    if event_time is not None:
                        last_triggered_at = event_time.isoformat()
                    else:
                        for key in ("timestamp", "ts", "time"):
                            value = payload.get(key)
                            if isinstance(value, str) and value.strip():
                                last_triggered_at = value.strip()
                                break
    except (OSError, UnicodeDecodeError):
        return {
            "audit_path": str(path),
            "total_events": 0,
            "context_warnings_triggered": 0,
            "compactions_triggered": 0,
            "recent_window_minutes": recent_window_minutes,
            "recent_context_warnings": 0,
            "recent_compactions": 0,
            "global_process_pressure_warnings": 0,
            "recent_global_process_pressure_warnings": 0,
            "last_triggered_at": None,
            "read_error": True,
        }

    return {
        "audit_path": str(path),
        "total_events": total_events,
        "context_warnings_triggered": context_warnings,
        "compactions_triggered": compactions,
        "recent_window_minutes": recent_window_minutes,
        "recent_context_warnings": recent_context_warnings,
        "recent_compactions": recent_compactions,
        "global_process_pressure_warnings": global_pressure_warnings,
        "recent_global_process_pressure_warnings": recent_global_pressure_warnings,
        "last_triggered_at": last_triggered_at,
    }


def parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def runtime_staleness(home: Path) -> dict[str, Any]:
    runtime_path = (
        home
        / ".config"
        / "opencode"
        / "my_opencode"
        / "runtime"
        / "autopilot_runtime.json"
    )
    if not runtime_path.exists():
        return {
            "exists": False,
            "path": str(runtime_path),
            "status": None,
            "is_stale_running": False,
            "age_minutes": None,
            "blockers": [],
        }
    try:
        payload = json.loads(runtime_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "exists": True,
            "path": str(runtime_path),
            "status": None,
            "is_stale_running": False,
            "age_minutes": None,
            "blockers": [],
            "read_error": True,
        }
    runtime = payload if isinstance(payload, dict) else {}
    status = str(runtime.get("status") or "").strip().lower()
    blockers_any = runtime.get("blockers")
    blockers = blockers_any if isinstance(blockers_any, list) else []
    updated_at = parse_iso(runtime.get("updated_at"))
    age_minutes: int | None = None
    if updated_at is not None:
        age_minutes = int((datetime.now(UTC) - updated_at).total_seconds() / 60)
    is_stale_running = (
        status == "running" and age_minutes is not None and age_minutes >= 30
    )
    return {
        "exists": True,
        "path": str(runtime_path),
        "status": status or None,
        "is_stale_running": is_stale_running,
        "age_minutes": age_minutes,
        "blockers": [str(item) for item in blockers if isinstance(item, str)],
    }


def process_pressure() -> dict[str, Any]:
    def is_opencode_command(command: str) -> bool:
        lowered = command.strip().lower()
        if not lowered:
            return False
        return bool(re.search(r"(^|[\s/])opencode(\s|$)", lowered))

    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,rss=,command="],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except Exception:
        return {
            "sampled": False,
            "opencode_process_count": 0,
            "continue_process_count": 0,
            "max_rss_mb": 0,
            "high_rss": [],
        }
    if result.returncode != 0:
        return {
            "sampled": False,
            "opencode_process_count": 0,
            "continue_process_count": 0,
            "max_rss_mb": 0,
            "high_rss": [],
        }

    opencode_process_count = 0
    continue_process_count = 0
    max_rss_kb = 0
    high_rss: list[dict[str, Any]] = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            pid_text, rss_text, command = line.split(maxsplit=2)
        except ValueError:
            continue
        lowered = command.lower()
        if not is_opencode_command(command):
            continue
        opencode_process_count += 1
        if "--continue" in lowered:
            continue_process_count += 1
        try:
            rss_kb = int(rss_text)
        except ValueError:
            rss_kb = 0
        if rss_kb > max_rss_kb:
            max_rss_kb = rss_kb
        if rss_kb >= 1_000_000:
            command_preview = command.strip()
            if command_preview:
                try:
                    command_preview = shlex.join(shlex.split(command_preview)[:8])
                except ValueError:
                    command_preview = command_preview[:180]
            high_rss.append(
                {
                    "pid": int(pid_text),
                    "rss_mb": round(rss_kb / 1024, 1),
                    "command": command_preview,
                }
            )

    return {
        "sampled": True,
        "opencode_process_count": opencode_process_count,
        "continue_process_count": continue_process_count,
        "max_rss_mb": round(max_rss_kb / 1024, 1),
        "high_rss": high_rss[:5],
    }


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
        "dist_exposes_command_execute_before": '"command.execute.before"' in content,
        "dist_exposes_chat_message": '"chat.message"' in content,
        "dist_exposes_messages_transform": '"experimental.chat.messages.transform"'
        in content,
        "dist_autopilot_handles_slashcommand": "tool.execute.before"
        in autopilot_loop_content
        and "slashcommand" in autopilot_loop_content,
        "dist_continuation_handles_session_idle": "session.idle"
        in continuation_content,
        "dist_safety_handles_session_deleted": "session.deleted" in safety_content,
        "dist_safety_handles_session_error": "session.error" in safety_content,
    }


# Resolves effective bun availability with optional deterministic overrides.
def bun_runtime_available() -> bool:
    forced = (
        os.environ.get("MY_OPENCODE_GATEWAY_FORCE_BUN_AVAILABLE", "").strip().lower()
    )
    if forced in {"1", "true", "yes", "on"}:
        return True
    if forced in {"0", "false", "no", "off"}:
        return False
    return shutil.which("bun") is not None


# Resolves active gateway runtime mode and deterministic reason code.
def gateway_runtime_mode(
    *, enabled: bool, bun_available: bool, hooks: dict[str, Any]
) -> dict[str, Any]:
    required_dist_flags = [
        "dist_exposes_tool_execute_before",
        "dist_exposes_command_execute_before",
        "dist_exposes_chat_message",
        "dist_exposes_messages_transform",
        "dist_autopilot_handles_slashcommand",
        "dist_continuation_handles_session_idle",
        "dist_safety_handles_session_deleted",
        "dist_safety_handles_session_error",
    ]
    missing = [flag for flag in required_dist_flags if hooks.get(flag) is not True]
    plugin_ready = (
        enabled
        and bun_available
        and hooks.get("dist_index_exists") is True
        and not missing
    )
    mode = "plugin_gateway" if plugin_ready else "python_command_bridge"
    reason_code = GATEWAY_PLUGIN_READY
    if not enabled:
        reason_code = GATEWAY_PLUGIN_DISABLED
    elif not bun_available:
        reason_code = GATEWAY_PLUGIN_RUNTIME_UNAVAILABLE
    elif not plugin_ready:
        reason_code = GATEWAY_PLUGIN_NOT_READY
    return {
        "mode": mode,
        "reason_code": reason_code,
        "missing_hook_capabilities": missing,
    }


# Returns loop state filtered for active runtime mode semantics.
def mode_loop_state(
    runtime_mode: str, loop_state: dict[str, Any]
) -> tuple[dict[str, Any] | None, str]:
    source = str(loop_state.get("source") or "") if isinstance(loop_state, dict) else ""
    if runtime_mode == "plugin_gateway" and source == "python-command-bridge":
        return None, BRIDGE_STATE_IGNORED_IN_PLUGIN_MODE
    if loop_state:
        return loop_state, LOOP_STATE_AVAILABLE
    return None, "state_missing"


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
    enabled = plugin_enabled(config, home)
    bun_available = bun_runtime_available()
    hooks = hook_diagnostics(pdir)
    runtime_mode = gateway_runtime_mode(
        enabled=enabled,
        bun_available=bun_available,
        hooks=hooks,
    )
    filtered_loop_state, loop_state_reason = mode_loop_state(
        runtime_mode["mode"], loop_state
    )
    gateway_entries = gateway_plugin_entries(config, home)
    payload = {
        "result": "PASS",
        "enabled": enabled,
        "plugin_spec": gateway_plugin_spec(home),
        "plugin_entry_count": len(gateway_entries),
        "plugin_entries": gateway_entries,
        "plugin_dir": str(pdir),
        "plugin_dir_exists": pdir.exists(),
        "plugin_dist_exists": (pdir / "dist" / "index.js").exists(),
        "bun_available": bun_available,
        "npm_available": shutil.which("npm") is not None,
        "hook_diagnostics": hooks,
        "runtime_mode": runtime_mode["mode"],
        "runtime_reason_code": runtime_mode["reason_code"],
        "missing_hook_capabilities": runtime_mode["missing_hook_capabilities"],
        "loop_state_path": str(gateway_loop_state_path(cwd)),
        "loop_state": filtered_loop_state,
        "loop_state_reason_code": loop_state_reason,
        "event_audit_enabled": gateway_event_audit_enabled(),
        "event_audit_path": str(gateway_event_audit_path(cwd)),
        "event_audit_exists": gateway_event_audit_path(cwd).exists(),
        "guard_event_counters": gateway_event_counters(cwd),
        "runtime_staleness": runtime_staleness(home),
        "process_pressure": process_pressure(),
    }
    if cleanup is not None:
        payload["orphan_cleanup"] = cleanup
    return payload


# Ensures Bun/OpenCode compatibility aliases for local file plugins.
def ensure_file_plugin_compat(home: Path, pdir: Path) -> dict[str, Any]:
    if not pdir.exists():
        return {"applied": False, "reason": "plugin_dir_missing"}
    if not bun_runtime_available():
        return {"applied": False, "reason": "bun_unavailable"}

    alias_path = pdir.parent / "gateway-core@latest"
    cache_home = Path(
        os.environ.get("XDG_CACHE_HOME", str(home / ".cache"))
    ).expanduser()
    cache_plugin_path = (
        cache_home
        / "opencode"
        / "node_modules"
        / f"file:{pdir.parent}"
        / "gateway-core"
    )

    alias_path.parent.mkdir(parents=True, exist_ok=True)
    cache_plugin_path.parent.mkdir(parents=True, exist_ok=True)
    alias_path.unlink(missing_ok=True)
    cache_plugin_path.unlink(missing_ok=True)
    alias_path.symlink_to(pdir)
    cache_plugin_path.symlink_to(pdir)

    return {
        "applied": True,
        "reason": "ok",
        "latest_alias_path": str(alias_path),
        "cache_alias_path": str(cache_plugin_path),
    }


# Returns hard safety problems that should block non-forced enable.
def enable_safety_problems(status: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if status.get("plugin_dir_exists") is not True:
        problems.append("gateway plugin directory is missing")
    if status.get("plugin_dist_exists") is not True:
        problems.append("gateway plugin dist build is missing")
    if status.get("bun_available") is not True:
        problems.append("bun runtime is unavailable")
    hooks_any = status.get("hook_diagnostics")
    hooks = hooks_any if isinstance(hooks_any, dict) else {}
    required_dist_flags = [
        "dist_exposes_tool_execute_before",
        "dist_exposes_command_execute_before",
        "dist_exposes_chat_message",
        "dist_exposes_messages_transform",
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
    return problems


# Enables gateway plugin spec in opencode config.
def command_enable(as_json: bool, *, force: bool = False) -> int:
    home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    config, cfg_path = load_config()
    set_plugin_enabled(config, home, True)
    save_config(config, cfg_path)
    payload = status_payload(config, home, Path.cwd())
    payload["compat"] = ensure_file_plugin_compat(home, plugin_dir(home))
    payload["config"] = str(cfg_path)
    problems = enable_safety_problems(payload)
    if problems and not force:
        set_plugin_enabled(config, home, False)
        save_config(config, cfg_path)
        fallback = status_payload(config, home, Path.cwd())
        fallback["result"] = "FAIL"
        fallback["reason_code"] = "gateway_enable_blocked_for_safety"
        fallback["problems"] = problems
        fallback["config"] = str(cfg_path)
        fallback["quick_fixes"] = [
            "install bun and run /gateway doctor",
            "run npm run build in plugin/gateway-core",
            "run /gateway enable --force to bypass safeguard",
        ]
        emit(fallback, as_json=as_json)
        return 1
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
    if status.get("bun_available") is True and status.get("enabled") is not True:
        warnings.append(
            "gateway plugin runtime is available but disabled; enable for plugin-first mode"
        )
    plugin_entry_count = int(status.get("plugin_entry_count") or 0)
    if plugin_entry_count > 1:
        message = "gateway plugin is configured multiple times; keep one canonical file: entry to avoid duplicate hook registration"
        if status.get("enabled") is True:
            problems.append(message)
        else:
            warnings.append(message)

    runtime_stale_any = status.get("runtime_staleness")
    runtime_stale = runtime_stale_any if isinstance(runtime_stale_any, dict) else {}
    if runtime_stale.get("is_stale_running") is True:
        age_minutes = runtime_stale.get("age_minutes")
        warnings.append(
            f"autopilot runtime appears stale in running state ({age_minutes} minutes since update); consider /autopilot pause then /autopilot status"
        )
    blockers_any = runtime_stale.get("blockers")
    blockers = blockers_any if isinstance(blockers_any, list) else []
    if blockers and runtime_stale.get("status") == "running":
        warnings.append(
            "autopilot runtime is running with blockers present; inspect /autopilot report before continuing"
        )

    process_pressure_any = status.get("process_pressure")
    process_pressure_status = (
        process_pressure_any if isinstance(process_pressure_any, dict) else {}
    )
    continue_count = int(process_pressure_status.get("continue_process_count") or 0)
    opencode_count = int(process_pressure_status.get("opencode_process_count") or 0)
    max_rss_mb = float(process_pressure_status.get("max_rss_mb") or 0)
    high_rss_any = process_pressure_status.get("high_rss")
    high_rss = high_rss_any if isinstance(high_rss_any, list) else []
    if continue_count >= 3:
        warnings.append(
            f"detected {continue_count} concurrent opencode --continue processes; this can accelerate memory pressure"
        )
    if opencode_count >= 8:
        warnings.append(
            f"detected {opencode_count} concurrent opencode-related processes; consider pruning stale sessions"
        )
    if max_rss_mb >= 1400 or high_rss:
        warnings.append(
            "detected high RSS opencode process(es); capture /gateway status --json baseline and reduce concurrent long-lived sessions"
        )

    hooks_any = status.get("hook_diagnostics")
    hooks = hooks_any if isinstance(hooks_any, dict) else {}
    if hooks and hooks.get("source_index_exists") is not True:
        warnings.append("gateway-core source index is missing")
    if hooks and hooks.get("source_hooks_exist") is not True:
        warnings.append("gateway-core source hook files are incomplete")
    if status["plugin_dist_exists"] and hooks:
        required_dist_flags = [
            "dist_exposes_tool_execute_before",
            "dist_exposes_command_execute_before",
            "dist_exposes_chat_message",
            "dist_exposes_messages_transform",
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
            "dedupe gateway plugin entries in config to a single file:<...>/gateway-core spec",
            "run /autopilot report to inspect blockers and stale runtime status",
        ],
    }
    emit(report, as_json=as_json)
    return 0 if not problems else 1


def command_tune_memory(as_json: bool) -> int:
    home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    config, _ = load_config()
    status = status_payload(config, home, Path.cwd(), cleanup_orphans=True)
    counters_any = status.get("guard_event_counters")
    counters = counters_any if isinstance(counters_any, dict) else {}
    process_any = status.get("process_pressure")
    process = process_any if isinstance(process_any, dict) else {}

    warnings_count = int(counters.get("recent_context_warnings") or 0)
    compactions_count = int(counters.get("recent_compactions") or 0)
    global_pressure_count = int(
        counters.get("recent_global_process_pressure_warnings") or 0
    )
    continue_count = int(process.get("continue_process_count") or 0)
    audit_enabled = status.get("event_audit_enabled") is True

    current = {
        "contextWindowMonitor": config.get("contextWindowMonitor", {}),
        "preemptiveCompaction": config.get("preemptiveCompaction", {}),
        "globalProcessPressure": config.get("globalProcessPressure", {}),
    }
    recommended = {
        "contextWindowMonitor": {
            "warningThreshold": 0.72,
            "reminderCooldownToolCalls": 14,
            "minTokenDeltaForReminder": 30000,
            "defaultContextLimitTokens": 128000,
            "guardMarkerMode": "both",
            "guardVerbosity": "normal",
            "maxSessionStateEntries": 512,
        },
        "preemptiveCompaction": {
            "warningThreshold": 0.8,
            "compactionCooldownToolCalls": 12,
            "minTokenDeltaForCompaction": 40000,
            "defaultContextLimitTokens": 200000,
            "guardMarkerMode": "both",
            "guardVerbosity": "normal",
            "maxSessionStateEntries": 512,
        },
        "globalProcessPressure": {
            "enabled": True,
            "checkCooldownToolCalls": 3,
            "reminderCooldownToolCalls": 6,
            "warningContinueSessions": 5,
            "warningOpencodeProcesses": 10,
            "warningMaxRssMb": 1400,
            "guardMarkerMode": "both",
            "guardVerbosity": "normal",
            "maxSessionStateEntries": 1024,
        },
    }
    rationale: list[str] = [
        "keep guard markers trigger-only to avoid steady-state noise",
        "use dual marker mode for Nerd Font + plain fallback readability",
        "cap per-session state maps to limit long-runtime memory growth",
    ]
    if not audit_enabled:
        rationale.append(
            "event audit is disabled; recent trigger counters may be incomplete"
        )
    if warnings_count >= 5:
        rationale.append(
            "high warning frequency in recent window; increase reminder cooldown or token delta"
        )
    if compactions_count >= 3:
        rationale.append(
            "frequent compactions in recent window; increase compaction cooldown and minimum token delta"
        )
    if global_pressure_count >= 3:
        rationale.append(
            "global process pressure repeatedly hit recent thresholds; many concurrent sessions are saturating memory"
        )
    if continue_count >= 3:
        rationale.append(
            "multiple concurrent --continue sessions detected; prune stale sessions to reduce pressure"
        )

    payload = {
        "result": "PASS",
        "profile": "memory-balanced",
        "status_snapshot": {
            "runtime_mode": status.get("runtime_mode"),
            "process_pressure": process,
            "guard_event_counters": counters,
        },
        "current": current,
        "recommended": recommended,
        "rationale": rationale,
        "next_steps": [
            "apply recommended values under contextWindowMonitor and preemptiveCompaction",
            "run /gateway status --json and /gateway doctor --json",
            "collect 20-30 minute baseline with MY_OPENCODE_GATEWAY_EVENT_AUDIT=1",
        ],
    }
    emit(payload, as_json=as_json)
    return 0


# Dispatches gateway command subcommands.
def main(argv: list[str]) -> int:
    args = list(argv)
    as_json = False
    force = False
    if "--json" in args:
        args.remove("--json")
        as_json = True
    if "--force" in args:
        args.remove("--force")
        force = True
    if not args:
        return command_status(as_json)
    cmd = args.pop(0)
    if cmd in {"help", "--help", "-h"}:
        return usage()
    if cmd == "tune":
        if len(args) == 1 and args[0] == "memory":
            return command_tune_memory(as_json)
        return usage()
    if args:
        return usage()
    if cmd == "status":
        return command_status(as_json)
    if cmd == "enable":
        return command_enable(as_json, force=force)
    if cmd == "disable":
        return command_disable(as_json)
    if cmd == "doctor":
        return command_doctor(as_json)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
