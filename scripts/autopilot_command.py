#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from autopilot_integration import integrate_controls  # type: ignore
from autopilot_runtime import execute_cycle, initialize_run, load_runtime, save_runtime  # type: ignore
from config_layering import load_layered_config, resolve_write_path  # type: ignore
from gateway_command import hook_diagnostics, plugin_dir, status_payload  # type: ignore
from gateway_plugin_bridge import (  # type: ignore
    bridge_start_loop,
    bridge_stop_loop,
    cleanup_orphan_loop,
    gateway_loop_state_path,
)


def usage() -> int:
    print(
        "usage: /autopilot [start|go|status|pause|resume|stop|report|doctor] [--json] "
        "| /autopilot start --goal <text> --scope <text> [--done-criteria <text>] [--completion-mode <promise|objective>] [--completion-promise <text>] --max-budget <profile> [--json] "
        "| /autopilot go [--goal <text>] [--scope <text>] [--done-criteria <text>] [--completion-mode <promise|objective>] [--completion-promise <text>] [--max-budget <profile>] "
        "[--confidence <0-1>] [--tool-calls <n>] [--token-estimate <n>] [--touched-paths <csv>] [--max-cycles <n>] [--json] "
        "| /autopilot resume [--confidence <0-1>] [--tool-calls <n>] [--token-estimate <n>] [--touched-paths <csv>] [--completion-signal] [--assistant-text <text>] [--json]"
    )
    return 2


def pop_flag(args: list[str], flag: str) -> bool:
    if flag in args:
        args.remove(flag)
        return True
    return False


