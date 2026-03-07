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
)
from model_routing_schema import (  # type: ignore
    default_schema,
    resolve_model_settings,
    validate_schema,
)


SECTION = "model_routing"
CONFIG_PATH = Path(
    os.environ.get(
        "OPENCODE_MODEL_ROUTING_PATH", "~/.config/opencode/opencode-model-routing.json"
    )
).expanduser()
LEGACY_ENV_SET = "OPENCODE_MODEL_ROUTING_PATH" in os.environ
SPEC_DIR = Path(__file__).resolve().parent.parent / "agent" / "specs"
DEFAULT_STATE = {
    "active_category": "balanced",
    "system_defaults": {
        "model": "openai/gpt-5.3-codex",
        "temperature": 0.2,
        "reasoning": "medium",
        "verbosity": "medium",
    },
    "latest_trace": {},
}

ENTRYPOINT_CATEGORY_DEFAULTS = {
    "autopilot": "balanced",
    "delivery": "balanced",
    "start-work": "deep",
    "workflow": "balanced",
}


def usage() -> int:
    print(
        "usage: /model-routing status [--json] | /model-routing set-category <quick|balanced|deep|critical|visual|writing> | /model-routing resolve [--category <name>] [--override-model <id>] [--override-temperature <value>] [--override-reasoning <value>] [--override-verbosity <value>] [--available-models <csv>] [--json] | /model-routing trace [--json] | /model-routing recommend [--agent <name>] [--apply] [--json]"
    )
    return 2


def _merged_state(raw_state: Any) -> dict[str, Any]:
    state = raw_state if isinstance(raw_state, dict) else {}
    merged = dict(DEFAULT_STATE)
    merged.update(state)
    system_defaults = merged.get("system_defaults")
    if not isinstance(system_defaults, dict):
        merged["system_defaults"] = dict(DEFAULT_STATE["system_defaults"])
    else:
        merged["system_defaults"] = {
            **DEFAULT_STATE["system_defaults"],
            **system_defaults,
        }
    if not isinstance(merged.get("latest_trace"), dict):
        merged["latest_trace"] = {}
    return merged


