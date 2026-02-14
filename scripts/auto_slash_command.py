#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from auto_slash_schema import COMMANDS, detect_intent, evaluate_precision  # type: ignore
from config_layering import (  # type: ignore
    load_layered_config,
    resolve_write_path,
    save_config as save_config_file,
)


SECTION = "auto_slash_detector"
AUDIT_DEFAULT = Path(
    "~/.config/opencode/my_opencode/runtime/auto_slash_audit.jsonl"
).expanduser()


def usage() -> int:
    print(
        "usage: /auto-slash status [--json] | /auto-slash detect --prompt <text> [--json] | /auto-slash preview --prompt <text> [--json] | /auto-slash execute --prompt <text> [--force] [--json] | /auto-slash enable | /auto-slash disable | /auto-slash enable-command <doctor|stack|nvim|devtools> | /auto-slash disable-command <doctor|stack|nvim|devtools> | /auto-slash doctor [--json] | /auto-slash audit [--limit <n>] [--json]"
    )
    return 2


def default_state() -> dict[str, Any]:
    return {
        "enabled": True,
        "preview_first": True,
        "min_confidence": 0.75,
        "ambiguity_delta": 0.15,
        "enabled_commands": sorted(COMMANDS.keys()),
        "last_detection": None,
    }


def parse_value(argv: list[str], flag: str) -> str | None:
    if flag not in argv:
        return None
    idx = argv.index(flag)
    if idx + 1 >= len(argv):
        return None
    return argv[idx + 1]


def normalize_enabled_commands(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return sorted(COMMANDS.keys())
    enabled = sorted(
        {
            str(item).strip().lower()
            for item in raw
            if str(item).strip().lower() in COMMANDS
        }
    )
    return enabled if enabled else sorted(COMMANDS.keys())


def load_state() -> tuple[dict[str, Any], dict[str, Any], Path]:
    config, _ = load_layered_config()
    write_path = resolve_write_path()
    merged = default_state()
    state = config.get(SECTION)
    if isinstance(state, dict):
        merged["enabled"] = bool(state.get("enabled", True))
        merged["preview_first"] = bool(state.get("preview_first", True))
        min_conf = state.get("min_confidence")
        if isinstance(min_conf, (int, float)):
            merged["min_confidence"] = max(0.5, min(0.99, float(min_conf)))
        amb_delta = state.get("ambiguity_delta")
        if isinstance(amb_delta, (int, float)):
            merged["ambiguity_delta"] = max(0.01, min(0.5, float(amb_delta)))
        merged["enabled_commands"] = normalize_enabled_commands(
            state.get("enabled_commands")
        )
        if isinstance(state.get("last_detection"), dict):
            merged["last_detection"] = dict(state["last_detection"])
    return config, merged, write_path


def save_state(config: dict[str, Any], state: dict[str, Any], write_path: Path) -> None:
    config[SECTION] = {
        "enabled": bool(state.get("enabled", True)),
        "preview_first": bool(state.get("preview_first", True)),
        "min_confidence": float(state.get("min_confidence", 0.75)),
        "ambiguity_delta": float(state.get("ambiguity_delta", 0.15)),
        "enabled_commands": normalize_enabled_commands(state.get("enabled_commands")),
        "last_detection": state.get("last_detection"),
    }
    save_config_file(config, write_path)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _run_detection(state: dict[str, Any], prompt: str) -> dict[str, Any]:
    return detect_intent(
        prompt,
        enabled=bool(state.get("enabled", True)),
        enabled_commands=set(normalize_enabled_commands(state.get("enabled_commands"))),
        min_confidence=float(state.get("min_confidence", 0.75)),
        ambiguity_delta=float(state.get("ambiguity_delta", 0.15)),
    )


def _render_action(report: dict[str, Any]) -> dict[str, Any]:
    selected = report.get("selected") or {}
    if not selected:
        return {
            "action": "no-op",
            "reason": report.get("reason"),
            "slash_command": None,
            "backend_command": None,
        }
    script_name = selected.get("script")
    args = selected.get("args") or []
    backend = [
        sys.executable,
        str(SCRIPT_DIR / str(script_name)),
        *[str(arg) for arg in args],
    ]
    return {
        "action": "dispatch",
        "reason": "matched",
        "slash_command": selected.get("slash_command"),
        "backend_command": backend,
        "score": selected.get("score"),
    }


def _append_audit(entry: dict[str, Any]) -> None:
    AUDIT_DEFAULT.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_DEFAULT.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True) + "\n")


