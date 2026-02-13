#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
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
from hook_actions import (  # type: ignore
    continuation_reminder,
    error_recovery_hint,
    output_truncation_safety,
)


HOOK_IDS = ("continuation-reminder", "truncate-safety", "error-hints")
HOOK_SECTION = "hooks"
HOOK_LOG_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_HOOK_AUDIT_PATH", "~/.config/opencode/hooks/actions.jsonl"
    )
).expanduser()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_hook_settings(raw: Any) -> dict[str, Any]:
    cfg = raw if isinstance(raw, dict) else {}
    enabled = cfg.get("enabled", False)
    disabled = cfg.get("disabled", [])
    if not isinstance(disabled, list):
        disabled = []
    disabled_ids = []
    for value in disabled:
        if not isinstance(value, str):
            continue
        item = value.strip()
        if item and item in HOOK_IDS and item not in disabled_ids:
            disabled_ids.append(item)
    return {
        "enabled": isinstance(enabled, bool) and enabled,
        "disabled": disabled_ids,
    }


def load_hook_settings() -> tuple[dict[str, Any], dict[str, Any], Path]:
    data, _ = load_layered_config()
    write_path = resolve_write_path()
    settings = normalize_hook_settings(data.get(HOOK_SECTION))
    return data, settings, write_path


def save_hook_settings(
    data: dict[str, Any], settings: dict[str, Any], path: Path
) -> None:
    data[HOOK_SECTION] = {
        "enabled": bool(settings.get("enabled", False)),
        "disabled": list(settings.get("disabled", [])),
    }
    save_config_file(data, path)


def hook_allowed(hook_id: str, settings: dict[str, Any]) -> tuple[bool, str | None]:
    if not settings.get("enabled"):
        return False, "hooks_disabled"
    if hook_id in settings.get("disabled", []):
        return False, "hook_disabled"
    return True, None


def _safe_audit_payload(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "hook_id": report.get("hook_id"),
        "triggered": bool(report.get("triggered", False)),
        "category": report.get("category"),
        "truncated": bool(report.get("truncated", False)),
        "pending_count": report.get("pending_count"),
        "exit_code": report.get("exit_code"),
    }


def write_audit_log(record: dict[str, Any]) -> None:
    HOOK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HOOK_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def usage() -> int:
    print(
        "usage: /hooks status | /hooks help | /hooks enable | /hooks disable | /hooks disable-hook <hook-id> | /hooks enable-hook <hook-id> | /hooks run <continuation-reminder|truncate-safety|error-hints> [--json '<payload>'] | /hooks doctor [--json]"
    )
    return 2


def parse_json(argv: list[str], name: str) -> dict[str, Any]:
    if name not in argv:
        return {}
    idx = argv.index(name)
    if idx + 1 >= len(argv):
        raise ValueError(f"missing value for {name}")
    raw = argv[idx + 1]
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} payload must be an object")
    return parsed


def command_status() -> int:
    _, settings, write_path = load_hook_settings()
    print("hooks: baseline")
    print(f"enabled: {'yes' if settings['enabled'] else 'no'}")
    print(
        "disabled: "
        + (",".join(settings["disabled"]) if settings["disabled"] else "(none)")
    )
    print(f"config: {write_path}")
    print(f"audit_log: {HOOK_LOG_PATH}")
    print("available:")
    for hook_id in HOOK_IDS:
        print(f"- {hook_id}")
    return 0


def command_enable() -> int:
    data, settings, write_path = load_hook_settings()
    settings["enabled"] = True
    save_hook_settings(data, settings, write_path)
    print("hooks: enabled")
    print(f"config: {write_path}")
    return 0


def command_disable() -> int:
    data, settings, write_path = load_hook_settings()
    settings["enabled"] = False
    save_hook_settings(data, settings, write_path)
    print("hooks: disabled")
    print(f"config: {write_path}")
    return 0


def command_disable_hook(argv: list[str]) -> int:
    if not argv:
        return usage()
    hook_id = argv[0]
    if hook_id not in HOOK_IDS:
        return usage()
    data, settings, write_path = load_hook_settings()
    disabled = list(settings.get("disabled", []))
    if hook_id not in disabled:
        disabled.append(hook_id)
    settings["disabled"] = disabled
    save_hook_settings(data, settings, write_path)
    print(f"hook disabled: {hook_id}")
    print(f"config: {write_path}")
    return 0