def load_state_snapshot(
    *, persist_missing: bool = False
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    config, _ = load_layered_config()
    write_path = resolve_write_path()
    if LEGACY_ENV_SET and CONFIG_PATH.exists():
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return config, _merged_state(loaded), CONFIG_PATH

    if CONFIG_PATH.exists():
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return config, _merged_state(loaded), CONFIG_PATH

    merged = _merged_state(config.get(SECTION))
    if persist_missing:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return config, merged, CONFIG_PATH


def load_state() -> tuple[dict[str, Any], dict[str, Any], Path]:
    return load_state_snapshot(persist_missing=True)


def save_state(config: dict[str, Any], state: dict[str, Any], write_path: Path) -> None:
    payload = {
        "active_category": state.get("active_category", "balanced"),
        "system_defaults": state.get("system_defaults", {}),
        "latest_trace": state.get("latest_trace", {}),
    }
    if LEGACY_ENV_SET:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def active_config_path(write_path: Path) -> Path:
    if LEGACY_ENV_SET:
        return CONFIG_PATH
    if CONFIG_PATH.exists():
        return CONFIG_PATH
    return write_path


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


def _load_agent_metadata() -> dict[str, dict[str, Any]]:
    metadata_map: dict[str, dict[str, Any]] = {}
    if not SPEC_DIR.exists() or not SPEC_DIR.is_dir():
        return metadata_map
    for path in sorted(SPEC_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        name = payload.get("name")
        metadata = payload.get("metadata")
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(metadata, dict)
        ):
            continue
        metadata_map[name.strip()] = metadata
    return metadata_map


def _recommend_for_agent(agent_name: str) -> dict[str, Any]:
    metadata_map = _load_agent_metadata()
    metadata = metadata_map.get(agent_name)
    if metadata is None:
        return {
            "result": "FAIL",
            "reason_codes": ["agent_metadata_not_found"],
            "agent": agent_name,
            "quick_fixes": [
                "use /model-routing recommend --json to inspect known agents",
                "run python3 scripts/agent_doctor.py run --json",
            ],
        }
    category = metadata.get("default_category")
    if not isinstance(category, str) or not category.strip():
        category = "balanced"
    return {
        "result": "PASS",
        "agent": agent_name,
        "recommended_category": category,
        "cost_tier": metadata.get("cost_tier"),
        "fallback_policy": metadata.get("fallback_policy"),
        "triggers": metadata.get("triggers", []),
        "avoid_when": metadata.get("avoid_when", []),
        "reason_codes": ["agent_routing_recommendation_generated"],
    }


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


def resolve_for_entrypoint(
    entrypoint: str,
    *,
    requested_category: str | None = None,
    available_models: set[str] | None = None,
    user_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _, state, _ = load_state_snapshot(persist_missing=False)
    schema = default_schema()
    problems = validate_schema(schema)
    if problems:
        return {
            "result": "FAIL",
            "entrypoint": entrypoint,
            "problems": problems,
        }

    effective_requested_category = requested_category
    requested_category_source = "requested_category"
    if not effective_requested_category:
        entrypoint_default = ENTRYPOINT_CATEGORY_DEFAULTS.get(entrypoint)
        if isinstance(entrypoint_default, str) and entrypoint_default:
            effective_requested_category = entrypoint_default
            requested_category_source = "entrypoint_default"
        else:
            active_category = state.get("active_category")
            effective_requested_category = (
                str(active_category).strip()
                if isinstance(active_category, str)
                else None
            )
            requested_category_source = "active_category"

    resolved = resolve_model_settings(
        schema=schema,
        requested_category=effective_requested_category,
        user_overrides=user_overrides,
        system_defaults=state.get("system_defaults"),
        available_models=available_models,
    )
    return {
        "result": "PASS",
        "entrypoint": entrypoint,
        "active_category": state.get("active_category"),
        "requested_category": effective_requested_category,
        "requested_category_source": requested_category_source,
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
        "config": str(active_config_path(write_path)),
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
    print(f"config: {active_config_path(write_path)}")
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


def command_recommend(argv: list[str]) -> int:
    json_output = "--json" in argv
    apply_change = "--apply" in argv
    filtered = [arg for arg in argv if arg not in {"--json", "--apply"}]
    agent_name = parse_value(filtered, "--agent")

    if agent_name:
        report = _recommend_for_agent(agent_name)
        if report.get("result") != "PASS":
            print(json.dumps(report, indent=2))
            return 1
        config, state, write_path = load_state()
        if apply_change:
            state["active_category"] = report.get("recommended_category", "balanced")
            save_state(config, state, write_path)
            report["applied"] = True
            report["active_category"] = state.get("active_category")
            report["config"] = str(active_config_path(write_path))
        else:
            report["applied"] = False
            report["active_category"] = state.get("active_category")
            report["config"] = str(active_config_path(write_path))

        if json_output:
            print(json.dumps(report, indent=2))
            return 0
        print(f"agent: {report.get('agent')}")
        print(f"recommended_category: {report.get('recommended_category')}")
        print(f"cost_tier: {report.get('cost_tier')}")
        print(f"fallback_policy: {report.get('fallback_policy')}")
        print(f"applied: {'yes' if report.get('applied') else 'no'}")
        print(f"active_category: {report.get('active_category')}")
        return 0

    metadata_map = _load_agent_metadata()
    rows = []
    for name in sorted(metadata_map):
        meta = metadata_map[name]
        category = meta.get("default_category")
        rows.append(
            {
                "agent": name,
                "recommended_category": category,
                "cost_tier": meta.get("cost_tier"),
            }
        )
    payload = {
        "result": "PASS",
        "agent_count": len(rows),
        "recommendations": rows,
        "reason_codes": ["agent_routing_catalog_generated"],
    }
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0
    print(f"agent_count: {len(rows)}")
    for row in rows:
        print(
            f"- {row['agent']}: {row['recommended_category']} (cost_tier={row['cost_tier']})"
        )
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
    if argv[0] == "recommend":
        return command_recommend(argv[1:])
    if argv[0] == "help":
        return usage()
    return usage()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