def _undo_hint(command: str) -> str:
    if command == "stack":
        return "run /stack status and re-apply the previous profile"
    if command == "nvim":
        return "run /nvim status, then /nvim uninstall --unlink-init if needed"
    if command == "devtools":
        return "rerun /devtools status and apply missing tools intentionally"
    return "no state mutation expected; rerun the command manually if needed"


def command_status(argv: list[str]) -> int:
    if any(arg not in ("--json",) for arg in argv):
        return usage()
    _, state, write_path = load_state()
    payload = {
        "enabled": bool(state.get("enabled", True)),
        "preview_first": bool(state.get("preview_first", True)),
        "min_confidence": state.get("min_confidence", 0.95),
        "ambiguity_delta": state.get("ambiguity_delta", 0.15),
        "enabled_commands": normalize_enabled_commands(state.get("enabled_commands")),
        "available_commands": sorted(COMMANDS.keys()),
        "last_detection": state.get("last_detection"),
        "audit_log": str(AUDIT_DEFAULT),
        "config": str(write_path),
    }
    if "--json" in argv:
        print(json.dumps(payload, indent=2))
    else:
        print(f"enabled: {'yes' if payload['enabled'] else 'no'}")
        print(f"preview_first: {'yes' if payload['preview_first'] else 'no'}")
        print(f"min_confidence: {payload['min_confidence']}")
        print(f"ambiguity_delta: {payload['ambiguity_delta']}")
        print(f"enabled_commands: {','.join(payload['enabled_commands'])}")
        print(f"audit_log: {payload['audit_log']}")
        print(f"config: {payload['config']}")
    return 0


def command_toggle(argv: list[str], enabled: bool) -> int:
    if argv:
        return usage()
    config, state, write_path = load_state()
    state["enabled"] = enabled
    save_state(config, state, write_path)
    print(f"enabled: {'yes' if enabled else 'no'}")
    print(f"config: {write_path}")
    return 0


def command_toggle_per_command(argv: list[str], enable: bool) -> int:
    if len(argv) != 1:
        return usage()
    target = argv[0].strip().lower()
    if target not in COMMANDS:
        return usage()
    config, state, write_path = load_state()
    enabled_commands = set(normalize_enabled_commands(state.get("enabled_commands")))
    if enable:
        enabled_commands.add(target)
    else:
        enabled_commands.discard(target)
    state["enabled_commands"] = sorted(enabled_commands)
    save_state(config, state, write_path)
    print(f"command: {target}")
    print(f"enabled: {'yes' if enable else 'no'}")
    print(f"enabled_commands: {','.join(state['enabled_commands']) or '(none)'}")
    print(f"config: {write_path}")
    return 0


def command_detect(argv: list[str], *, persist: bool) -> int:
    json_output = "--json" in argv
    prompt = parse_value([arg for arg in argv if arg != "--json"], "--prompt")
    if prompt is None:
        return usage()

    config, state, write_path = load_state()
    report = _run_detection(state, prompt)
    action = _render_action(report)
    payload = {
        "result": report.get("result"),
        "reason": report.get("reason"),
        "tokens": report.get("tokens", []),
        "candidates": report.get("candidates", []),
        "selected": report.get("selected"),
        "action": action,
        "preview_required": bool(state.get("preview_first", True)),
        "cancel_guidance": "use --force only when this preview matches your intent",
        "undo_guidance": _undo_hint((report.get("selected") or {}).get("command", "")),
    }

    if persist:
        state["last_detection"] = {
            "timestamp": now_iso(),
            "prompt": prompt,
            "result": payload["result"],
            "reason": payload["reason"],
            "selected": payload["selected"],
        }
        save_state(config, state, write_path)
        payload["config"] = str(write_path)

    if json_output:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"result: {payload['result']}")
    print(f"reason: {payload['reason']}")
    if action["slash_command"]:
        print(f"suggested_slash: {action['slash_command']}")
        print(f"score: {action['score']}")
        print(f"cancel_guidance: {payload['cancel_guidance']}")
        print(f"undo_guidance: {payload['undo_guidance']}")
    return 0


