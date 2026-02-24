#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_STATE_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_WORKFLOW_STATE_PATH",
        "~/.config/opencode/my_opencode/runtime/workflow_state.json",
    )
).expanduser()

DEFAULT_TEMPLATE_DIR = Path(
    os.environ.get(
        "MY_OPENCODE_WORKFLOW_TEMPLATE_DIR",
        "~/.config/opencode/my_opencode/workflows",
    )
).expanduser()


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def usage() -> int:
    print(
        "usage: /workflow run --file <path> [--execute] [--json] | /workflow validate --file <path> [--json] | "
        "/workflow list [--json] | /workflow status [--json] | /workflow stop [--reason <text>] [--json] | "
        "/workflow template list [--json] | /workflow template init <name> [--json] | /workflow doctor [--json]"
    )
    return 2


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def save_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def history_list(state: dict[str, Any]) -> list[dict[str, Any]]:
    raw_history = state.get("history")
    if not isinstance(raw_history, list):
        state["history"] = []
        return state["history"]
    return [item for item in raw_history if isinstance(item, dict)]


def active_record(state: dict[str, Any]) -> dict[str, Any]:
    raw_active = state.get("active")
    if isinstance(raw_active, dict):
        return raw_active
    state["active"] = {}
    return state["active"]


def parse_flag_value(argv: list[str], flag: str) -> str | None:
    if flag not in argv:
        return None
    idx = argv.index(flag)
    if idx + 1 >= len(argv):
        raise ValueError(f"{flag} requires value")
    value = argv[idx + 1]
    del argv[idx : idx + 2]
    return value


