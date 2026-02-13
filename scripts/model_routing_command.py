#!/usr/bin/env python3

from __future__ import annotations

import json
import os
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
from model_routing_schema import (  # type: ignore
    default_schema,
    resolve_model_settings,
    validate_schema,
)


SECTION = "model_routing"
DEFAULT_STATE = {
    "active_category": "quick",
    "system_defaults": {
        "model": "openai/gpt-5.3-codex",
        "temperature": 0.2,
        "reasoning": "medium",
        "verbosity": "medium",
    },
    "latest_trace": {},
}


def usage() -> int:
    print(
        "usage: /model-routing status [--json] | /model-routing set-category <quick|deep|visual|writing> | /model-routing resolve [--category <name>] [--override-model <id>] [--override-temperature <value>] [--override-reasoning <value>] [--override-verbosity <value>] [--available-models <csv>] [--json] | /model-routing trace [--json]"
    )
    return 2


def load_state() -> tuple[dict[str, Any], dict[str, Any], Path]:
    config, _ = load_layered_config()
    write_path = resolve_write_path()
    state = config.get(SECTION)
    if not isinstance(state, dict):
        state = dict(DEFAULT_STATE)
    merged = dict(DEFAULT_STATE)
    merged.update(state)
    if not isinstance(merged.get("system_defaults"), dict):
        merged["system_defaults"] = dict(DEFAULT_STATE["system_defaults"])
    return config, merged, write_path


def save_state(config: dict[str, Any], state: dict[str, Any], write_path: Path) -> None:
    config[SECTION] = {
        "active_category": state.get("active_category", "quick"),
        "system_defaults": state.get("system_defaults", {}),
        "latest_trace": state.get("latest_trace", {}),
    }
    save_config_file(config, write_path)


def parse_value(argv: list[str], flag: str) -> str | None:
    if flag not in argv:
        return None
    idx = argv.index(flag)
    if idx + 1 >= len(argv):
        return None
    return argv[idx + 1]


def parse_available_models(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    parts = {item.strip() for item in raw.split(",") if item.strip()}
    return parts if parts else None


def parse_temperature(raw: str | None) -> float | None:
    if raw is None:
        return None
    return float(raw)


def run_resolve(state: dict[str, Any], argv: list[str]) -> dict[str, Any]:
    schema = default_schema()
    problems = validate_schema(schema)
    if problems:
        return {"result": "FAIL", "problems": problems}

    category = parse_value(argv, "--category") or state.get("active_category")
    available_models = parse_available_models(parse_value(argv, "--available-models"))

    user_overrides: dict[str, Any] = {}
    override_model = parse_value(argv, "--override-model")
    if override_model:
        user_overrides["model"] = override_model
    override_temperature = parse_value(argv, "--override-temperature")
    if override_temperature is not None:
        user_overrides["temperature"] = parse_temperature(override_temperature)
    override_reasoning = parse_value(argv, "--override-reasoning")
    if override_reasoning:
        user_overrides["reasoning"] = override_reasoning
    override_verbosity = parse_value(argv, "--override-verbosity")
    if override_verbosity:
        user_overrides["verbosity"] = override_verbosity

    resolved = resolve_model_settings(
        schema=schema,
        requested_category=str(category) if category else None,
        user_overrides=user_overrides,
        system_defaults=state.get("system_defaults"),
        available_models=available_models,
    )
    return {
        "result": "PASS",
        "active_category": state.get("active_category"),
        "requested_category": category,
        "available_models": sorted(available_models) if available_models else None,
        **resolved,
    }


def command_status(argv: list[str]) -> int:
    if any(arg not in ("--json",) for arg in argv):
        return usage()
    json_output = "--json" in argv
    _, state, write_path = load_state()
    payload = {
        "active_category": state.get("active_category"),
        "system_defaults": state.get("system_defaults"),
        "has_latest_trace": bool(state.get("latest_trace")),
        "config": str(write_path),
    }
    if json_output:
        print(json.dumps(payload, indent=2))
    else:
        print(f"active_category: {payload['active_category']}")
        print(f"system_defaults: {json.dumps(payload['system_defaults'])}")
        print(f"has_latest_trace: {'yes' if payload['has_latest_trace'] else 'no'}")
        print(f"config: {payload['config']}")
    return 0


def command_set_category(argv: list[str]) -> int:
    if len(argv) != 1:
        return usage()
    category = argv[0]
    schema = default_schema()
    categories = schema.get("categories", {})
    if category not in categories:
        return usage()
    config, state, write_path = load_state()
    state["active_category"] = category
    save_state(config, state, write_path)
    print(f"active_category: {category}")
    print(f"config: {write_path}")
    return 0


def command_resolve(argv: list[str]) -> int:
    json_output = "--json" in argv
    filtered = [arg for arg in argv if arg != "--json"]
    config, state, write_path = load_state()
    report = run_resolve(state, filtered)
    if report.get("result") != "PASS":
        print(json.dumps(report, indent=2))
        return 1

    resolution_trace = report.get("resolution_trace")
    if isinstance(resolution_trace, dict):
        state["latest_trace"] = resolution_trace
        save_state(config, state, write_path)

    if json_output:
        print(json.dumps(report, indent=2))
        return 0
    settings = report.get("settings", {})
    print(f"category: {report.get('category')}")
    print(f"model: {settings.get('model')}")
    print(f"temperature: {settings.get('temperature')}")
    print(f"reasoning: {settings.get('reasoning')}")
    print(f"verbosity: {settings.get('verbosity')}")
    print(f"trace_steps: {len(report.get('trace', []))}")
    return 0


def command_trace(argv: list[str]) -> int:
    if any(arg not in ("--json",) for arg in argv):
        return usage()
    json_output = "--json" in argv
    _, state, _ = load_state()
    trace = state.get("latest_trace")
    payload = {
        "result": "PASS",
        "has_trace": isinstance(trace, dict) and bool(trace),
        "trace": trace if isinstance(trace, dict) else {},
    }
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0
    print(f"has_trace: {'yes' if payload['has_trace'] else 'no'}")
    if payload["has_trace"]:
        selected = payload["trace"].get("selected", {})
        print(f"selected_model: {selected.get('model')}")
        print(f"selected_reason: {selected.get('reason')}")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] == "status":
        return command_status(argv[1:] if argv else [])
    if argv[0] == "set-category":
        return command_set_category(argv[1:])
    if argv[0] == "resolve":
        return command_resolve(argv[1:])
    if argv[0] == "trace":
        return command_trace(argv[1:])
    if argv[0] == "help":
        return usage()
    return usage()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