def pop_value(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag not in args:
        return default
    idx = args.index(flag)
    if idx + 1 >= len(args):
        raise ValueError(f"{flag} requires a value")
    value = args[idx + 1]
    del args[idx : idx + 2]
    return value


def pop_optional_value(
    args: list[str], flag: str, default: str | None = None
) -> str | None:
    if flag not in args:
        return default
    idx = args.index(flag)
    if idx + 1 >= len(args):
        del args[idx]
        return default
    next_token = args[idx + 1]
    if next_token.startswith("--"):
        del args[idx]
        return default
    del args[idx : idx + 2]
    return next_token


def emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def normalize_args(args: list[str]) -> list[str]:
    normalized: list[str] = []
    for token in args:
        value = token.strip()
        if value.startswith("—"):
            value = "--" + value.lstrip("—")
        elif value.startswith("–"):
            value = "--" + value.lstrip("–")
        normalized.append(value)
    return normalized


def normalize_goal(goal: str | None) -> str:
    value = str(goal or "").strip()
    if not value:
        return ""
    lowered = value.lower()
    if lowered in {"$arguments", "${arguments}"}:
        return ""
    if lowered.startswith("${arguments:-") and lowered.endswith("}"):
        return ""
    if lowered in {'"$arguments"', "'$arguments'"}:
        return ""
    return value


def gateway_runtime_status(cwd: Path, config: dict[str, Any]) -> dict[str, Any]:
    home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    status = status_payload(config, home, cwd, cleanup_orphans=False)
    return status if isinstance(status, dict) else {}


def gateway_state_snapshot(cwd: Path, config: dict[str, Any]) -> dict[str, Any]:
    cleanup_path, changed, reason = cleanup_orphan_loop(cwd)
    gateway_status = gateway_runtime_status(cwd, config)
    return {
        "gateway_runtime_mode": gateway_status.get("runtime_mode"),
        "gateway_runtime_reason_code": gateway_status.get("runtime_reason_code"),
        "gateway_plugin_enabled": gateway_status.get("enabled"),
        "gateway_bun_available": gateway_status.get("bun_available"),
        "gateway_missing_hook_capabilities": gateway_status.get(
            "missing_hook_capabilities", []
        ),
        "gateway_loop_state": gateway_status.get("loop_state"),
        "gateway_loop_state_reason_code": gateway_status.get("loop_state_reason_code"),
        "gateway_orphan_cleanup": {
            "attempted": True,
            "changed": changed,
            "reason": reason,
            "state_path": str(cleanup_path) if cleanup_path else None,
        },
    }


def infer_touched_paths(cwd: Path) -> list[str]:
    inside = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    if inside.returncode != 0:
        return []

    commands = [
        ["git", "-C", str(cwd), "diff", "--name-only", "--diff-filter=ACMR"],
        [
            "git",
            "-C",
            str(cwd),
            "diff",
            "--name-only",
            "--cached",
            "--diff-filter=ACMR",
        ],
        ["git", "-C", str(cwd), "ls-files", "--others", "--exclude-standard"],
    ]
    ignored_prefixes = (".beads/", ".opencode/")

    def include_path(path: str) -> bool:
        if path.startswith(ignored_prefixes):
            return False
        if path.startswith("node_modules/"):
            return False
        if path.startswith("plugin/autopilot-loop/node_modules/"):
            return False
        if path.startswith("plugin/gateway-core/node_modules/"):
            return False
        if "/node_modules/" in path:
            return False
        return True

    discovered: list[str] = []
    for cmd in commands:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except Exception:
            continue
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines():
            path = line.strip()
            if path and include_path(path) and path not in discovered:
                discovered.append(path)
            if len(discovered) >= 200:
                return discovered
    return discovered


def _runtime_or_fail(
    write_path: Path, *, as_json: bool
) -> tuple[dict[str, Any] | None, int]:
    runtime = load_runtime(write_path)
    if runtime:
        return runtime, 0
    emit(
        {
            "result": "FAIL",
            "reason_code": "autopilot_runtime_missing",
            "remediation": [
                "run /autopilot start with required objective fields",
                "use /autopilot doctor --json to inspect subsystem readiness",
            ],
        },
        as_json=as_json,
    )
    return None, 1


def command_start(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    try:
        goal = pop_optional_value(args, "--goal", "")
        scope = pop_optional_value(args, "--scope", "")
        done_criteria = pop_optional_value(args, "--done-criteria", "")
        completion_mode = (
            (pop_value(args, "--completion-mode", "promise") or "promise")
            .strip()
            .lower()
        )
        completion_promise = pop_value(args, "--completion-promise", "DONE") or "DONE"
        max_budget = pop_value(args, "--max-budget", "balanced")
    except ValueError:
        return usage()
    if args:
        return usage()

    inferred_defaults: list[str] = []
    goal = normalize_goal(goal)
    if completion_mode not in {"promise", "objective"}:
        return usage()
    inferred_continuous = completion_mode == "objective"
    if not goal:
        goal = (
            "continue the active user request from current session context until done"
        )
        inferred_defaults.append("goal")
    if not scope:
        scope = "**"
        inferred_defaults.append("scope")
    if not done_criteria:
        done_criteria = [
            "advance the highest-priority remaining subtask",
            "apply and validate concrete changes for that subtask",
            "repeat until the objective is fully complete",
        ]
        inferred_defaults.append("done-criteria")

    config, _ = load_layered_config()
    write_path = resolve_write_path()
    objective = {
        "goal": goal or "",
        "scope": scope or "",
        "done-criteria": done_criteria or "",
        "max-budget": max_budget or "balanced",
        "continuous_mode": inferred_continuous,
        "completion_mode": completion_mode,
        "completion_promise": completion_promise,
    }
    initialized = initialize_run(
        config=config,
        write_path=write_path,
        objective=objective,
        actor="autopilot",
    )
    if inferred_defaults:
        initialized["inferred_defaults"] = inferred_defaults
        initialized["warnings"] = initialized.get("warnings", [])
        if isinstance(initialized["warnings"], list):
            initialized["warnings"].append(
                "autopilot inferred missing objective fields; use explicit fields for tighter control"
            )
    run_any = initialized.get("run")
    if isinstance(run_any, dict):
        runtime_status = gateway_runtime_status(Path.cwd(), config)
        runtime_mode = str(
            runtime_status.get("runtime_mode") or "python_command_bridge"
        )
        bridge_state_path: Path | None = None
        if runtime_mode == "python_command_bridge":
            bridge_state_path = bridge_start_loop(Path.cwd(), run_any)
        initialized["gateway_loop_state_path"] = str(
            bridge_state_path or gateway_loop_state_path(Path.cwd())
        )
        initialized["gateway_runtime_mode"] = runtime_status.get("runtime_mode")
        initialized["gateway_runtime_reason_code"] = runtime_status.get(
            "runtime_reason_code"
        )
        initialized["gateway_plugin_enabled"] = runtime_status.get("enabled")
        initialized["gateway_bun_available"] = runtime_status.get("bun_available")
        initialized["gateway_missing_hook_capabilities"] = runtime_status.get(
            "missing_hook_capabilities", []
        )
    emit(initialized, as_json=as_json)
    return 0 if initialized.get("result") == "PASS" else 1


def command_go(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    completion_signal = pop_flag(args, "--completion-signal")
    explicit_goal = "--goal" in args
    explicit_scope = "--scope" in args
    explicit_done_criteria = "--done-criteria" in args
    explicit_completion_mode = "--completion-mode" in args
    explicit_completion_promise = "--completion-promise" in args
    explicit_max_budget = "--max-budget" in args
    try:
        goal = pop_optional_value(args, "--goal", "")
        scope = pop_optional_value(args, "--scope", "")
        done_criteria = pop_optional_value(args, "--done-criteria", "")
        completion_mode = (
            (pop_value(args, "--completion-mode", "promise") or "promise")
            .strip()
            .lower()
        )
        completion_promise = pop_value(args, "--completion-promise", "DONE") or "DONE"
        max_budget = pop_value(args, "--max-budget", "balanced") or "balanced"
        confidence_raw = pop_value(args, "--confidence", "0.8") or "0.8"
        tool_calls_raw = pop_value(args, "--tool-calls", "1") or "1"
        token_raw = pop_value(args, "--token-estimate", "100") or "100"
        touched_paths_raw = pop_value(args, "--touched-paths", "") or ""
        assistant_text = pop_value(args, "--assistant-text", "") or ""
        max_cycles_raw = pop_value(args, "--max-cycles", "20") or "20"
    except ValueError:
        return usage()
    if args:
        return usage()

    try:
        confidence = float(confidence_raw)
        tool_calls = max(0, int(tool_calls_raw))
        token_estimate = max(0, int(token_raw))
        max_cycles = max(1, int(max_cycles_raw))
    except ValueError:
        return usage()

    touched_paths = [
        path.strip() for path in touched_paths_raw.split(",") if path.strip()
    ]
    inferred_touched_paths: list[str] = []
    if not touched_paths:
        inferred_touched_paths = infer_touched_paths(Path.cwd())
        touched_paths = list(inferred_touched_paths)

    no_touched_paths = len(touched_paths) == 0
    cycle_cap_warning = False
    if no_touched_paths and max_cycles > 1:
        max_cycles = 1
        cycle_cap_warning = True

    config, _ = load_layered_config()
    write_path = resolve_write_path()
    goal = normalize_goal(goal)

    runtime = load_runtime(write_path)
    started_new_run = False
    inferred_defaults: list[str] = []
    if completion_mode not in {"promise", "objective"}:
        return usage()
    inferred_continuous = completion_mode == "objective"
    terminal_states = {
        "completed",
        "budget_stopped",
        "scope_stopped",
        "stopped",
    }
    runtime_status = str(runtime.get("status") or "") if runtime else ""
    runtime_legacy_inferred = False
    runtime_budget_exhausted = False
    if runtime:
        objective_any = runtime.get("objective")
        objective = objective_any if isinstance(objective_any, dict) else {}
        objective_goal = str(objective.get("goal") or "").strip()
        objective_criteria_any = objective.get("done_criteria")
        objective_criteria = (
            objective_criteria_any if isinstance(objective_criteria_any, list) else []
        )
        objective_continuous = bool(objective.get("continuous_mode", False))
        runtime_legacy_inferred = (
            (not goal)
            and (not scope)
            and (not done_criteria)
            and (not objective_continuous)
            and objective_goal
            == "continue the active user request from current session context until done"
            and len(objective_criteria) == 1
        )

        budget_any = runtime.get("budget")
        budget = budget_any if isinstance(budget_any, dict) else {}
        counters_any = budget.get("counters")
        counters = counters_any if isinstance(counters_any, dict) else {}
        policy_any = budget.get("policy")
        policy = policy_any if isinstance(policy_any, dict) else {}
        limits_any = policy.get("limits")
        limits = limits_any if isinstance(limits_any, dict) else {}
        wall = int(counters.get("wall_clock_seconds", 0) or 0)
        wall_limit = int(limits.get("wall_clock_seconds", 0) or 0)
        runtime_budget_exhausted = wall_limit > 0 and wall >= wall_limit

    explicit_objective_override = any(
        [
            explicit_goal,
            explicit_scope,
            explicit_done_criteria,
            explicit_completion_mode,
            explicit_completion_promise,
            explicit_max_budget,
        ]
    )

    should_initialize = (
        not runtime
        or runtime_status in terminal_states
        or runtime_budget_exhausted
        or runtime_legacy_inferred
        or explicit_objective_override
    )

    if should_initialize:
        if not goal:
            goal = "continue the active user request from current session context until done"
            inferred_defaults.append("goal")
        if not scope:
            scope = "**"
            inferred_defaults.append("scope")
        if not done_criteria:
            done_criteria = [
                "advance the highest-priority remaining subtask",
                "apply and validate concrete changes for that subtask",
                "repeat until the objective is fully complete",
            ]
            inferred_defaults.append("done-criteria")
        objective = {
            "goal": goal or "",
            "scope": scope or "",
            "done-criteria": done_criteria or "",
            "max-budget": max_budget,
            "continuous_mode": inferred_continuous,
            "completion_mode": completion_mode,
            "completion_promise": completion_promise,
        }
        initialized = initialize_run(
            config=config,
            write_path=write_path,
            objective=objective,
            actor="autopilot",
        )
        if initialized.get("result") != "PASS":
            emit(initialized, as_json=as_json)
            return 1
        run_any = initialized.get("run")
        runtime = run_any if isinstance(run_any, dict) else {}
        started_new_run = True
        if runtime:
            runtime_status = gateway_runtime_status(Path.cwd(), config)
            runtime_mode = str(
                runtime_status.get("runtime_mode") or "python_command_bridge"
            )
            if runtime_mode == "python_command_bridge":
                bridge_start_loop(Path.cwd(), runtime)

    if not runtime:
        emit(
            {
                "result": "FAIL",
                "reason_code": "autopilot_runtime_missing",
                "remediation": [
                    "run /autopilot start with objective fields",
                    "run /autopilot go --goal '<objective>'",
                ],
            },
            as_json=as_json,
        )
        return 1

    history: list[dict[str, Any]] = []
    current = runtime
    for _ in range(max_cycles):
        integrated = integrate_controls(
            run=current,
            write_path=write_path,
            confidence_score=confidence,
        )
        handoff_mode = (
            integrated.get("control_integrations", {})
            .get("manual_handoff", {})
            .get("mode", "auto")
        )
        if handoff_mode == "manual":
            run_any = integrated.get("run")
            current = run_any if isinstance(run_any, dict) else current
            history.append(
                {
                    "status": current.get("status"),
                    "reason_code": current.get("reason_code"),
                }
            )
            break

        resumed = execute_cycle(
            config=config,
            write_path=write_path,
            run=integrated.get("run", current),
            tool_call_increment=tool_calls,
            token_increment=token_estimate,
            touched_paths=touched_paths,
            completion_signal=completion_signal,
            assistant_text=assistant_text,
        )
        run_any = resumed.get("run")
        current = run_any if isinstance(run_any, dict) else current
        history.append(
            {
                "status": current.get("status"),
                "reason_code": current.get("reason_code"),
            }
        )
        status = str(current.get("status") or "")
        if status in terminal_states:
            break

    status = str(current.get("status") or "")
    reason_code = str(current.get("reason_code") or "")
    result = "PASS"
    if status in {"budget_stopped", "scope_stopped"}:
        result = "FAIL"
    if history and history[-1].get("reason_code") == "confidence_drop_requires_handoff":
        result = "FAIL"

    payload: dict[str, Any] = {
        "result": result,
        "started_new_run": started_new_run,
        "iterations": len(history),
        "final_status": status,
        "reason_code": reason_code,
        "run": current,
        "history": history,
        "next_actions": current.get("next_actions", []),
    }
    payload.update(gateway_state_snapshot(Path.cwd(), config))
    if inferred_defaults:
        payload["inferred_defaults"] = inferred_defaults
        payload["warnings"] = [
            "autopilot inferred missing objective fields; use explicit fields for tighter control"
        ]
    if len(history) >= max_cycles and status not in terminal_states:
        payload.setdefault("warnings", [])
        if isinstance(payload["warnings"], list):
            payload["warnings"].append(
                "max cycles reached before terminal status; run /autopilot go again to continue"
            )
    if cycle_cap_warning:
        payload.setdefault("warnings", [])
        if isinstance(payload["warnings"], list):
            payload["warnings"].append(
                "autopilot received no touched paths; executed one guarded cycle only"
            )
    if inferred_touched_paths:
        payload["inferred_touched_paths"] = inferred_touched_paths
    emit(payload, as_json=as_json)
    return 0 if result == "PASS" else 1


def command_status(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    try:
        confidence_raw = pop_value(args, "--confidence", "0.8") or "0.8"
        interruption_class = (
            pop_value(args, "--interruption-class", "tool_failure") or "tool_failure"
        )
    except ValueError:
        return usage()
    if args:
        return usage()
    try:
        confidence = float(confidence_raw)
    except ValueError:
        return usage()

    config, _ = load_layered_config()
    write_path = resolve_write_path()
    runtime = load_runtime(write_path)
    if not runtime:
        idle_payload = {
            "result": "PASS",
            "status": "idle",
            "reason_code": "autopilot_runtime_missing",
            "warnings": [
                "autopilot has no active runtime yet; start a run to track status"
            ],
            "next_actions": [
                "run /autopilot start with required objective fields",
                "use /autopilot doctor --json to inspect subsystem readiness",
            ],
        }
        idle_payload.update(gateway_state_snapshot(Path.cwd(), config))
        emit(
            idle_payload,
            as_json=as_json,
        )
        return 0

    integrated = integrate_controls(
        run=runtime,
        write_path=write_path,
        confidence_score=confidence,
        interruption_class=interruption_class,
    )
    integrated.update(gateway_state_snapshot(Path.cwd(), config))
    emit(integrated, as_json=as_json)
    return 0


def command_pause(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    if args:
        return usage()

    config, _ = load_layered_config()
    write_path = resolve_write_path()
    runtime, code = _runtime_or_fail(write_path, as_json=as_json)
    if runtime is None:
        return code

    runtime["status"] = "paused"
    runtime["reason_code"] = "operator_paused"
    runtime["next_actions"] = [
        "review blockers and confidence before resume",
        "run /autopilot resume when safe to continue",
    ]
    path = save_runtime(write_path, runtime)
    runtime_status = gateway_runtime_status(Path.cwd(), config)
    bridge_state_path = None
    if runtime_status.get("runtime_mode") == "python_command_bridge":
        bridge_state_path = bridge_stop_loop(Path.cwd())
    payload = {
        "result": "PASS",
        "status": runtime["status"],
        "reason_code": runtime["reason_code"],
        "runtime_path": str(path),
        "gateway_loop_state_path": str(
            bridge_state_path or gateway_loop_state_path(Path.cwd())
        ),
    }
    payload.update(gateway_state_snapshot(Path.cwd(), config))
    emit(payload, as_json=as_json)
    return 0


def command_resume(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    completion_signal = pop_flag(args, "--completion-signal")
    try:
        confidence_raw = pop_value(args, "--confidence", "0.8") or "0.8"
        tool_calls_raw = pop_value(args, "--tool-calls", "1") or "1"
        token_raw = pop_value(args, "--token-estimate", "100") or "100"
        touched_paths_raw = pop_value(args, "--touched-paths", "") or ""
        assistant_text = pop_value(args, "--assistant-text", "") or ""
    except ValueError:
        return usage()
    if args:
        return usage()
    try:
        confidence = float(confidence_raw)
        tool_calls = max(0, int(tool_calls_raw))
        token_estimate = max(0, int(token_raw))
    except ValueError:
        return usage()
    touched_paths = [
        path.strip() for path in touched_paths_raw.split(",") if path.strip()
    ]
    inferred_touched_paths: list[str] = []
    if not touched_paths:
        inferred_touched_paths = infer_touched_paths(Path.cwd())
        touched_paths = list(inferred_touched_paths)

    config, _ = load_layered_config()
    write_path = resolve_write_path()
    runtime, code = _runtime_or_fail(write_path, as_json=as_json)
    if runtime is None:
        return code

    integrated = integrate_controls(
        run=runtime,
        write_path=write_path,
        confidence_score=confidence,
    )
    handoff_mode = (
        integrated.get("control_integrations", {})
        .get("manual_handoff", {})
        .get("mode", "auto")
    )
    if handoff_mode == "manual":
        emit(integrated, as_json=as_json)
        return 1

    resumed = execute_cycle(
        config=config,
        write_path=write_path,
        run=integrated.get("run", runtime),
        tool_call_increment=tool_calls,
        token_increment=token_estimate,
        touched_paths=touched_paths,
        completion_signal=completion_signal,
        assistant_text=assistant_text,
    )
    runtime_status = gateway_runtime_status(Path.cwd(), config)
    if runtime_status.get("runtime_mode") == "python_command_bridge":
        run_any = resumed.get("run")
        run = run_any if isinstance(run_any, dict) else None
        if isinstance(run, dict) and str(run.get("status") or "") in {
            "draft",
            "running",
            "paused",
        }:
            resumed["gateway_loop_state_path"] = str(bridge_start_loop(Path.cwd(), run))
    if inferred_touched_paths:
        resumed["inferred_touched_paths"] = inferred_touched_paths
    resumed.update(gateway_state_snapshot(Path.cwd(), config))
    emit(resumed, as_json=as_json)
    return 0 if resumed.get("result") == "PASS" else 1


def command_stop(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    reason = "manual"
    try:
        reason = pop_value(args, "--reason", "manual") or "manual"
    except ValueError:
        return usage()
    if args:
        return usage()

    config, _ = load_layered_config()
    write_path = resolve_write_path()
    runtime, code = _runtime_or_fail(write_path, as_json=as_json)
    if runtime is None:
        return code

    runtime["status"] = "stopped"
    runtime["reason_code"] = "autopilot_stop_requested"
    runtime["stop_reason"] = reason
    runtime["next_actions"] = [
        "use /autopilot report to inspect final progress and blockers",
        "use /autopilot start to begin a new objective run",
    ]
    path = save_runtime(write_path, runtime)
    runtime_status = gateway_runtime_status(Path.cwd(), config)
    bridge_state_path = None
    if runtime_status.get("runtime_mode") == "python_command_bridge":
        bridge_state_path = bridge_stop_loop(Path.cwd())
    payload = {
        "result": "PASS",
        "status": runtime["status"],
        "reason_code": runtime["reason_code"],
        "stop_reason": runtime["stop_reason"],
        "runtime_path": str(path),
        "gateway_loop_state_path": str(
            bridge_state_path or gateway_loop_state_path(Path.cwd())
        ),
    }
    payload.update(gateway_state_snapshot(Path.cwd(), config))
    emit(payload, as_json=as_json)
    return 0


def command_report(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    if args:
        return usage()

    config, _ = load_layered_config()
    write_path = resolve_write_path()
    runtime, code = _runtime_or_fail(write_path, as_json=as_json)
    if runtime is None:
        return code

    progress = (
        runtime.get("progress", {}) if isinstance(runtime.get("progress"), dict) else {}
    )
    payload = {
        "result": "PASS",
        "run_id": runtime.get("run_id"),
        "status": runtime.get("status"),
        "reason_code": runtime.get("reason_code"),
        "summary": {
            "goal": runtime.get("objective", {}).get("goal")
            if isinstance(runtime.get("objective"), dict)
            else None,
            "completed_cycles": progress.get("completed_cycles", 0),
            "pending_cycles": progress.get("pending_cycles", 0),
        },
        "blockers": runtime.get("blockers", []),
        "next_actions": runtime.get("next_actions", []),
    }
    payload.update(gateway_state_snapshot(Path.cwd(), config))
    emit(payload, as_json=as_json)
    return 0


def command_doctor(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    as_json = "--json" in args
    plugin_root = SCRIPT_DIR.parent / "plugin" / "autopilot-loop"
    plugin_scaffold_exists = (plugin_root / "src" / "index.ts").exists()
    plugin_dist_exists = (plugin_root / "dist" / "index.js").exists()
    config, _ = load_layered_config()
    home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    gateway_root = plugin_dir(home)
    gateway_hooks = hook_diagnostics(gateway_root)
    gateway_status = status_payload(config, home, Path.cwd(), cleanup_orphans=False)
    report = {
        "result": "PASS",
        "runtime_exists": (SCRIPT_DIR / "autopilot_runtime.py").exists(),
        "integration_exists": (SCRIPT_DIR / "autopilot_integration.py").exists(),
        "contract_exists": (
            SCRIPT_DIR.parent / "instructions" / "autopilot_command_contract.md"
        ).exists(),
        "hook_plugin_scaffold_exists": plugin_scaffold_exists,
        "hook_plugin_dist_exists": plugin_dist_exists,
        "gateway_plugin_dir": str(gateway_root),
        "gateway_hook_diagnostics": gateway_hooks,
        "gateway_runtime_mode": gateway_status.get("runtime_mode"),
        "gateway_runtime_reason_code": gateway_status.get("runtime_reason_code"),
        "gateway_plugin_enabled": gateway_status.get("enabled"),
        "gateway_bun_available": gateway_status.get("bun_available"),
        "gateway_missing_hook_capabilities": gateway_status.get(
            "missing_hook_capabilities", []
        ),
        "warnings": [],
        "problems": [],
        "quick_fixes": [
            "/autopilot start --goal 'Ship objective' --scope 'scripts/**' --done-criteria 'all checks pass' --max-budget balanced --json",
            "/autopilot go --goal 'Ship objective' --json",
            "/autopilot status --json",
            "/autopilot report --json",
        ],
    }
    if not report["runtime_exists"]:
        report["problems"].append("missing scripts/autopilot_runtime.py")
    if not report["integration_exists"]:
        report["problems"].append("missing scripts/autopilot_integration.py")
    if not report["contract_exists"]:
        report["warnings"].append("missing instructions/autopilot_command_contract.md")
    if not report["hook_plugin_scaffold_exists"]:
        report["warnings"].append(
            "autopilot-loop hook plugin scaffold missing (plugin/autopilot-loop/src/index.ts)"
        )
    if report["hook_plugin_scaffold_exists"] and not report["hook_plugin_dist_exists"]:
        report["warnings"].append(
            "autopilot-loop plugin not built yet (run install.sh or npm run build in plugin/autopilot-loop)"
        )
    if gateway_hooks.get("dist_index_exists") is not True:
        report["warnings"].append(
            "gateway-core dist plugin is missing (run npm run build in plugin/gateway-core)"
        )
    if (
        report.get("gateway_bun_available") is True
        and report.get("gateway_plugin_enabled") is not True
    ):
        report["warnings"].append(
            "gateway plugin runtime is available but disabled; run /gateway enable for plugin-first mode"
        )
    required_gateway_flags = [
        "dist_exposes_tool_execute_before",
        "dist_exposes_chat_message",
        "dist_autopilot_handles_slashcommand",
        "dist_continuation_handles_session_idle",
        "dist_safety_handles_session_deleted",
        "dist_safety_handles_session_error",
    ]
    if gateway_hooks.get("dist_index_exists") is True:
        missing_gateway = [
            flag
            for flag in required_gateway_flags
            if gateway_hooks.get(flag) is not True
        ]
        if missing_gateway:
            report["problems"].append(
                "gateway-core hook capabilities missing: " + ", ".join(missing_gateway)
            )
    if report["problems"]:
        report["result"] = "FAIL"
    emit(report, as_json=as_json)
    return 0 if report["result"] == "PASS" else 1


def main(argv: list[str]) -> int:
    argv = normalize_args(list(argv))
    if not argv:
        return command_go(["--json"])
    cmd, *rest = argv
    if cmd in {"help", "--help", "-h"}:
        return usage()
    if cmd == "start":
        return command_start(rest)
    if cmd == "go":
        if rest and not any(token.startswith("-") for token in rest):
            return command_go(["--goal", " ".join(rest), "--json"])
        return command_go(rest)
    if cmd == "continue":
        if rest and not any(token.startswith("-") for token in rest):
            return command_go(["--goal", " ".join(rest), "--json"])
        return command_go(rest)
    if cmd == "status":
        return command_status(rest)
    if cmd == "pause":
        return command_pause(rest)
    if cmd == "resume":
        return command_resume(rest)
    if cmd == "stop":
        return command_stop(rest)
    if cmd == "report":
        return command_report(rest)
    if cmd == "doctor":
        return command_doctor(rest)
    if cmd.startswith("-"):
        return command_go(argv)
    return command_go(["--goal", " ".join(argv), "--json"])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
