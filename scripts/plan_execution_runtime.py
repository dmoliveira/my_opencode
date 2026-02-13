#!/usr/bin/env python3

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from config_layering import save_config as save_config_file


SECTION = "plan_execution"
RUNTIME_ENV_VAR = "MY_OPENCODE_PLAN_RUNTIME_PATH"
LEGACY_CONFIG_ENV_VAR = "OPENCODE_CONFIG_PATH"


def _runtime_path(write_path: Path) -> Path:
    override = os.environ.get(RUNTIME_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()
    return write_path.parent / "my_opencode" / "runtime" / "plan_execution.json"


def _load_runtime_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_plan_execution_state(
    config: dict[str, Any], write_path: Path
) -> tuple[dict[str, Any], Path]:
    runtime_path = _runtime_path(write_path)
    runtime = _load_runtime_file(runtime_path)

    legacy = config.get(SECTION)
    if isinstance(legacy, dict):
        # Preserve test compatibility when OPENCODE_CONFIG_PATH is explicitly set.
        if os.environ.get(LEGACY_CONFIG_ENV_VAR, "").strip() or not runtime:
            runtime = legacy

    return runtime, runtime_path


def save_plan_execution_state(
    config: dict[str, Any], write_path: Path, runtime: dict[str, Any]
) -> Path:
    runtime_path = _runtime_path(write_path)
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8")

    legacy_env_path = os.environ.get(LEGACY_CONFIG_ENV_VAR, "").strip()
    if legacy_env_path:
        config[SECTION] = runtime
        save_config_file(config, write_path)
        return runtime_path

    if SECTION in config:
        del config[SECTION]
        save_config_file(config, write_path)

    return runtime_path