def command_execute(argv: list[str]) -> int:
    json_output = "--json" in argv
    force = "--force" in argv
    filtered = [arg for arg in argv if arg not in ("--json", "--force")]
    prompt = parse_value(filtered, "--prompt")
    if prompt is None:
        return usage()

    _, state, _ = load_state()
    report = _run_detection(state, prompt)
    action = _render_action(report)
    selected = report.get("selected") or {}
    payload: dict[str, Any] = {
        "result": report.get("result"),
        "reason": report.get("reason"),
        "selected": selected,
        "action": action,
        "executed": False,
        "preview_required": bool(state.get("preview_first", True)),
    }

    if payload["result"] != "MATCH":
        if json_output:
            print(json.dumps(payload, indent=2))
        else:
            print(f"result: {payload['result']}")
            print(f"reason: {payload['reason']}")
        return 0

    if bool(state.get("preview_first", True)) and not force:
        payload["result"] = "PREVIEW_ONLY"
        payload["reason"] = "force_required"
        payload["cancel_guidance"] = "rerun with --force only if preview is correct"
        payload["undo_guidance"] = _undo_hint(selected.get("command", ""))
        if json_output:
            print(json.dumps(payload, indent=2))
        else:
            print("result: PREVIEW_ONLY")
            print(f"suggested_slash: {action['slash_command']}")
            print("cancel_guidance: rerun with --force only if preview is correct")
            print(f"undo_guidance: {payload['undo_guidance']}")
        return 0

    backend = action.get("backend_command") or []
    completed = subprocess.run(backend, capture_output=True, text=True, check=False)
    payload["executed"] = True
    payload["command_returncode"] = completed.returncode
    payload["stdout"] = completed.stdout
    payload["stderr"] = completed.stderr

    _append_audit(
        {
            "timestamp": now_iso(),
            "prompt": prompt,
            "selected": selected,
            "backend_command": backend,
            "returncode": completed.returncode,
        }
    )

    if json_output:
        print(json.dumps(payload, indent=2))
    else:
        print(f"result: {payload['result']}")
        print(f"executed: yes")
        print(f"slash_command: {action['slash_command']}")
        print(f"returncode: {completed.returncode}")
        print(f"undo_guidance: {_undo_hint(selected.get('command', ''))}")
        if completed.stdout.strip():
            print("stdout:")
            print(completed.stdout.rstrip())
        if completed.stderr.strip():
            print("stderr:")
            print(completed.stderr.rstrip())
    return 0 if completed.returncode == 0 else 1


