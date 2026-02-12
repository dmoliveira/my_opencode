#!/usr/bin/env python3

import json
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse


CONFIG_PATH = Path(
    os.environ.get(
        "OPENCODE_TELEMETRY_PATH", "~/.config/opencode/opencode-telemetry.json"
    )
).expanduser()

EVENTS = ("complete", "error", "permission", "question")

PROFILE_MAP = {
    "off": {
        "enabled": False,
        "events": {name: False for name in EVENTS},
    },
    "local": {
        "enabled": True,
        "events": {name: True for name in EVENTS},
    },
    "errors-only": {
        "enabled": True,
        "events": {
            "complete": False,
            "error": True,
            "permission": False,
            "question": False,
        },
    },
}


def default_state() -> dict:
    return {
        "enabled": False,
        "endpoint": "http://localhost:3000/opencode/events",
        "timeout_ms": 1500,
        "events": {name: True for name in EVENTS},
    }


def to_bool(value, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    return fallback


def load_state() -> dict:
    state = default_state()
    if not CONFIG_PATH.exists():
        return state

    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    state["enabled"] = to_bool(data.get("enabled"), state["enabled"])

    if isinstance(data.get("endpoint"), str) and data["endpoint"].strip():
        state["endpoint"] = data["endpoint"].strip()

    if isinstance(data.get("timeout_ms"), int) and data["timeout_ms"] > 0:
        state["timeout_ms"] = data["timeout_ms"]

    if isinstance(data.get("events"), dict):
        for name in EVENTS:
            if name in data["events"]:
                state["events"][name] = to_bool(
                    data["events"][name], state["events"][name]
                )

    return state


def save_state(state: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def usage() -> int:
    print(
        "usage: /telemetry status | /telemetry help | /telemetry doctor [--json] | /telemetry profile <off|local|errors-only> | /telemetry enable <all|complete|error|permission|question> | /telemetry disable <all|complete|error|permission|question> | /telemetry set endpoint <url> | /telemetry set timeout <ms>"
    )
    return 2


def print_status(state: dict) -> int:
    print(f"enabled: {'yes' if state['enabled'] else 'no'}")
    print(f"endpoint: {state['endpoint']}")
    print(f"timeout_ms: {state['timeout_ms']}")
    print("events:")
    for name in EVENTS:
        print(f"- {name}: {'enabled' if state['events'][name] else 'disabled'}")
    print(f"config: {CONFIG_PATH}")
    return 0


def validate_endpoint(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "endpoint must start with http:// or https://"
    if not parsed.hostname:
        return "endpoint host is missing"
    return None


def endpoint_reachable(url: str, timeout_ms: int) -> tuple[bool, str]:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return False, "invalid host"

    default_port = 443 if parsed.scheme == "https" else 80
    port = parsed.port or default_port
    timeout_seconds = max(timeout_ms / 1000.0, 0.2)

    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True, f"tcp ok ({host}:{port})"
    except OSError as exc:
        return False, f"tcp failed ({host}:{port}): {exc}"


def collect_doctor(state: dict) -> dict:
    problems: list[str] = []
    warnings: list[str] = []

    endpoint_error = validate_endpoint(state["endpoint"])
    if endpoint_error:
        problems.append(endpoint_error)

    if state["timeout_ms"] <= 0:
        problems.append("timeout_ms must be greater than zero")

    enabled_count = sum(1 for name in EVENTS if state["events"][name])
    if enabled_count == 0:
        warnings.append("all telemetry events are disabled")

    reachability = {"checked": False, "ok": None, "detail": "not checked"}
    if state["enabled"] and not endpoint_error:
        ok, detail = endpoint_reachable(state["endpoint"], state["timeout_ms"])
        reachability = {"checked": True, "ok": ok, "detail": detail}
        if not ok:
            warnings.append(f"endpoint not reachable: {detail}")

    return {
        "result": "PASS" if not problems else "FAIL",
        "config": str(CONFIG_PATH),
        "enabled": state["enabled"],
        "endpoint": state["endpoint"],
        "timeout_ms": state["timeout_ms"],
        "events": state["events"],
        "reachability": reachability,
        "warnings": warnings,
        "problems": problems,
        "quick_fixes": [
            "set a valid endpoint with: /telemetry set endpoint http://localhost:3000/opencode/events",
            "set timeout with: /telemetry set timeout 1500",
            "enable event forwarding with: /telemetry profile local",
        ]
        if problems
        else [],
    }


def print_doctor(state: dict, json_output: bool) -> int:
    report = collect_doctor(state)

    if json_output:
        print(json.dumps(report, indent=2))
        return 0 if report["result"] == "PASS" else 1

    print("telemetry doctor")
    print("----------------")
    print(f"enabled: {'yes' if report['enabled'] else 'no'}")
    print(f"endpoint: {report['endpoint']}")
    print(f"timeout_ms: {report['timeout_ms']}")
    print("events:")
    for name in EVENTS:
        print(f"- {name}: {'enabled' if report['events'][name] else 'disabled'}")

    r = report["reachability"]
    if r["checked"]:
        status = "ok" if r["ok"] else "failed"
        print(f"reachability: {status} ({r['detail']})")

    if report["warnings"]:
        print("\nwarnings:")
        for item in report["warnings"]:
            print(f"- {item}")

    if report["problems"]:
        print("\nproblems:")
        for item in report["problems"]:
            print(f"- {item}")
        print("\nquick fixes:")
        for item in report["quick_fixes"]:
            print(f"- {item}")
        print("\nresult: FAIL")
        return 1

    print("\nresult: PASS")
    return 0


def apply_profile(state: dict, profile: str) -> int:
    if profile not in PROFILE_MAP:
        return usage()
    p = PROFILE_MAP[profile]
    state["enabled"] = p["enabled"]
    for name in EVENTS:
        state["events"][name] = p["events"][name]
    print(f"profile: {profile}")
    return 0


def toggle(state: dict, action: str, target: str) -> int:
    value = action == "enable"
    if target == "all":
        state["enabled"] = value
        for name in EVENTS:
            state["events"][name] = value
        print(f"all: {'enabled' if value else 'disabled'}")
        return 0

    if target in EVENTS:
        state["events"][target] = value
        print(f"{target}: {'enabled' if value else 'disabled'}")
        return 0

    return usage()


def set_value(state: dict, key: str, value: str) -> int:
    if key == "endpoint":
        error = validate_endpoint(value)
        if error:
            print(f"error: {error}")
            return 1
        state["endpoint"] = value
        print(f"endpoint: {value}")
        return 0

    if key == "timeout":
        try:
            timeout = int(value)
        except ValueError:
            print("error: timeout must be an integer")
            return 1
        if timeout <= 0:
            print("error: timeout must be greater than zero")
            return 1
        state["timeout_ms"] = timeout
        print(f"timeout_ms: {timeout}")
        return 0

    return usage()


def main(argv: list[str]) -> int:
    state = load_state()

    if not argv or argv[0] == "status":
        return print_status(state)

    if argv[0] == "help":
        return usage()

    if argv[0] == "doctor":
        json_output = len(argv) > 1 and argv[1] == "--json"
        if len(argv) > 1 and not json_output:
            return usage()
        return print_doctor(state, json_output)

    if argv[0] == "profile":
        if len(argv) < 2:
            return usage()
        code = apply_profile(state, argv[1])
        if code != 0:
            return code
        save_state(state)
        print(f"config: {CONFIG_PATH}")
        return 0

    if argv[0] in ("enable", "disable"):
        if len(argv) < 2:
            return usage()
        code = toggle(state, argv[0], argv[1])
        if code != 0:
            return code
        save_state(state)
        print(f"config: {CONFIG_PATH}")
        return 0

    if argv[0] == "set":
        if len(argv) < 3:
            return usage()
        code = set_value(state, argv[1], argv[2])
        if code != 0:
            return code
        save_state(state)
        print(f"config: {CONFIG_PATH}")
        return 0

    return usage()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
