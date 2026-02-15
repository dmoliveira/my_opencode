#!/usr/bin/env python3

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


# Returns current UTC timestamp in ISO-8601 Z format.
def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# Returns canonical local file plugin spec for gateway-core.
def gateway_plugin_spec(home: Path) -> str:
    return f"file:{home / '.config' / 'opencode' / 'my_opencode' / 'plugin' / 'gateway-core'}"


# Returns true when gateway plugin spec is enabled in config.
def plugin_enabled(config: dict[str, Any], home: Path) -> bool:
    plugins_any = config.get("plugin")
    plugins = plugins_any if isinstance(plugins_any, list) else []
    spec = gateway_plugin_spec(home)
    return any(isinstance(item, str) and item == spec for item in plugins)


# Enables or disables gateway plugin spec in config plugin list.
def set_plugin_enabled(config: dict[str, Any], home: Path, enabled: bool) -> None:
    plugins_any = config.get("plugin")
    plugins = (
        [item for item in plugins_any if isinstance(item, str)]
        if isinstance(plugins_any, list)
        else []
    )
    spec = gateway_plugin_spec(home)
    filtered = [item for item in plugins if item != spec]
    if enabled:
        filtered.insert(0, spec)
    config["plugin"] = filtered


# Returns gateway loop bridge state file for current working directory.
def gateway_loop_state_path(cwd: Path) -> Path:
    return cwd / ".opencode" / "gateway-core.state.json"


# Loads gateway loop bridge state if available.
def load_gateway_loop_state(cwd: Path) -> dict[str, Any]:
    path = gateway_loop_state_path(cwd)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


# Persists gateway loop bridge state to disk.
def save_gateway_loop_state(cwd: Path, state: dict[str, Any]) -> Path:
    path = gateway_loop_state_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return path


# Initializes or refreshes active gateway loop bridge state.
def bridge_start_loop(cwd: Path, run: dict[str, Any]) -> Path:
    objective_any = run.get("objective")
    objective = objective_any if isinstance(objective_any, dict) else {}
    state = {
        "activeLoop": {
            "active": True,
            "sessionId": f"bridge-{run.get('run_id', 'unknown')}",
            "objective": str(objective.get("goal") or "continue objective"),
            "completionMode": str(objective.get("completion_mode") or "promise"),
            "completionPromise": str(objective.get("completion_promise") or "DONE"),
            "iteration": 1,
            "maxIterations": 100,
            "startedAt": str(run.get("started_at") or now_iso()),
        },
        "lastUpdatedAt": now_iso(),
        "source": "python-command-bridge",
    }
    return save_gateway_loop_state(cwd, state)


# Marks bridge loop state inactive while preserving metadata.
def bridge_stop_loop(cwd: Path) -> Path | None:
    state = load_gateway_loop_state(cwd)
    if not state:
        return None
    active_any = state.get("activeLoop")
    active = active_any if isinstance(active_any, dict) else {}
    if active:
        active["active"] = False
        state["activeLoop"] = active
    state["lastUpdatedAt"] = now_iso()
    return save_gateway_loop_state(cwd, state)
