#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from typing import Any

from kvforge_discovery import load_states, state_running


def usage() -> int:
    print("usage: /models [--json]")
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


def models_payload() -> dict[str, Any]:
    models = []
    for state in load_states():
        models.append(
            {
                "connection_name": state.get("connection_name"),
                "provider_model": state.get("provider_model"),
                "served_model_name": state.get("served_model_name"),
                "source_model": state.get("model"),
                "base_url": state.get("base_url"),
                "running": state_running(state),
            }
        )
    models.sort(key=lambda item: (not bool(item.get("running")), str(item.get("connection_name") or "")))
    return {
        "result": "PASS" if models else "FAIL",
        "reason": "models_found" if models else "models_missing",
        "models": models,
    }


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    args = [item for item in argv if item != "--json"]
    if args and args[0] in {"-h", "--help", "help"}:
        return usage()
    emit(models_payload(), as_json=as_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