def emit(payload: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        if payload.get("result") != "PASS":
            print(f"error: {payload.get('error', 'workflow command failed')}")
            return 1
        print(f"result: {payload.get('result')}")
        if payload.get("run_id"):
            print(f"run_id: {payload.get('run_id')}")
        if payload.get("status"):
            print(f"status: {payload.get('status')}")
    return 0 if payload.get("result") == "PASS" else 1


def validate_workflow(workflow: dict[str, Any]) -> tuple[bool, list[str]]:
    issues: list[str] = []
    if (
        not isinstance(workflow.get("name"), str)
        or not str(workflow.get("name")).strip()
    ):
        issues.append("missing workflow name")
    steps = workflow.get("steps")
    if not isinstance(steps, list) or not steps:
        issues.append("missing workflow steps")
    else:
        seen_ids: set[str] = set()
        for idx, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                issues.append(f"step {idx} must be object")
                continue
            step_id = str(step.get("id") or "").strip()
            if not step_id:
                issues.append(f"step {idx} missing id")
            elif step_id in seen_ids:
                issues.append(f"duplicate step id: {step_id}")
            else:
                seen_ids.add(step_id)
            if (
                not isinstance(step.get("action"), str)
                or not str(step.get("action")).strip()
            ):
                issues.append(f"step {idx} missing action")
            depends_on = step.get("depends_on")
            if depends_on is not None and not isinstance(depends_on, list):
                issues.append(f"step {idx} depends_on must be list")
    return (not issues, issues)


def resolve_step_order(
    steps: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    by_id: dict[str, dict[str, Any]] = {}
    deps: dict[str, set[str]] = {}
    reverse_edges: dict[str, set[str]] = {}
    issues: list[str] = []

    for step in steps:
        step_id = str(step.get("id") or "").strip()
        if not step_id:
            continue
        by_id[step_id] = step
        deps[step_id] = set()
        reverse_edges[step_id] = set()

    for step_id, step in by_id.items():
        raw_depends = step.get("depends_on")
        if raw_depends is None:
            continue
        if not isinstance(raw_depends, list):
            issues.append(f"step {step_id} has invalid depends_on")
            continue
        for dep in raw_depends:
            dep_id = str(dep).strip()
            if not dep_id:
                continue
            if dep_id not in by_id:
                issues.append(f"step {step_id} depends on unknown step {dep_id}")
                continue
            deps[step_id].add(dep_id)
            reverse_edges[dep_id].add(step_id)

    if issues:
        return [], issues

    queue = sorted(step_id for step_id, d in deps.items() if not d)
    ordered_ids: list[str] = []
    while queue:
        current = queue.pop(0)
        ordered_ids.append(current)
        for dependent in sorted(reverse_edges[current]):
            if current in deps[dependent]:
                deps[dependent].remove(current)
            if (
                not deps[dependent]
                and dependent not in ordered_ids
                and dependent not in queue
            ):
                queue.append(dependent)

    if len(ordered_ids) != len(by_id):
        return [], ["workflow dependency cycle detected"]

    return [by_id[step_id] for step_id in ordered_ids], []


def run_command_step(step: dict[str, Any]) -> tuple[str, str | None, str, int | None]:
    raw_command = step.get("command")
    tokens: list[str]
    if isinstance(raw_command, list):
        tokens = [str(token) for token in raw_command if str(token).strip()]
    elif isinstance(raw_command, str):
        tokens = shlex.split(raw_command)
    else:
        return "failed", "invalid_command_step", "command field missing", None

    if not tokens:
        return "failed", "invalid_command_step", "empty command tokens", None

    executable = tokens[0]
    if executable not in {"python3", "make"}:
        return (
            "failed",
            "command_not_allowed",
            f"executable not allowed: {executable}",
            None,
        )
    if executable == "make":
        target = tokens[1] if len(tokens) > 1 else ""
        if target not in {"validate", "selftest", "install-test"}:
            return (
                "failed",
                "command_not_allowed",
                f"make target not allowed: {target}",
                None,
            )
    if executable == "python3" and len(tokens) > 1:
        script_target = tokens[1]
        if not script_target.startswith("scripts/"):
            return (
                "failed",
                "command_not_allowed",
                "python3 command must target scripts/*",
                None,
            )

    completed = subprocess.run(
        tokens, capture_output=True, text=True, check=False, timeout=120000
    )
    if completed.returncode != 0:
        detail = (
            completed.stderr or completed.stdout or "command execution failed"
        ).strip()
        return "failed", "command_exit_nonzero", detail[:500], completed.returncode
    detail = (completed.stdout or "command executed").strip()
    return "passed", None, detail[:500], completed.returncode


def execute_steps(
    steps: list[dict[str, Any]], execute_commands: bool
) -> tuple[str, list[dict[str, Any]], str | None]:
    results: list[dict[str, Any]] = []
    failed_step_id: str | None = None
    for step in steps:
        step_id = str(step.get("id") or "unknown-step")
        action = str(step.get("action") or "")
        started_at = now_iso()
        status = "passed"
        reason_code = None
        detail = "executed"
        if not action:
            status = "failed"
            reason_code = "missing_step_action"
            detail = "step action is required"
            failed_step_id = step_id
        elif execute_commands and step.get("command") is not None:
            status, reason_code, detail, _ = run_command_step(step)
            if status == "failed":
                failed_step_id = step_id
        elif action in {"fail", "error"} or str(step.get("simulate") or "") == "fail":
            status = "failed"
            reason_code = "step_failed"
            detail = "step requested failure"
            failed_step_id = step_id
        elif step.get("command") is not None:
            detail = "dry-run command step (use --execute)"
        results.append(
            {
                "id": step_id,
                "action": action,
                "status": status,
                "reason_code": reason_code,
                "detail": detail,
                "depends_on": step.get("depends_on")
                if isinstance(step.get("depends_on"), list)
                else [],
                "started_at": started_at,
                "finished_at": now_iso(),
            }
        )
        if status == "failed":
            break
    if failed_step_id:
        return "failed", results, failed_step_id
    return "completed", results, None


def load_workflow_file(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    if not path.exists():
        return None, [f"workflow file not found: {path}"]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [f"invalid json: {exc}"]
    if not isinstance(raw, dict):
        return None, ["workflow root must be object"]
    ok, issues = validate_workflow(raw)
    return (raw, []) if ok else (raw, issues)


def cmd_validate(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    try:
        file_arg = parse_flag_value(argv, "--file")
    except ValueError:
        return usage()
    if not file_arg:
        return usage()
    workflow, issues = load_workflow_file(Path(file_arg).expanduser())
    if issues:
        return emit(
            {
                "result": "FAIL",
                "command": "validate",
                "issues": issues,
                "error": issues[0],
            },
            as_json,
        )
    return emit(
        {
            "result": "PASS",
            "command": "validate",
            "workflow": workflow,
            "issues": [],
        },
        as_json,
    )


def cmd_run(argv: list[str]) -> int:
    as_json = "--json" in argv
    execute_commands = "--execute" in argv
    argv = [a for a in argv if a not in {"--json", "--execute"}]
    try:
        file_arg = parse_flag_value(argv, "--file")
    except ValueError:
        return usage()
    if not file_arg:
        return usage()
    workflow_path = Path(file_arg).expanduser()
    workflow, issues = load_workflow_file(workflow_path)
    if issues or not isinstance(workflow, dict):
        return emit(
            {"result": "FAIL", "command": "run", "issues": issues, "error": issues[0]},
            as_json,
        )

    state = load_json_file(DEFAULT_STATE_PATH)
    active = active_record(state)
    if active and str(active.get("status") or "") == "running":
        return emit(
            {
                "result": "FAIL",
                "command": "run",
                "error": "workflow run already active",
                "reason_code": "workflow_already_running",
                "active_run_id": active.get("run_id"),
            },
            as_json,
        )

    history = history_list(state)
    run_id = f"wf-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    raw_steps = workflow.get("steps")
    steps = raw_steps if isinstance(raw_steps, list) else []
    normalized_steps = [step for step in steps if isinstance(step, dict)]
    ordered_steps, order_issues = resolve_step_order(normalized_steps)
    if order_issues:
        return emit(
            {
                "result": "FAIL",
                "command": "run",
                "error": order_issues[0],
                "issues": order_issues,
                "reason_code": "workflow_dependency_error",
            },
            as_json,
        )

    status, step_results, failed_step_id = execute_steps(
        ordered_steps, execute_commands
    )
    run_record = {
        "run_id": run_id,
        "name": workflow.get("name"),
        "path": str(workflow_path),
        "status": status,
        "execution_mode": "execute" if execute_commands else "dry-run",
        "step_count": len(normalized_steps),
        "completed_steps": sum(
            1 for step in step_results if step.get("status") == "passed"
        ),
        "failed_step_id": failed_step_id,
        "ordered_step_ids": [str(step.get("id") or "") for step in ordered_steps],
        "steps": step_results,
        "started_at": now_iso(),
        "finished_at": now_iso(),
    }
    state["active"] = {}
    history.insert(0, run_record)
    state["history"] = history[:50]
    save_json_file(DEFAULT_STATE_PATH, state)
    return emit({"result": "PASS", "command": "run", **run_record}, as_json)


def cmd_status(argv: list[str]) -> int:
    as_json = "--json" in argv
    state = load_json_file(DEFAULT_STATE_PATH)
    active = active_record(state)
    if not active:
        history = history_list(state)
        latest = history[0] if history and isinstance(history[0], dict) else {}
        return emit(
            {
                "result": "PASS",
                "command": "status",
                "status": "idle",
                "warnings": ["no active workflow run"],
                "latest": latest,
            },
            as_json,
        )
    return emit({"result": "PASS", "command": "status", **active}, as_json)


def cmd_stop(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    reason = "manual stop"
    try:
        reason_arg = parse_flag_value(argv, "--reason")
    except ValueError:
        return usage()
    if reason_arg:
        reason = reason_arg
    state = load_json_file(DEFAULT_STATE_PATH)
    active = active_record(state)
    if not active:
        return emit(
            {
                "result": "PASS",
                "command": "stop",
                "status": "idle",
                "warnings": ["no active workflow run"],
            },
            as_json,
        )
    active["status"] = "stopped"
    active["stopped_at"] = now_iso()
    active["stop_reason"] = reason
    state["active"] = {}
    history = history_list(state)
    if (
        history
        and isinstance(history[0], dict)
        and history[0].get("run_id") == active.get("run_id")
    ):
        history[0] = active
    state["history"] = history
    save_json_file(DEFAULT_STATE_PATH, state)
    return emit({"result": "PASS", "command": "stop", **active}, as_json)


def cmd_list(argv: list[str]) -> int:
    as_json = "--json" in argv
    state = load_json_file(DEFAULT_STATE_PATH)
    history = history_list(state)
    return emit(
        {
            "result": "PASS",
            "command": "list",
            "count": len(history),
            "runs": history,
        },
        as_json,
    )


def cmd_template(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if not argv:
        return usage()
    sub = argv[0]
    rest = argv[1:]
    DEFAULT_TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    if sub == "list":
        templates = sorted(path.name for path in DEFAULT_TEMPLATE_DIR.glob("*.json"))
        return emit(
            {
                "result": "PASS",
                "command": "template-list",
                "count": len(templates),
                "templates": templates,
            },
            as_json,
        )
    if sub == "init":
        if not rest:
            return usage()
        name = rest[0].strip()
        if not name:
            return usage()
        path = DEFAULT_TEMPLATE_DIR / f"{name}.json"
        if path.exists():
            return emit(
                {
                    "result": "PASS",
                    "command": "template-init",
                    "path": str(path),
                    "status": "exists",
                },
                as_json,
            )
        template = {
            "name": name,
            "version": 1,
            "steps": [
                {"id": "prepare", "action": "gather-context"},
                {"id": "execute", "action": "implement"},
                {"id": "verify", "action": "run-validate"},
            ],
        }
        save_json_file(path, template)
        return emit(
            {
                "result": "PASS",
                "command": "template-init",
                "path": str(path),
                "status": "created",
            },
            as_json,
        )
    return usage()


def cmd_doctor(argv: list[str]) -> int:
    as_json = "--json" in argv
    state = load_json_file(DEFAULT_STATE_PATH)
    warnings: list[str] = []
    if not DEFAULT_TEMPLATE_DIR.exists():
        warnings.append("workflow template directory does not exist yet")
    history = history_list(state)
    return emit(
        {
            "result": "PASS",
            "command": "doctor",
            "state_path": str(DEFAULT_STATE_PATH),
            "template_dir": str(DEFAULT_TEMPLATE_DIR),
            "history_count": len(history),
            "warnings": warnings,
            "quick_fixes": [
                "/workflow template init baseline --json",
                "/workflow list --json",
            ],
        },
        as_json,
    )


def main(argv: list[str]) -> int:
    if not argv:
        return usage()
    command = argv[0]
    rest = argv[1:]
    if command in {"help", "-h", "--help"}:
        return usage()
    if command == "validate":
        return cmd_validate(rest)
    if command == "run":
        return cmd_run(rest)
    if command == "status":
        return cmd_status(rest)
    if command == "stop":
        return cmd_stop(rest)
    if command == "list":
        return cmd_list(rest)
    if command == "template":
        return cmd_template(rest)
    if command == "doctor":
        return cmd_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