def command_enable_hook(argv: list[str]) -> int:
    if not argv:
        return usage()
    hook_id = argv[0]
    if hook_id not in HOOK_IDS:
        return usage()
    data, settings, write_path = load_hook_settings()
    settings["disabled"] = [x for x in settings.get("disabled", []) if x != hook_id]
    save_hook_settings(data, settings, write_path)
    print(f"hook enabled: {hook_id}")
    print(f"config: {write_path}")
    return 0


def command_run(argv: list[str]) -> int:
    if not argv:
        return usage()

    hook = argv[0].strip()
    if hook not in HOOK_IDS:
        return usage()

    payload = parse_json(argv[1:], "--json")
    _, settings, _ = load_hook_settings()
    allowed, reason = hook_allowed(hook, settings)

    if not allowed:
        report = {
            "hook_id": hook,
            "triggered": False,
            "skipped": True,
            "reason": reason,
        }
        write_audit_log(
            {
                "timestamp": now_iso(),
                "result": "skipped",
                "reason": reason,
                **_safe_audit_payload(report),
            }
        )
        print(json.dumps(report, indent=2))
        return 0

    if hook == "continuation-reminder":
        report = continuation_reminder(payload)
    elif hook == "truncate-safety":
        report = output_truncation_safety(payload)
    else:
        report = error_recovery_hint(payload)

    write_audit_log(
        {
            "timestamp": now_iso(),
            "result": "executed",
            "reason": None,
            **_safe_audit_payload(report),
        }
    )

    print(json.dumps(report, indent=2))
    return 0


def collect_doctor() -> dict[str, Any]:
    _, settings, write_path = load_hook_settings()
    warnings: list[str] = []
    problems: list[str] = []

    for hook_id in settings.get("disabled", []):
        if hook_id not in HOOK_IDS:
            problems.append(f"unknown disabled hook id in config: {hook_id}")

    if not settings.get("enabled"):
        warnings.append("hooks are globally disabled")

    if not HOOK_LOG_PATH.exists():
        warnings.append("hook audit log does not exist yet")
    else:
        try:
            lines = [
                line.strip()
                for line in HOOK_LOG_PATH.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if lines:
                sample = json.loads(lines[-1])
                forbidden = [
                    field for field in ("stderr", "stdout", "text") if field in sample
                ]
                if forbidden:
                    problems.append(
                        "hook audit includes forbidden raw-output fields: "
                        + ",".join(forbidden)
                    )
            else:
                warnings.append("hook audit log is empty")
        except Exception as exc:
            problems.append(f"failed to parse hook audit log: {exc}")

    return {
        "result": "PASS" if not problems else "FAIL",
        "enabled": bool(settings.get("enabled", False)),
        "disabled": settings.get("disabled", []),
        "available_hooks": list(HOOK_IDS),
        "audit_log": str(HOOK_LOG_PATH),
        "config": str(write_path),
        "warnings": warnings,
        "problems": problems,
        "quick_fixes": [
            "/hooks enable",
            '/hooks run continuation-reminder --json \'{"checklist":["update docs"]}\'',
        ]
        if warnings or problems
        else [],
    }


def command_doctor(argv: list[str]) -> int:
    json_output = "--json" in argv
    if any(arg not in ("--json",) for arg in argv):
        return usage()
    report = collect_doctor()
    if json_output:
        print(json.dumps(report, indent=2))
        return 0 if report["result"] == "PASS" else 1

    print("hooks doctor")
    print("------------")
    print(f"result: {report['result']}")
    print(f"enabled: {'yes' if report['enabled'] else 'no'}")
    print(
        f"disabled: {','.join(report['disabled']) if report['disabled'] else '(none)'}"
    )
    print(f"audit_log: {report['audit_log']}")
    if report["warnings"]:
        print("warnings:")
        for warning in report["warnings"]:
            print(f"- {warning}")
    if report["problems"]:
        print("problems:")
        for problem in report["problems"]:
            print(f"- {problem}")
    return 0 if report["result"] == "PASS" else 1


def main(argv: list[str]) -> int:
    if not argv or argv[0] == "status":
        return command_status()
    if argv[0] == "help":
        return usage()
    if argv[0] == "enable":
        return command_enable()
    if argv[0] == "disable":
        return command_disable()
    if argv[0] == "disable-hook":
        return command_disable_hook(argv[1:])
    if argv[0] == "enable-hook":
        return command_enable_hook(argv[1:])
    if argv[0] == "run":
        return command_run(argv[1:])
    if argv[0] == "doctor":
        return command_doctor(argv[1:])
    return usage()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
