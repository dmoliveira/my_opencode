#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from config_layering import load_layered_config, resolve_write_path, save_config

KVFORGE_STATE_PATH = Path.home() / ".kvforge" / "server.json"
KVFORGE_SERVERS_DIR = Path.home() / ".kvforge" / "servers"


def load_current_state() -> dict[str, Any] | None:
    if not KVFORGE_STATE_PATH.exists():
        return None
    loaded = json.loads(KVFORGE_STATE_PATH.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else None


def load_states() -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    current = load_current_state()
    if current:
        states.append(current)
    if KVFORGE_SERVERS_DIR.exists():
        for path in sorted(KVFORGE_SERVERS_DIR.glob("*.json")):
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(loaded, dict):
                states.append(loaded)
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for state in states:
        key = (
            str(state.get("connection_name") or "").strip(),
            str(state.get("base_url") or "").strip(),
        )
        deduped[key] = state
    return list(deduped.values())


def state_running(state: dict[str, Any] | None) -> bool:
    if not state:
        return False
    pid = state.get("pid")
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def select_state(*, requested_name: str = "", requested_model: str = "") -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    states = load_states()
    running_states = [state for state in states if state_running(state)]
    if requested_name:
        selected = next(
            (state for state in running_states if str(state.get("connection_name") or "") == requested_name),
            None,
        )
    elif requested_model:
        selected = next(
            (state for state in running_states if str(state.get("provider_model") or "") == requested_model),
            None,
        )
    else:
        current = load_current_state()
        selected = current if state_running(current) else (running_states[0] if len(running_states) == 1 else None)
    return selected, running_states


def write_gateway_connection(selected: dict[str, Any], *, mode: str, connection_name: str) -> dict[str, Any]:
    config, _ = load_layered_config()
    write_path = resolve_write_path()
    llm_config = dict(config.get("llmDecisionRuntime") or {})
    llm_config.update(
        {
            "enabled": True,
            "mode": mode,
            "command": "opencode",
            "model": str(selected.get("provider_model") or "openai/gpt-5.4-mini"),
            "allowStandaloneOpencode": True,
            "env": {
                "OPENAI_BASE_URL": str(selected.get("base_url") or "http://127.0.0.1:8000/v1"),
                "OPENAI_API_KEY": "dummy",
            },
        }
    )
    config["llmDecisionRuntime"] = llm_config
    config["kvforge"] = {
        "connectionName": connection_name,
        "lastConnectedBaseUrl": llm_config["env"]["OPENAI_BASE_URL"],
        "lastConnectedModel": llm_config["model"],
    }
    save_config(config, write_path)
    return {
        "write_path": str(write_path),
        "connection_name": connection_name,
        "model": llm_config["model"],
        "base_url": llm_config["env"]["OPENAI_BASE_URL"],
        "mode": mode,
    }
