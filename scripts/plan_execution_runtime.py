#!/usr/bin/env python3

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from config_layering import (
    ConfigFileParticipant,
    ConfigTransactionError,
    edit_layered_config,
)


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
    config: dict[str, Any],
    write_path: Path,
    runtime: dict[str, Any],
    *,
    expected_runtime: dict[str, Any],
) -> Path:
    runtime_path = _runtime_path(write_path)
    replacement = json.loads(json.dumps(runtime))
    expected = json.loads(json.dumps(expected_runtime))
    legacy_seed_any = config.get(SECTION)
    legacy_seed = legacy_seed_any if isinstance(legacy_seed_any, dict) else {}
    transaction_legacy_seed = legacy_seed
    transaction_legacy_authoritative = False

    def fingerprint(value: dict[str, Any]) -> str:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def require_expected(current: dict[str, Any]) -> None:
        if fingerprint(current) != fingerprint(expected):
            raise ConfigTransactionError(
                "plan_runtime_stale",
                "plan execution runtime changed after it was loaded",
                phase="mutate",
            )

    def replace_runtime(current: dict[str, Any]) -> None:
        if not transaction_legacy_authoritative:
            require_expected(current if current else transaction_legacy_seed)
        current.clear()
        current.update(replacement)

    legacy_env_path = os.environ.get(LEGACY_CONFIG_ENV_VAR, "").strip()

    def mutate_layered(current: dict[str, Any]) -> None:
        nonlocal transaction_legacy_authoritative, transaction_legacy_seed
        current_runtime = current.get(SECTION)
        transaction_legacy_seed = (
            current_runtime if isinstance(current_runtime, dict) else {}
        )
        transaction_legacy_authoritative = bool(
            legacy_env_path and isinstance(current_runtime, dict)
        )
        if legacy_env_path:
            if transaction_legacy_authoritative:
                require_expected(transaction_legacy_seed)
            current[SECTION] = replacement
        else:
            current.pop(SECTION, None)

    edit_layered_config(
        mutate_layered,
        direct_participants=(
            ConfigFileParticipant(runtime_path, replace_runtime),
        ),
    )

    return runtime_path
