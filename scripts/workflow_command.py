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

from runtime_audit import append_event  # type: ignore
from governance_policy import check_operation  # type: ignore
from model_routing_command import resolve_for_entrypoint  # type: ignore
from task_graph_bridge import (  # type: ignore
    sync_workflow_run_to_task_graph,
    task_graph_status_snapshot,
    task_graph_runtime_path,
)


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


def entrypoint_model_routing() -> dict[str, Any]:
    return resolve_for_entrypoint("workflow")


def attach_model_routing(
    target: dict[str, Any], routing: dict[str, Any]
) -> dict[str, Any]:
    target["model_routing"] = routing
    return target


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def usage() -> int:
    print(
        "usage: /workflow run --file <path> [--execute] [--override] [--json] | /workflow validate --file <path> [--json] | "
        "/workflow list [--json] | /workflow status [--json] | /workflow resume --run-id <id> [--execute] [--override] [--json] | "
        "/workflow stop [--reason <text>] [--json] | /workflow template list [--json] | /workflow template init <name> [--json] | /workflow doctor [--json]"
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


def next_run_id(state: dict[str, Any]) -> str:
    max_seq = 0
    candidates: list[dict[str, Any]] = []
    active = active_record(state)
    if active:
        candidates.append(active)
    candidates.extend(history_list(state))
    prefix = "wf-run-"
    for item in candidates:
        raw = str(item.get("run_id") or "")
        if not raw.startswith(prefix):
            continue
        suffix = raw[len(prefix) :]
        if suffix.isdigit():
            max_seq = max(max_seq, int(suffix))
    return f"{prefix}{max_seq + 1:06d}"


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
    attach_model_routing(payload, entrypoint_model_routing())
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


def merge_step_results(
    ordered_steps: list[dict[str, Any]],
    previous_results: list[dict[str, Any]],
    current_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    previous_by_id = {
        str(item.get("id") or "").strip(): item
        for item in previous_results
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    current_by_id = {
        str(item.get("id") or "").strip(): item
        for item in current_results
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    merged: list[dict[str, Any]] = []
    for step in ordered_steps:
        step_id = str(step.get("id") or "").strip()
        if not step_id:
            continue
        if step_id in current_by_id:
            merged.append(current_by_id[step_id])
        elif step_id in previous_by_id:
            merged.append(previous_by_id[step_id])
    return merged


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
            when = step.get("when")
            if when is not None and str(when) not in {
                "always",
                "on_success",
                "on_failure",
            }:
                issues.append(f"step {idx} has invalid when value")
            retry = step.get("retry")
            if retry is not None:
                try:
                    if int(retry) < 0:
                        issues.append(f"step {idx} retry must be >= 0")
                except (TypeError, ValueError):
                    issues.append(f"step {idx} retry must be integer")
    return (not issues, issues)


def resolve_step_order(
    steps: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    by_id: dict[str, dict[str, Any]] = {}
    deps: dict[str, set[str]] = {}
    reverse_edges: dict[str, set[str]] = {}
    issues: list[str] = []
    order_index: dict[str, int] = {}

    for idx, step in enumerate(steps):
        step_id = str(step.get("id") or "").strip()
        if not step_id:
            continue
        by_id[step_id] = step
        deps[step_id] = set()
        reverse_edges[step_id] = set()
        order_index[step_id] = idx

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

    queue = sorted(
        (step_id for step_id, d in deps.items() if not d),
        key=lambda sid: order_index.get(sid, 0),
    )
    ordered_ids: list[str] = []
    while queue:
        current = queue.pop(0)
        ordered_ids.append(current)
        for dependent in sorted(
            reverse_edges[current], key=lambda sid: order_index.get(sid, 0)
        ):
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
    steps: list[dict[str, Any]],
    execute_commands: bool,
    on_step_settled: Any = None,
    interrupt_after_steps: int = 0,
) -> tuple[str, list[dict[str, Any]], str | None]:
    results: list[dict[str, Any]] = []
    failed_step_id: str | None = None
    failure_seen = False
    results_by_id: dict[str, dict[str, Any]] = {}

    for step in steps:
        step_id = str(step.get("id") or "unknown-step")
        action = str(step.get("action") or "")
        when = str(step.get("when") or "always")
        started_at = now_iso()

        if when == "on_success" and failure_seen:
            results.append(
                {
                    "id": step_id,
                    "action": action,
                    "status": "skipped",
                    "reason_code": "skipped_on_failure",
                    "detail": "skipped because a previous step failed",
                    "depends_on": step.get("depends_on")
                    if isinstance(step.get("depends_on"), list)
                    else [],
                    "when": when,
                    "retry": int(step.get("retry", 0) or 0),
                    "attempts": 0,
                    "started_at": started_at,
                    "finished_at": now_iso(),
                }
            )
            results_by_id[step_id] = results[-1]
            if callable(on_step_settled):
                on_step_settled(results, step_id)
            if (
                interrupt_after_steps > 0
                and len(results) >= interrupt_after_steps
                and step != steps[-1]
            ):
                next_step_id = str(steps[steps.index(step) + 1].get("id") or "")
                return "interrupted", results, next_step_id or None
            continue
        if when == "on_failure" and not failure_seen:
            results.append(
                {
                    "id": step_id,
                    "action": action,
                    "status": "skipped",
                    "reason_code": "skipped_on_success",
                    "detail": "skipped because no previous step failed",
                    "depends_on": step.get("depends_on")
                    if isinstance(step.get("depends_on"), list)
                    else [],
                    "when": when,
                    "retry": int(step.get("retry", 0) or 0),
                    "attempts": 0,
                    "started_at": started_at,
                    "finished_at": now_iso(),
                }
            )
            results_by_id[step_id] = results[-1]
            if callable(on_step_settled):
                on_step_settled(results, step_id)
            if (
                interrupt_after_steps > 0
                and len(results) >= interrupt_after_steps
                and step != steps[-1]
            ):
                next_step_id = str(steps[steps.index(step) + 1].get("id") or "")
                return "interrupted", results, next_step_id or None
            continue

        raw_depends_on = step.get("depends_on")
        depends_on: list[Any] = (
            raw_depends_on if isinstance(raw_depends_on, list) else []
        )
        unmet_dependency = next(
            (
                dep_id
                for dep_id in [
                    str(dep).strip() for dep in depends_on if str(dep).strip()
                ]
                if str(results_by_id.get(dep_id, {}).get("status") or "") != "passed"
            ),
            None,
        )
        if unmet_dependency:
            results.append(
                {
                    "id": step_id,
                    "action": action,
                    "status": "skipped",
                    "reason_code": "skipped_dependency_not_passed",
                    "detail": f"skipped because dependency did not pass: {unmet_dependency}",
                    "depends_on": depends_on,
                    "when": when,
                    "retry": int(step.get("retry", 0) or 0),
                    "attempts": 0,
                    "started_at": started_at,
                    "finished_at": now_iso(),
                }
            )
            results_by_id[step_id] = results[-1]
            if callable(on_step_settled):
                on_step_settled(results, step_id)
            if (
                interrupt_after_steps > 0
                and len(results) >= interrupt_after_steps
                and step != steps[-1]
            ):
                next_step_id = str(steps[steps.index(step) + 1].get("id") or "")
                return "interrupted", results, next_step_id or None
            continue

        retry_count = 0
        try:
            retry_count = max(0, int(step.get("retry", 0) or 0))
        except (TypeError, ValueError):
            retry_count = 0

        status = "passed"
        reason_code = None
        detail = "executed"
        attempts = 0
        for _ in range(retry_count + 1):
            attempts += 1
            status = "passed"
            reason_code = None
            detail = "executed"

            if not action:
                status = "failed"
                reason_code = "missing_step_action"
                detail = "step action is required"
            elif execute_commands and step.get("command") is not None:
                status, reason_code, detail, _ = run_command_step(step)
            elif (
                action in {"fail", "error"} or str(step.get("simulate") or "") == "fail"
            ):
                status = "failed"
                reason_code = "step_failed"
                detail = "step requested failure"
            elif str(step.get("simulate") or "") == "fail-once" and attempts == 1:
                status = "failed"
                reason_code = "step_failed_once"
                detail = "step requested one-time failure"
            elif step.get("command") is not None:
                detail = "dry-run command step (use --execute)"

            if status != "failed":
                break

        if status == "failed":
            failure_seen = True
            if failed_step_id is None:
                failed_step_id = step_id

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
                "when": when,
                "retry": retry_count,
                "attempts": attempts,
                "started_at": started_at,
                "finished_at": now_iso(),
            }
        )
        results_by_id[step_id] = results[-1]
        if callable(on_step_settled):
            on_step_settled(results, step_id)
        if (
            interrupt_after_steps > 0
            and len(results) >= interrupt_after_steps
            and step != steps[-1]
        ):
            next_step_id = str(steps[steps.index(step) + 1].get("id") or "")
            return "interrupted", results, next_step_id or None

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
    routing = entrypoint_model_routing()
    as_json = "--json" in argv
    execute_commands = "--execute" in argv
    override_flag = "--override" in argv
    argv = [a for a in argv if a not in {"--json", "--execute", "--override"}]
    try:
        file_arg = parse_flag_value(argv, "--file")
    except ValueError:
        return usage()
    if not file_arg:
        return usage()

    if execute_commands:
        guard = check_operation("workflow.execute", override_flag=override_flag)
        if not bool(guard.get("allowed")):
            return emit(
                {
                    "result": "FAIL",
                    "command": "run",
                    "error": "operation blocked by governance policy",
                    "reason_code": guard.get("reason_code"),
                    "governance": guard,
                },
                as_json,
            )

    workflow_path = Path(file_arg).expanduser()
    workflow, issues = load_workflow_file(workflow_path)
    if issues or not isinstance(workflow, dict):
        return emit(
            {
                "result": "FAIL",
                "command": "run",
                "issues": issues,
                "error": issues[0],
            },
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

    run_id = next_run_id(state)
    started_at = now_iso()
    interrupt_after_steps = 0
    try:
        interrupt_after_steps = max(
            0,
            int(os.environ.get("MY_OPENCODE_WORKFLOW_INTERRUPT_AFTER_STEP", "0") or 0),
        )
    except ValueError:
        interrupt_after_steps = 0
    active_run = {
        "run_id": run_id,
        "name": workflow.get("name"),
        "path": str(workflow_path),
        "status": "running" if execute_commands else "dry-run",
        "execution_mode": "execute" if execute_commands else "dry-run",
        "step_count": len(ordered_steps),
        "completed_steps": 0,
        "failed_step_id": None,
        "ordered_step_ids": [str(step.get("id") or "") for step in ordered_steps],
        "steps": [],
        "started_at": started_at,
        "updated_at": started_at,
    }
    state["active"] = active_run
    save_json_file(DEFAULT_STATE_PATH, state)

    def persist_partial(step_results: list[dict[str, Any]], next_step_id: str) -> None:
        partial_state = load_json_file(DEFAULT_STATE_PATH)
        partial_active = active_record(partial_state)
        partial_active.update(
            {
                "run_id": run_id,
                "name": workflow.get("name"),
                "path": str(workflow_path),
                "status": "running",
                "execution_mode": "execute" if execute_commands else "dry-run",
                "step_count": len(ordered_steps),
                "completed_steps": sum(
                    1 for item in step_results if item.get("status") == "passed"
                ),
                "failed_step_id": next_step_id or None,
                "ordered_step_ids": [
                    str(step.get("id") or "") for step in ordered_steps
                ],
                "steps": step_results,
                "started_at": started_at,
                "updated_at": now_iso(),
            }
        )
        partial_state["active"] = partial_active
        save_json_file(DEFAULT_STATE_PATH, partial_state)
        if execute_commands:
            sync_workflow_run_to_task_graph(
                workflow_path=workflow_path,
                workflow=workflow,
                ordered_steps=ordered_steps,
                step_results=step_results,
                run_record=partial_active,
            )

    status, step_results, failed_step_id = execute_steps(
        ordered_steps,
        execute_commands,
        on_step_settled=persist_partial if execute_commands else None,
        interrupt_after_steps=interrupt_after_steps if execute_commands else 0,
    )
    run_record = {
        "run_id": run_id,
        "name": workflow.get("name"),
        "path": str(workflow_path),
        "status": status,
        "execution_mode": "execute" if execute_commands else "dry-run",
        "step_count": len(ordered_steps),
        "completed_steps": sum(
            1 for step in step_results if step.get("status") == "passed"
        ),
        "failed_step_id": failed_step_id,
        "ordered_step_ids": [str(step.get("id") or "") for step in ordered_steps],
        "steps": step_results,
        "started_at": started_at,
        "finished_at": now_iso(),
    }
    if status == "interrupted":
        state = load_json_file(DEFAULT_STATE_PATH)
        state["active"] = run_record
        save_json_file(DEFAULT_STATE_PATH, state)
    else:
        history = history_list(state)
        history.insert(0, run_record)
        state["history"] = history[:50]
        state["active"] = {}
        save_json_file(DEFAULT_STATE_PATH, state)
    task_graph_path = task_graph_runtime_path()
    if execute_commands:
        task_graph_path = sync_workflow_run_to_task_graph(
            workflow_path=workflow_path,
            workflow=workflow,
            ordered_steps=ordered_steps,
            step_results=step_results,
            run_record=run_record,
        )
    append_event("workflow", "run", "PASS", {"run_id": run_id, "status": status})
    return emit(
        attach_model_routing(
            (
                {
                    "result": "PASS" if status != "interrupted" else "FAIL",
                    "command": "run",
                    **run_record,
                    **(
                        {
                            **task_graph_status_snapshot(),
                            "task_graph_path": str(task_graph_path),
                        }
                        if execute_commands
                        else {}
                    ),
                }
            ),
            routing,
        ),
        as_json,
    )


def cmd_resume(argv: list[str]) -> int:
    routing = entrypoint_model_routing()
    as_json = "--json" in argv
    execute_commands = "--execute" in argv
    override_flag = "--override" in argv
    argv = [a for a in argv if a not in {"--json", "--execute", "--override"}]
    try:
        run_id = parse_flag_value(argv, "--run-id")
    except ValueError:
        return usage()
    if not run_id:
        return usage()

    if execute_commands:
        guard = check_operation("workflow.resume_execute", override_flag=override_flag)
        if not bool(guard.get("allowed")):
            return emit(
                {
                    "result": "FAIL",
                    "command": "resume",
                    "error": "operation blocked by governance policy",
                    "reason_code": guard.get("reason_code"),
                    "governance": guard,
                },
                as_json,
            )

    state = load_json_file(DEFAULT_STATE_PATH)
    active = active_record(state)
    if active and str(active.get("status") or "") == "running":
        return emit(
            {
                "result": "FAIL",
                "command": "resume",
                "error": "workflow run already active",
                "reason_code": "workflow_already_running",
                "active_run_id": active.get("run_id"),
            },
            as_json,
        )
    history = history_list(state)
    source_run = None
    if active and str(active.get("run_id") or "") == run_id:
        source_run = active
    if not isinstance(source_run, dict):
        source_run = next(
            (row for row in history if str(row.get("run_id") or "") == run_id), None
        )
    if not isinstance(source_run, dict):
        return emit(
            {
                "result": "FAIL",
                "command": "resume",
                "error": f"run not found: {run_id}",
                "reason_code": "workflow_run_not_found",
            },
            as_json,
        )
    if str(source_run.get("status") or "") not in {"failed", "interrupted"}:
        return emit(
            {
                "result": "FAIL",
                "command": "resume",
                "error": "run is not resumable",
                "reason_code": "workflow_resume_not_failed",
            },
            as_json,
        )

    workflow_path = Path(str(source_run.get("path") or "")).expanduser()
    workflow, issues = load_workflow_file(workflow_path)
    if issues or not isinstance(workflow, dict):
        return emit(
            {
                "result": "FAIL",
                "command": "resume",
                "error": issues[0] if issues else "workflow load failed",
                "reason_code": "workflow_resume_load_failed",
            },
            as_json,
        )

    raw_steps = workflow.get("steps")
    steps = raw_steps if isinstance(raw_steps, list) else []
    normalized_steps = [step for step in steps if isinstance(step, dict)]
    ordered_steps, order_issues = resolve_step_order(normalized_steps)
    if order_issues:
        return emit(
            {
                "result": "FAIL",
                "command": "resume",
                "error": order_issues[0],
                "issues": order_issues,
                "reason_code": "workflow_dependency_error",
            },
            as_json,
        )

    failed_step_id = str(source_run.get("failed_step_id") or "")
    start_index = 0
    found_failed_step = False
    if failed_step_id:
        for idx, step in enumerate(ordered_steps):
            if str(step.get("id") or "") == failed_step_id:
                start_index = idx
                found_failed_step = True
                break
        if not found_failed_step:
            return emit(
                {
                    "result": "FAIL",
                    "command": "resume",
                    "error": f"failed step no longer exists in workflow: {failed_step_id}",
                    "reason_code": "workflow_resume_failed_step_missing",
                    "failed_step_id": failed_step_id,
                },
                as_json,
            )
    resumed_steps = ordered_steps[start_index:]

    started_at = now_iso()
    active_resume = {
        "run_id": next_run_id(state),
        "name": workflow.get("name"),
        "path": str(workflow_path),
        "status": "running" if execute_commands else "dry-run",
        "execution_mode": "execute" if execute_commands else "dry-run",
        "resumed_from": run_id,
        "step_count": len(resumed_steps),
        "completed_steps": 0,
        "failed_step_id": None,
        "ordered_step_ids": [str(step.get("id") or "") for step in resumed_steps],
        "steps": [],
        "started_at": started_at,
        "updated_at": started_at,
    }
    state["active"] = active_resume
    save_json_file(DEFAULT_STATE_PATH, state)

    def persist_resumed_partial(
        step_results: list[dict[str, Any]], next_step_id: str
    ) -> None:
        partial_state = load_json_file(DEFAULT_STATE_PATH)
        partial_active = active_record(partial_state)
        partial_active.update(
            {
                **active_resume,
                "completed_steps": sum(
                    1 for item in step_results if item.get("status") == "passed"
                ),
                "failed_step_id": next_step_id or None,
                "steps": step_results,
                "updated_at": now_iso(),
            }
        )
        partial_state["active"] = partial_active
        save_json_file(DEFAULT_STATE_PATH, partial_state)
        if execute_commands:
            previous_step_results = [
                item for item in source_run.get("steps", []) if isinstance(item, dict)
            ]
            merged_step_results = merge_step_results(
                ordered_steps, previous_step_results, step_results
            )
            sync_workflow_run_to_task_graph(
                workflow_path=workflow_path,
                workflow=workflow,
                ordered_steps=ordered_steps,
                step_results=merged_step_results,
                run_record=partial_active,
            )

    interrupt_after_steps = 0
    try:
        interrupt_after_steps = max(
            0,
            int(os.environ.get("MY_OPENCODE_WORKFLOW_INTERRUPT_AFTER_STEP", "0") or 0),
        )
    except ValueError:
        interrupt_after_steps = 0
    status, step_results, new_failed = execute_steps(
        resumed_steps,
        execute_commands,
        on_step_settled=persist_resumed_partial if execute_commands else None,
        interrupt_after_steps=interrupt_after_steps if execute_commands else 0,
    )
    new_run_id = active_resume["run_id"]
    run_record = {
        "run_id": new_run_id,
        "name": workflow.get("name"),
        "path": str(workflow_path),
        "status": status,
        "execution_mode": "execute" if execute_commands else "dry-run",
        "resumed_from": run_id,
        "step_count": len(resumed_steps),
        "completed_steps": sum(
            1 for step in step_results if step.get("status") == "passed"
        ),
        "failed_step_id": new_failed,
        "ordered_step_ids": [str(step.get("id") or "") for step in resumed_steps],
        "steps": step_results,
        "started_at": started_at,
        "finished_at": now_iso(),
    }
    if status == "interrupted":
        state = load_json_file(DEFAULT_STATE_PATH)
        state["active"] = run_record
        save_json_file(DEFAULT_STATE_PATH, state)
    else:
        history.insert(0, run_record)
        state["history"] = history[:50]
        state["active"] = {}
        save_json_file(DEFAULT_STATE_PATH, state)
    task_graph_path = task_graph_runtime_path()
    if execute_commands:
        previous_step_results = [
            item for item in source_run.get("steps", []) if isinstance(item, dict)
        ]
        merged_step_results = merge_step_results(
            ordered_steps, previous_step_results, step_results
        )
        task_graph_path = sync_workflow_run_to_task_graph(
            workflow_path=workflow_path,
            workflow=workflow,
            ordered_steps=ordered_steps,
            step_results=merged_step_results,
            run_record=run_record,
        )
    append_event(
        "workflow",
        "resume",
        "PASS",
        {"run_id": new_run_id, "resumed_from": run_id, "status": status},
    )
    return emit(
        attach_model_routing(
            (
                {
                    "result": "PASS" if status != "interrupted" else "FAIL",
                    "command": "resume",
                    **run_record,
                    **(
                        {
                            **task_graph_status_snapshot(),
                            "task_graph_path": str(task_graph_path),
                        }
                        if execute_commands
                        else {}
                    ),
                }
            ),
            routing,
        ),
        as_json,
    )


def cmd_status(argv: list[str]) -> int:
    routing = entrypoint_model_routing()
    as_json = "--json" in argv
    state = load_json_file(DEFAULT_STATE_PATH)
    active = active_record(state)
    if not active:
        history = history_list(state)
        latest = history[0] if history and isinstance(history[0], dict) else {}
        return emit(
            attach_model_routing(
                {
                    "result": "PASS",
                    "command": "status",
                    "status": "idle",
                    "warnings": ["no active workflow run"],
                    "latest": latest,
                    **task_graph_status_snapshot(),
                },
                routing,
            ),
            as_json,
        )
    return emit(
        attach_model_routing(
            {
                "result": "PASS",
                "command": "status",
                **active,
                **task_graph_status_snapshot(),
            },
            routing,
        ),
        as_json,
    )


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
    if history and history[0].get("run_id") == active.get("run_id"):
        history[0] = active
    state["history"] = history
    save_json_file(DEFAULT_STATE_PATH, state)
    append_event(
        "workflow", "stop", "PASS", {"run_id": active.get("run_id"), "reason": reason}
    )
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
    if command == "resume":
        return cmd_resume(rest)
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
