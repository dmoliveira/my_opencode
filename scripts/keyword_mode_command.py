#!/usr/bin/env python3

from __future__ import annotations

import json
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
from keyword_mode_schema import (  # type: ignore
    KEYWORDS,
    default_state,
    normalize_disabled_keywords,
    resolve_prompt_modes,
)


SECTION = "keyword_modes"


def usage() -> int:
    print(
        "usage: /keyword-mode status [--json] | /keyword-mode detect --prompt <text> [--json] | /keyword-mode apply --prompt <text> [--json]"
    )
    return 2


def parse_value(argv: list[str], flag: str) -> str | None:
    if flag not in argv:
        return None
    idx = argv.index(flag)
    if idx + 1 >= len(argv):
        return None
    return argv[idx + 1]


def load_state() -> tuple[dict[str, Any], dict[str, Any], Path]:
    config, _ = load_layered_config()
    write_path = resolve_write_path()
    state = config.get(SECTION)
    merged = default_state()
    if isinstance(state, dict):
        merged["enabled"] = bool(state.get("enabled", True))
        merged["disabled_keywords"] = sorted(
            normalize_disabled_keywords(state.get("disabled_keywords"))
        )
        if isinstance(state.get("active_modes"), list):
            merged["active_modes"] = [
                str(item)
                for item in state.get("active_modes", [])
                if isinstance(item, str)
            ]
        effective_flags = state.get("effective_flags")
        if isinstance(effective_flags, dict):
            merged["effective_flags"] = dict(effective_flags)
        if isinstance(state.get("last_prompt"), str):
            merged["last_prompt"] = state.get("last_prompt")
    return config, merged, write_path


def save_state(config: dict[str, Any], state: dict[str, Any], write_path: Path) -> None:
    config[SECTION] = {
        "enabled": bool(state.get("enabled", True)),
        "disabled_keywords": sorted(
            normalize_disabled_keywords(state.get("disabled_keywords"))
        ),
        "active_modes": state.get("active_modes", []),
        "effective_flags": state.get("effective_flags", {}),
        "last_prompt": state.get("last_prompt"),
    }
    save_config_file(config, write_path)


def resolve_from_prompt(state: dict[str, Any], prompt: str) -> dict[str, Any]:
    disabled_keywords = normalize_disabled_keywords(state.get("disabled_keywords"))
    report = resolve_prompt_modes(
        prompt,
        enabled=bool(state.get("enabled", True)),
        disabled_keywords=disabled_keywords,
    )
    return {
        "result": "PASS",
        "available_keywords": sorted(KEYWORDS.keys()),
        "global_enabled": bool(state.get("enabled", True)),
        "global_disabled_keywords": sorted(disabled_keywords),
        **report,
    }


def command_status(argv: list[str]) -> int:
    if any(arg not in ("--json",) for arg in argv):
        return usage()
    json_output = "--json" in argv
    _, state, write_path = load_state()
    payload = {
        "enabled": bool(state.get("enabled", True)),
        "disabled_keywords": sorted(
            normalize_disabled_keywords(state.get("disabled_keywords"))
        ),
        "active_modes": state.get("active_modes", []),
        "effective_flags": state.get("effective_flags", {}),
        "available_keywords": sorted(KEYWORDS.keys()),
        "config": str(write_path),
    }
    if json_output:
        print(json.dumps(payload, indent=2))
    else:
        print(f"enabled: {'yes' if payload['enabled'] else 'no'}")
        print(
            f"disabled_keywords: {','.join(payload['disabled_keywords']) or '(none)'}"
        )
        print(f"active_modes: {','.join(payload['active_modes']) or '(none)'}")
        print(f"config: {payload['config']}")
    return 0


def command_detect(argv: list[str]) -> int:
    json_output = "--json" in argv
    prompt = parse_value([arg for arg in argv if arg != "--json"], "--prompt")
    if prompt is None:
        return usage()
    _, state, _ = load_state()
    report = resolve_from_prompt(state, prompt)
    if json_output:
        print(json.dumps(report, indent=2))
        return 0
    print(f"matched_keywords: {','.join(report['matched_keywords']) or '(none)'}")
    print(f"request_opt_out: {report['request_opt_out']}")
    print(f"conflicts: {len(report['conflicts'])}")
    print(f"effective_flags: {json.dumps(report['effective_flags'])}")
    return 0


def command_apply(argv: list[str]) -> int:
    json_output = "--json" in argv
    prompt = parse_value([arg for arg in argv if arg != "--json"], "--prompt")
    if prompt is None:
        return usage()
    config, state, write_path = load_state()
    report = resolve_from_prompt(state, prompt)
    state["active_modes"] = report.get("matched_keywords", [])
    state["effective_flags"] = report.get("effective_flags", {})
    state["last_prompt"] = prompt
    save_state(config, state, write_path)

    payload = dict(report)
    payload["config"] = str(write_path)
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0
    print(f"active_modes: {','.join(payload['matched_keywords']) or '(none)'}")
    print(f"request_opt_out: {payload['request_opt_out']}")
    print(f"effective_flags: {json.dumps(payload['effective_flags'])}")
    print(f"config: {payload['config']}")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] == "status":
        return command_status(argv[1:] if argv else [])
    if argv[0] == "detect":
        return command_detect(argv[1:])
    if argv[0] == "apply":
        return command_apply(argv[1:])
    if argv[0] == "help":
        return usage()
    return usage()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
