#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from config_layering import _load_json_or_jsonc, save_config

KVFORGE_STATE_PATH = Path.home() / ".kvforge" / "server.json"
KVFORGE_SERVERS_DIR = Path.home() / ".kvforge" / "servers"
KVFORGE_PROVIDER_ID = "kvforge"
KVFORGE_PROVIDER_NAME = "KVForge"
KVFORGE_PROVIDER_PACKAGE = "@ai-sdk/openai-compatible"
KVFORGE_MODEL_LIMIT_HEADROOM = 1024


def load_current_state() -> dict[str, Any] | None:
    if not KVFORGE_STATE_PATH.exists():
        return None
    try:
        loaded = json.loads(KVFORGE_STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
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


def selected_served_model_name(state: dict[str, Any]) -> str:
    served_model_name = str(state.get("served_model_name") or "").strip()
    if served_model_name:
        return served_model_name
    provider_model = str(state.get("provider_model") or "").strip()
    if "/" in provider_model:
        return provider_model.split("/", 1)[1]
    return provider_model or "gpt-5.4-mini"


def selected_provider_model(state: dict[str, Any]) -> str:
    provider_model = str(state.get("provider_model") or "").strip()
    if provider_model:
        return provider_model
    return f"openai/{selected_served_model_name(state)}"


def selected_native_model(state: dict[str, Any]) -> str:
    return f"{KVFORGE_PROVIDER_ID}/{selected_served_model_name(state)}"


def _models_endpoint(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/models"


def load_live_model_limit(state: dict[str, Any]) -> dict[str, int]:
    base_url = str(state.get("base_url") or "").strip()
    served_model_name = selected_served_model_name(state)
    if not base_url or not served_model_name:
        return {}
    try:
        with urllib.request.urlopen(_models_endpoint(base_url), timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return {}
    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return {}
    selected = next(
        (
            item
            for item in models
            if isinstance(item, dict) and str(item.get("id") or "").strip() == served_model_name
        ),
        None,
    )
    if not isinstance(selected, dict):
        return {}
    max_model_len = selected.get("max_model_len")
    if not isinstance(max_model_len, int) or max_model_len <= 0:
        return {}
    safe_output_limit = max(256, max_model_len - KVFORGE_MODEL_LIMIT_HEADROOM)
    return {
        "context": max_model_len,
        "output": safe_output_limit,
    }


def native_write_path(env_var: str = "OPENCODE_CONFIG_PATH") -> Path:
    env_path = os.environ.get(env_var, "").strip()
    if env_path:
        return Path(env_path).expanduser()
    return Path("~/.config/opencode/opencode.json").expanduser()


def load_native_config(path: Path) -> dict[str, Any]:
    if path.exists():
        return _load_json_or_jsonc(path)
    return {"$schema": "https://opencode.ai/config.json"}


def gateway_sidecar_write_path() -> Path:
    env_path = os.environ.get("MY_OPENCODE_GATEWAY_CONFIG_PATH", "").strip()
    if env_path:
        return Path(env_path).expanduser()
    local_path = Path.cwd() / ".opencode" / "gateway-core.config.json"
    if local_path.exists():
        return local_path
    return Path("~/.config/opencode/my_opencode/gateway-core.config.json").expanduser()


def load_gateway_sidecar_config(path: Path) -> dict[str, Any]:
    if path.exists():
        return _load_json_or_jsonc(path)
    return {}


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
            (
                state
                for state in running_states
                if requested_model
                in {
                    str(state.get("provider_model") or "").strip(),
                    selected_native_model(state),
                    selected_served_model_name(state),
                }
            ),
            None,
        )
    else:
        current = load_current_state()
        selected = current if state_running(current) else (running_states[0] if len(running_states) == 1 else None)
    return selected, running_states


def write_gateway_connection(selected: dict[str, Any], *, mode: str, connection_name: str) -> dict[str, Any]:
    write_path = native_write_path()
    config = load_native_config(write_path)
    gateway_write_path = gateway_sidecar_write_path()
    gateway_config = load_gateway_sidecar_config(gateway_write_path)
    provider_model = selected_provider_model(selected)
    native_model = selected_native_model(selected)
    served_model_name = selected_served_model_name(selected)
    base_url = str(selected.get("base_url") or "http://127.0.0.1:8000/v1")
    live_limit = load_live_model_limit(selected)

    provider_config = dict(config.get("provider") or {})
    kvforge_provider = dict(provider_config.get(KVFORGE_PROVIDER_ID) or {})
    kvforge_options = dict(kvforge_provider.get("options") or {})
    kvforge_options.update(
        {
            "baseURL": base_url,
            "apiKey": str(kvforge_options.get("apiKey") or "dummy"),
        }
    )
    kvforge_models = dict(kvforge_provider.get("models") or {})
    kvforge_models[served_model_name] = {
        **dict(kvforge_models.get(served_model_name) or {}),
        "name": served_model_name,
        **({"limit": live_limit} if live_limit else {}),
    }
    kvforge_provider.update(
        {
            "name": str(kvforge_provider.get("name") or KVFORGE_PROVIDER_NAME),
            "npm": str(kvforge_provider.get("npm") or KVFORGE_PROVIDER_PACKAGE),
            "options": kvforge_options,
            "models": kvforge_models,
        }
    )
    provider_config[KVFORGE_PROVIDER_ID] = kvforge_provider
    config["provider"] = provider_config

    config["model"] = native_model
    config.pop("llmDecisionRuntime", None)
    config.pop("kvforge", None)

    existing_env = dict(gateway_config.get("llmDecisionRuntime", {}).get("env") or {})
    cleaned_env = {
        key: value
        for key, value in existing_env.items()
        if key not in {"OPENAI_BASE_URL", "OPENAI_API_KEY"}
    }

    llm_config = dict(gateway_config.get("llmDecisionRuntime") or {})
    llm_config.update(
        {
            "enabled": True,
            "mode": mode,
            "command": "opencode",
            "model": native_model,
            "allowStandaloneOpencode": True,
            "env": cleaned_env,
        }
    )
    gateway_config["llmDecisionRuntime"] = llm_config
    save_config(config, write_path)
    save_config(gateway_config, gateway_write_path)
    return {
        "write_path": str(write_path),
        "gateway_write_path": str(gateway_write_path),
        "connection_name": connection_name,
        "model": native_model,
        "provider_model": provider_model,
        "served_model_name": served_model_name,
        "base_url": base_url,
        "mode": mode,
    }
