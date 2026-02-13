#!/usr/bin/env python3

from __future__ import annotations

import json
import shutil
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


SECTION = "browser"
DEFAULT_PROVIDER = "playwright"
PROVIDERS = {
    "playwright": {
        "enabled": True,
        "command": "npx",
        "args": ["@playwright/mcp@latest"],
        "doctor": {
            "required_binaries": ["node", "npx"],
            "install_hint": "npm i -D @playwright/mcp",
        },
    },
    "agent-browser": {
        "enabled": False,
        "command": "agent-browser",
        "args": [],
        "doctor": {
            "required_binaries": ["agent-browser"],
            "install_hint": "install agent-browser CLI and authenticate",
        },
    },
}


def usage() -> int:
    print(
        "usage: /browser status [--json] | /browser profile <playwright|agent-browser> | /browser doctor [--json] | /browser help"
    )
    return 2


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def default_state() -> dict[str, Any]:
    return {
        "provider": DEFAULT_PROVIDER,
        "providers": json.loads(json.dumps(PROVIDERS)),
    }


def normalize_state(raw: Any) -> dict[str, Any]:
    defaults = default_state()
    if not isinstance(raw, dict):
        return defaults

    merged = deep_merge(defaults, raw)
    providers = merged.get("providers")
    if not isinstance(providers, dict):
        merged["providers"] = defaults["providers"]
        providers = merged["providers"]

    for name, provider_default in PROVIDERS.items():
        entry = providers.get(name)
        if not isinstance(entry, dict):
            providers[name] = json.loads(json.dumps(provider_default))
            continue
        providers[name] = deep_merge(provider_default, entry)

    return merged


def load_state() -> tuple[dict[str, Any], dict[str, Any], Path]:
    config, _ = load_layered_config()
    write_path = resolve_write_path()
    state = normalize_state(config.get(SECTION))
    return config, state, write_path


def save_state(config: dict[str, Any], state: dict[str, Any], write_path: Path) -> None:
    config[SECTION] = state
    save_config_file(config, write_path)


def selected_provider(state: dict[str, Any]) -> str:
    provider = state.get("provider")
    return str(provider) if provider is not None else ""


def provider_report(name: str, provider_cfg: Any) -> dict[str, Any]:
    if not isinstance(provider_cfg, dict):
        return {
            "enabled": False,
            "command": "",
            "required_binaries": [],
            "missing_binaries": [],
            "ready": False,
            "install_hint": "",
        }

    doctor_cfg = provider_cfg.get("doctor")
    if not isinstance(doctor_cfg, dict):
        doctor_cfg = {}

    required_raw = doctor_cfg.get("required_binaries")
    required = (
        [str(item) for item in required_raw if str(item).strip()]
        if isinstance(required_raw, list)
        else []
    )
    missing = [binary for binary in required if shutil.which(binary) is None]

    return {
        "enabled": bool(provider_cfg.get("enabled", False)),
        "command": str(provider_cfg.get("command") or ""),
        "required_binaries": required,
        "missing_binaries": missing,
        "ready": not missing,
        "install_hint": str(doctor_cfg.get("install_hint") or ""),
        "args": provider_cfg.get("args")
        if isinstance(provider_cfg.get("args"), list)
        else [],
        "name": name,
    }


def build_status_payload(state: dict[str, Any], write_path: Path) -> dict[str, Any]:
    provider = selected_provider(state)
    providers_cfg = state.get("providers")
    if not isinstance(providers_cfg, dict):
        providers_cfg = {}

    providers_payload = {
        name: provider_report(name, providers_cfg.get(name)) for name in PROVIDERS
    }
    selected = providers_payload.get(provider)

    return {
        "provider": provider,
        "valid_provider": provider in PROVIDERS,
        "selected_ready": bool(selected and selected.get("ready")),
        "providers": providers_payload,
        "config": str(write_path),
    }


