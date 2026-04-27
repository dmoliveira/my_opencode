#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from config_layering import load_layered_config, resolve_write_path, save_config


KVFORGE_STATE_PATH = Path.home() / ".kvforge" / "server.json"
KVFORGE_SERVERS_DIR = Path.home() / ".kvforge" / "servers"


def usage() -> int:
    print(
        "usage: /kvforge status [--json] | /kvforge models [--json] | /kvforge connect [--mode <assist|shadow|enforce>] [--name <name>] [--model <provider/model>] [--json]"
    )
    return 2


def emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            print(f"{key}: {json.dumps(value, indent=2)}")
        else:
            print(f"{key}: {value}")


def load_kvforge_state() -> dict[str, Any] | None:
    if not KVFORGE_STATE_PATH.exists():
        return None
    loaded = json.loads(KVFORGE_STATE_PATH.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else None


def load_kvforge_states() -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    current = load_kvforge_state()
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


def status_payload() -> dict[str, Any]:
    state = load_kvforge_state()
    running = state_running(state)
    if not state:
        return {
            "result": "FAIL",
            "reason": "kvforge_state_missing",
            "state_path": str(KVFORGE_STATE_PATH),
            "running": False,
        }
    return {
        "result": "PASS" if running else "WARN",
        "reason": "kvforge_server_running" if running else "kvforge_state_stale",
        "state_path": str(KVFORGE_STATE_PATH),
        "running": running,
        "connection_name": state.get("connection_name"),
        "provider_model": state.get("provider_model"),
        "base_url": state.get("base_url"),
        "served_model_name": state.get("served_model_name"),
        "model": state.get("model"),
        "port": state.get("port"),
    }


def models_payload() -> dict[str, Any]:
    models = []
    for state in load_kvforge_states():
        running = state_running(state)
        models.append(
            {
                "connection_name": state.get("connection_name"),
                "provider_model": state.get("provider_model"),
                "served_model_name": state.get("served_model_name"),
                "source_model": state.get("model"),
                "base_url": state.get("base_url"),
                "running": running,
            }
        )
    models.sort(key=lambda item: (not bool(item.get("running")), str(item.get("connection_name") or "")))
    return {
        "result": "PASS" if models else "FAIL",
        "reason": "kvforge_models_found" if models else "kvforge_models_missing",
        "models": models,
    }


def _parse_flag(argv: list[str], name: str, default: str) -> str:
    if name not in argv:
        return default
    idx = argv.index(name)
    if idx + 1 >= len(argv):
        raise ValueError(f"missing value for {name}")
    return str(argv[idx + 1]).strip()


def connect_payload(argv: list[str]) -> dict[str, Any]:
    mode = _parse_flag(argv, "--mode", "assist")
    if mode not in {"assist", "shadow", "enforce"}:
        raise ValueError("invalid mode")
    requested_name = _parse_flag(argv, "--name", "")
    requested_model = _parse_flag(argv, "--model", "")
    states = load_kvforge_states()
    running_states = [state for state in states if state_running(state)]
    if requested_name:
        selected = next((state for state in running_states if str(state.get("connection_name") or "") == requested_name), None)
    elif requested_model:
        selected = next((state for state in running_states if str(state.get("provider_model") or "") == requested_model), None)
    else:
        current = load_kvforge_state()
        selected = current if state_running(current) else (running_states[0] if len(running_states) == 1 else None)
    if not selected:
        return {
            "result": "FAIL",
            "reason": "kvforge_server_not_running" if not running_states else "kvforge_selection_required",
            "state_path": str(KVFORGE_STATE_PATH),
            "available": [
                {
                    "connection_name": state.get("connection_name"),
                    "provider_model": state.get("provider_model"),
                    "base_url": state.get("base_url"),
                }
                for state in running_states
            ],
        }

    config, _ = load_layered_config()
    write_path = resolve_write_path()
    llm_config = dict(config.get("llmDecisionRuntime") or {})
    connection_name = requested_name or str(selected.get("connection_name") or "kvforge-local")
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
        "result": "PASS",
        "reason": "kvforge_connected",
        "write_path": str(write_path),
        "connection_name": connection_name,
        "model": llm_config["model"],
        "base_url": llm_config["env"]["OPENAI_BASE_URL"],
        "mode": mode,
    }


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help", "help"}:
        return usage()
    as_json = "--json" in argv
    args = [item for item in argv if item != "--json"]
    command = args[0]
    if command == "status":
        emit(status_payload(), as_json=as_json)
        return 0
    if command == "models":
        emit(models_payload(), as_json=as_json)
        return 0
    if command == "connect":
        try:
            emit(connect_payload(args[1:]), as_json=as_json)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        return 0
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