def command_doctor(argv: list[str]) -> int:
    if any(arg not in ("--json",) for arg in argv):
        return usage()
    _, state, write_path = load_state()
    enabled_commands = normalize_enabled_commands(state.get("enabled_commands"))
    missing_scripts = [
        name
        for name in enabled_commands
        if not (SCRIPT_DIR / COMMANDS[name]["script"]).exists()
    ]

    representative_set = [
        {"prompt": "please run doctor diagnostics", "expected": "doctor"},
        {"prompt": "switch to focus mode", "expected": "stack"},
        {"prompt": "install nvim integration minimal link init", "expected": "nvim"},
        {"prompt": "install devtools and setup hooks", "expected": "devtools"},
        {"prompt": "write release notes for me", "expected": None},
    ]
    precision_report = evaluate_precision(
        representative_set,
        enabled=bool(state.get("enabled", True)),
        enabled_commands=set(enabled_commands),
        min_confidence=float(state.get("min_confidence", 0.95)),
        ambiguity_delta=float(state.get("ambiguity_delta", 0.15)),
    )

    problems: list[str] = []
    warnings: list[str] = []
    if missing_scripts:
        problems.append(f"missing backend scripts for: {', '.join(missing_scripts)}")
    if precision_report["precision"] < 0.95:
        problems.append("representative precision below 0.95 target")
    if precision_report["unsafe_predictions"] > 0:
        problems.append("unsafe predictions detected on no-command prompts")
    if not state.get("enabled", True):
        warnings.append("auto-slash detector is globally disabled")

    payload = {
        "result": "PASS" if not problems else "FAIL",
        "enabled": bool(state.get("enabled", True)),
        "preview_first": bool(state.get("preview_first", True)),
        "enabled_commands": enabled_commands,
        "config": str(write_path),
        "audit_log": str(AUDIT_DEFAULT),
        "precision_report": precision_report,
        "warnings": warnings,
        "problems": problems,
        "quick_fixes": [
            "/auto-slash status --json",
            "/auto-slash preview --prompt 'run doctor diagnostics' --json",
            "/auto-slash execute --prompt 'run doctor diagnostics' --force --json",
        ],
    }
    if "--json" in argv:
        print(json.dumps(payload, indent=2))
        return 0 if payload["result"] == "PASS" else 1

    print(f"result: {payload['result']}")
    print(f"enabled: {'yes' if payload['enabled'] else 'no'}")
    print(f"preview_first: {'yes' if payload['preview_first'] else 'no'}")
    print(f"enabled_commands: {','.join(payload['enabled_commands'])}")
    print(f"precision: {payload['precision_report']['precision']}")
    print(f"unsafe_predictions: {payload['precision_report']['unsafe_predictions']}")
    if warnings:
        print("warnings:")
        for warning in warnings:
            print(f"- {warning}")
    if problems:
        print("problems:")
        for problem in problems:
            print(f"- {problem}")
    return 0 if payload["result"] == "PASS" else 1


def command_audit(argv: list[str]) -> int:
    json_output = "--json" in argv
    filtered = [arg for arg in argv if arg != "--json"]
    limit_raw = parse_value(filtered, "--limit")
    if any(arg.startswith("--") and arg not in ("--limit",) for arg in filtered):
        return usage()

    limit = 20
    if limit_raw is not None:
        try:
            limit = max(1, min(200, int(limit_raw)))
        except ValueError:
            return usage()

    if not AUDIT_DEFAULT.exists():
        payload = {"audit_log": str(AUDIT_DEFAULT), "entries": []}
        print(json.dumps(payload, indent=2) if json_output else "entries: (none)")
        return 0

    lines = AUDIT_DEFAULT.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in lines[-limit:] if line.strip()]
    payload = {"audit_log": str(AUDIT_DEFAULT), "entries": entries}
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0
    print(f"audit_log: {payload['audit_log']}")
    if not entries:
        print("entries: (none)")
        return 0
    for entry in entries:
        command = ((entry.get("selected") or {}).get("slash_command")) or "(unknown)"
        print(f"- {entry.get('timestamp')}: {command} rc={entry.get('returncode')}")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] == "status":
        return command_status(argv[1:] if argv else [])
    if argv[0] == "detect":
        return command_detect(argv[1:], persist=False)
    if argv[0] == "preview":
        return command_detect(argv[1:], persist=True)
    if argv[0] == "execute":
        return command_execute(argv[1:])
    if argv[0] == "enable":
        return command_toggle(argv[1:], True)
    if argv[0] == "disable":
        return command_toggle(argv[1:], False)
    if argv[0] == "enable-command":
        return command_toggle_per_command(argv[1:], True)
    if argv[0] == "disable-command":
        return command_toggle_per_command(argv[1:], False)
    if argv[0] == "doctor":
        return command_doctor(argv[1:])
    if argv[0] == "audit":
        return command_audit(argv[1:])
    return usage()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