def command_status(argv: list[str]) -> int:
    if any(arg not in ("--json",) for arg in argv):
        return usage()
    json_output = "--json" in argv
    _, state, write_path = load_state()
    payload = build_status_payload(state, write_path)

    if json_output:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"provider: {payload['provider']}")
    print(f"valid_provider: {'yes' if payload['valid_provider'] else 'no'}")
    print(f"selected_ready: {'yes' if payload['selected_ready'] else 'no'}")
    for name, report in payload["providers"].items():
        print(
            f"{name}: {'enabled' if report['enabled'] else 'disabled'} "
            f"(command={report['command'] or 'unset'}, ready={'yes' if report['ready'] else 'no'})"
        )
    print(f"config: {payload['config']}")
    print("next:")
    print("- /browser profile playwright")
    print("- /browser profile agent-browser")
    print("- /browser doctor --json")
    return 0


def command_profile(argv: list[str]) -> int:
    if len(argv) != 1:
        return usage()
    provider = argv[0]
    if provider not in PROVIDERS:
        return usage()

    config, state, write_path = load_state()
    providers_cfg = state.get("providers")
    if not isinstance(providers_cfg, dict):
        providers_cfg = {}
        state["providers"] = providers_cfg

    for name in PROVIDERS:
        current = providers_cfg.get(name)
        if not isinstance(current, dict):
            current = json.loads(json.dumps(PROVIDERS[name]))
        current["enabled"] = name == provider
        providers_cfg[name] = current

    state["provider"] = provider
    save_state(config, state, write_path)

    print(f"provider: {provider}")
    print(f"config: {write_path}")
    return 0


def command_doctor(argv: list[str]) -> int:
    if any(arg not in ("--json",) for arg in argv):
        return usage()
    json_output = "--json" in argv

    _, state, write_path = load_state()
    payload = build_status_payload(state, write_path)

    warnings: list[str] = []
    problems: list[str] = []
    quick_fixes: list[str] = []

    provider = payload["provider"]
    selected = payload["providers"].get(provider)

    if not payload["valid_provider"]:
        problems.append(
            f"browser.provider must be one of: {', '.join(PROVIDERS.keys())}"
        )
        quick_fixes.append("run /browser profile playwright")
    elif isinstance(selected, dict):
        missing = selected.get("missing_binaries", [])
        if missing:
            warnings.append(
                f"selected provider '{provider}' missing binaries: {', '.join(missing)}"
            )
            install_hint = str(selected.get("install_hint") or "")
            if install_hint:
                quick_fixes.append(install_hint)
            quick_fixes.append(f"run /browser profile {provider}")

    report = {
        "result": "PASS" if not problems else "FAIL",
        **payload,
        "warnings": warnings,
        "problems": problems,
        "quick_fixes": quick_fixes,
    }

    if json_output:
        print(json.dumps(report, indent=2))
        return 0 if report["result"] == "PASS" else 1

    print("browser doctor")
    print("-------------")
    print(f"provider: {report['provider']}")
    print(f"valid_provider: {'yes' if report['valid_provider'] else 'no'}")
    print(f"selected_ready: {'yes' if report['selected_ready'] else 'no'}")
    if warnings:
        print("warnings:")
        for warning in warnings:
            print(f"- {warning}")
    if problems:
        print("problems:")
        for problem in problems:
            print(f"- {problem}")
    if quick_fixes:
        print("quick_fixes:")
        for item in quick_fixes:
            print(f"- {item}")
    print(f"result: {report['result']}")
    return 0 if report["result"] == "PASS" else 1


def main(argv: list[str]) -> int:
    if not argv or argv[0] == "status":
        return command_status(argv[1:] if argv else [])
    if argv[0] == "profile":
        return command_profile(argv[1:])
    if argv[0] == "doctor":
        return command_doctor(argv[1:])
    if argv[0] == "help":
        return usage()
    return usage()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
