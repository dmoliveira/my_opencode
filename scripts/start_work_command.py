#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import UTC, datetime
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
from todo_enforcement import (  # type: ignore
    build_transition_event,
    normalize_todo_state,
    remediation_prompts,
    validate_plan_completion,
    validate_todo_set,
    validate_todo_transition,
)
from recovery_engine import (  # type: ignore
    execute_resume,
    evaluate_resume_eligibility,
    explain_resume_reason,
)


SECTION = "plan_execution"
PLAN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-_]{2,63}$")
STEP_RE = re.compile(r"^- \[(?P<mark>[ xX])\] (?P<text>.+)$")
ORDINAL_RE = re.compile(r"^(?P<ordinal>\d+)\.\s+(?P<detail>.+)$")
REQUIRED_KEYS = ("id", "title", "owner", "created_at", "version")
ALLOWED_STATUSES = {"idle", "completed", "failed", "in_progress", "resume_escalated"}


def usage() -> int:
    print(
        "usage: /start-work <plan.md> [--deviation <note> ...] [--background] [--json] | /start-work status [--json] | /start-work deviations [--json] | /start-work recover --interruption-class <class> [--approve-step <ordinal> ...] [--json] | /start-work doctor [--json]"
    )
    return 2


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_frontmatter(text: str) -> tuple[dict[str, str], int, list[dict[str, Any]]]:
    lines = text.splitlines()
    violations: list[dict[str, Any]] = []
    if not lines or lines[0].strip() != "---":
        violations.append(
            {
                "code": "missing_frontmatter",
                "line": 1,
                "message": "missing YAML frontmatter block",
                "hint": "add --- delimited metadata at the top of the plan file",
            }
        )
        return {}, 0, violations

    metadata: dict[str, str] = {}
    end_index = -1
    for index in range(1, len(lines)):
        line = lines[index]
        if line.strip() == "---":
            end_index = index
            break
        if not line.strip():
            continue
        if ":" not in line:
            violations.append(
                {
                    "code": "invalid_frontmatter_line",
                    "line": index + 1,
                    "message": "frontmatter line must use key: value format",
                    "hint": "use scalar metadata entries like `title: My Plan`",
                }
            )
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            violations.append(
                {
                    "code": "empty_metadata_key",
                    "line": index + 1,
                    "message": "metadata key cannot be empty",
                    "hint": "provide a non-empty metadata key",
                }
            )
            continue
        metadata[key] = value.strip('"')

    if end_index == -1:
        violations.append(
            {
                "code": "unterminated_frontmatter",
                "line": len(lines),
                "message": "missing closing --- for frontmatter",
                "hint": "close the metadata block before checklist content",
            }
        )
        return metadata, 0, violations

    return metadata, end_index + 1, violations


def validate_metadata(metadata: dict[str, str]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for key in REQUIRED_KEYS:
        if not metadata.get(key, "").strip():
            violations.append(
                {
                    "code": "missing_required_metadata",
                    "line": 1,
                    "message": f"missing required metadata key: {key}",
                    "hint": f"add `{key}: ...` to frontmatter",
                }
            )

    plan_id = metadata.get("id", "")
    if plan_id and not PLAN_ID_RE.match(plan_id):
        violations.append(
            {
                "code": "invalid_plan_id",
                "line": 1,
                "message": "metadata.id must match slug pattern [a-z0-9][a-z0-9-_]{2,63}",
                "hint": "use lowercase letters, numbers, dashes, and underscores only",
            }
        )

    created_at = metadata.get("created_at", "")
    if created_at:
        try:
            datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            violations.append(
                {
                    "code": "invalid_created_at",
                    "line": 1,
                    "message": "metadata.created_at must be RFC3339",
                    "hint": "example: 2026-02-13T10:00:00Z",
                }
            )

    version = metadata.get("version", "")
    if version:
        try:
            if int(version) <= 0:
                raise ValueError
        except ValueError:
            violations.append(
                {
                    "code": "invalid_version",
                    "line": 1,
                    "message": "metadata.version must be a positive integer",
                    "hint": "set `version: 1` for first revision",
                }
            )
    return violations


def parse_steps(
    lines: list[str], start_index: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    steps: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []

    for index in range(start_index, len(lines)):
        line = lines[index]
        match = STEP_RE.match(line)
        if not match:
            continue
        text = match.group("text").strip()
        if not text:
            violations.append(
                {
                    "code": "empty_step_text",
                    "line": index + 1,
                    "message": "checklist step text cannot be empty",
                    "hint": "add an ordinal and description after the checkbox",
                }
            )
            continue
        ordinal_match = ORDINAL_RE.match(text)
        if not ordinal_match:
            violations.append(
                {
                    "code": "missing_step_ordinal",
                    "line": index + 1,
                    "message": "step text must start with numeric ordinal like `1. ...`",
                    "hint": "prefix each executable checklist step with an explicit ordinal",
                }
            )
            continue

        steps.append(
            {
                "ordinal": int(ordinal_match.group("ordinal")),
                "text": ordinal_match.group("detail")
                .replace("[non-idempotent]", "")
                .strip(),
                "line": index + 1,
                "checked": match.group("mark").lower() == "x",
                "idempotent": "[non-idempotent]" not in ordinal_match.group("detail"),
            }
        )

    if not steps:
        violations.append(
            {
                "code": "no_executable_steps",
                "line": start_index + 1,
                "message": "plan must include at least one executable checklist step",
                "hint": "add top-level `- [ ] 1. ...` items",
            }
        )
        return [], violations

    ordinals = [step["ordinal"] for step in steps]
    if len(ordinals) != len(set(ordinals)):
        violations.append(
            {
                "code": "duplicate_step_ordinal",
                "line": steps[0]["line"],
                "message": "step ordinals must be unique",
                "hint": "renumber duplicate ordinals to keep sequence deterministic",
            }
        )
    if ordinals != sorted(ordinals):
        violations.append(
            {
                "code": "out_of_order_ordinals",
                "line": steps[0]["line"],
                "message": "step ordinals must appear in increasing order",
                "hint": "reorder checklist items to match ascending ordinal order",
            }
        )
    if all(step["checked"] for step in steps):
        violations.append(
            {
                "code": "plan_already_complete",
                "line": steps[0]["line"],
                "message": "all checklist steps are already complete",
                "hint": "start from a plan with at least one pending step",
            }
        )
    return steps, violations


def parse_plan(plan_path: Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    text = plan_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    metadata, checklist_start, violations = parse_frontmatter(text)
    violations.extend(validate_metadata(metadata))
    steps, step_violations = parse_steps(lines, checklist_start)
    violations.extend(step_violations)
    if violations:
        return None, violations
    return {"metadata": metadata, "steps": steps}, []


def load_state() -> tuple[dict[str, Any], Path]:
    config, _ = load_layered_config()
    return config, resolve_write_path()


def save_state(config: dict[str, Any], write_path: Path, state: dict[str, Any]) -> None:
    config[SECTION] = state
    save_config_file(config, write_path)


def command_start(args: list[str]) -> int:
    json_output = False
    background = False
    deviations: list[str] = []
    filtered: list[str] = []

    index = 0
    while index < len(args):
        token = args[index]
        if token == "--json":
            json_output = True
        elif token == "--background":
            background = True
        elif token == "--deviation":
            if index + 1 >= len(args):
                return usage()
            deviations.append(args[index + 1].strip())
            index += 1
        else:
            filtered.append(token)
        index += 1

    if len(filtered) != 1:
        return usage()

    plan_path = Path(filtered[0]).expanduser().resolve()
    if not plan_path.exists():
        report = {
            "result": "FAIL",
            "code": "plan_not_found",
            "plan": str(plan_path),
            "hint": "pass a readable markdown plan path",
        }
        print(json.dumps(report, indent=2) if json_output else report["hint"])
        return 1

    try:
        parsed, violations = parse_plan(plan_path)
    except OSError as exc:
        report = {
            "result": "FAIL",
            "code": "plan_read_error",
            "plan": str(plan_path),
            "detail": str(exc),
        }
        print(json.dumps(report, indent=2) if json_output else str(exc))
        return 1

    if violations:
        report = {
            "result": "FAIL",
            "code": "validation_failed",
            "plan": str(plan_path),
            "violations": violations,
        }
        print(json.dumps(report, indent=2) if json_output else "validation failed")
        return 1

    assert parsed is not None
    steps = parsed["steps"]
    transitions: list[dict[str, Any]] = []
    compliance_violations: list[dict[str, Any]] = []
    audit_events: list[dict[str, Any]] = []
    deviation_records: list[dict[str, Any]] = []
    actor = str(parsed["metadata"].get("owner") or "unknown")

    for step in steps:
        state = "done" if step["checked"] else "pending"
        step["state"] = state
        if step["checked"]:
            deviation_records.append(
                {
                    "type": "precompleted_step",
                    "step_ordinal": step["ordinal"],
                    "reason": "step marked complete in source plan before execution",
                    "timestamp": now_iso(),
                }
            )

    for note in deviations:
        if note:
            deviation_records.append(
                {
                    "type": "manual_note",
                    "step_ordinal": None,
                    "reason": note,
                    "timestamp": now_iso(),
                }
            )

    for step in steps:
        if step["state"] != "pending":
            continue
        todo_id = f"todo-{step['ordinal']}"
        to_in_progress = validate_todo_transition(
            todo_id=todo_id,
            from_state=str(step["state"]),
            to_state="in_progress",
        )
        if to_in_progress:
            compliance_violations.append(to_in_progress)
            continue
        step["state"] = "in_progress"
        transition_ts = now_iso()
        transitions.append(
            {"step_ordinal": step["ordinal"], "to": "in_progress", "at": transition_ts}
        )
        audit_events.append(
            build_transition_event(
                todo_id=todo_id,
                from_state="pending",
                to_state="in_progress",
                at=transition_ts,
                actor=actor,
            )
        )
        to_done = validate_todo_transition(
            todo_id=todo_id,
            from_state="in_progress",
            to_state="done",
        )
        if to_done:
            compliance_violations.append(to_done)
            continue
        step["state"] = "done"
        completion_ts = now_iso()
        transitions.append(
            {"step_ordinal": step["ordinal"], "to": "done", "at": completion_ts}
        )
        audit_events.append(
            build_transition_event(
                todo_id=todo_id,
                from_state="in_progress",
                to_state="done",
                at=completion_ts,
                actor=actor,
            )
        )

    compliance_violations.extend(validate_todo_set(steps))
    compliance_violations.extend(validate_plan_completion(steps))
    done_count = sum(
        1 for step in steps if normalize_todo_state(step.get("state")) == "done"
    )
    status = "completed" if not compliance_violations else "failed"
    run_state = {
        "plan": {
            "path": str(plan_path),
            "metadata": parsed["metadata"],
        },
        "status": status,
        "steps": [
            {
                "ordinal": step["ordinal"],
                "text": step["text"],
                "line": step["line"],
                "state": normalize_todo_state(step["state"]),
                "idempotent": bool(step.get("idempotent", True)),
            }
            for step in steps
        ],
        "transitions": transitions,
        "deviations": deviation_records,
        "todo_compliance": {
            "result": "PASS" if not compliance_violations else "FAIL",
            "violations": compliance_violations,
            "remediation": remediation_prompts(compliance_violations),
            "audit_events": audit_events,
        },
        "started_at": now_iso(),
        "finished_at": now_iso(),
        "resume": {
            "enabled": True,
            "attempt_count": 0,
            "max_attempts": 3,
            "trail": [],
        },
    }

    config, write_path = load_state()
    existing_runtime = config.get(SECTION)
    if isinstance(existing_runtime, dict):
        existing_resume = existing_runtime.get("resume")
        if (
            isinstance(existing_resume, dict)
            and existing_resume.get("enabled") is False
        ):
            run_state["resume"]["enabled"] = False

    if background:
        bg_script = SCRIPT_DIR / "background_task_manager.py"
        if not bg_script.exists():
            report = {
                "result": "FAIL",
                "code": "background_manager_unavailable",
                "hint": "install scripts/background_task_manager.py before using --background",
            }
            print(json.dumps(report, indent=2) if json_output else report["hint"])
            return 1

        enqueue_cmd = [
            sys.executable,
            str(bg_script),
            "enqueue",
            "--cwd",
            str(Path.cwd()),
            "--label",
            "plan-execution",
            "--label",
            f"plan:{parsed['metadata'].get('id', 'unknown')}",
            "--",
            sys.executable,
            str(Path(__file__).resolve()),
            str(plan_path),
            "--json",
        ]
        for note in deviations:
            enqueue_cmd.extend(["--deviation", note])

        enqueue_result = subprocess.run(
            enqueue_cmd,
            capture_output=True,
            text=True,
            check=False,
            cwd=Path.cwd(),
        )
        if enqueue_result.returncode != 0:
            report = {
                "result": "FAIL",
                "code": "background_enqueue_failed",
                "stderr": enqueue_result.stderr.strip(),
                "stdout": enqueue_result.stdout.strip(),
            }
            print(json.dumps(report, indent=2) if json_output else "failed to enqueue")
            return 1

        job_id = ""
        for line in enqueue_result.stdout.splitlines():
            if line.startswith("id: "):
                job_id = line.replace("id: ", "", 1).strip()
                break
        if not job_id:
            report = {
                "result": "FAIL",
                "code": "background_enqueue_parse_failed",
                "stdout": enqueue_result.stdout.strip(),
            }
            print(
                json.dumps(report, indent=2)
                if json_output
                else "failed to parse job id"
            )
            return 1

        report = {
            "result": "PASS",
            "status": "queued",
            "background": True,
            "job_id": job_id,
            "plan": {"path": str(plan_path), "metadata": parsed["metadata"]},
            "hint": "run /bg run --id <job-id> to execute queued plan",
        }
        if json_output:
            print(json.dumps(report, indent=2))
        else:
            print(f"plan: {plan_path}")
            print("status: queued")
            print(f"job_id: {job_id}")
            print("next: /bg run --id <job-id>")
        return 0

    save_state(config, write_path, run_state)

    report = {
        "result": "PASS" if status == "completed" else "FAIL",
        "status": run_state["status"],
        "plan": run_state["plan"],
        "step_counts": {
            "total": len(steps),
            "done": done_count,
            "pending": len(steps) - done_count,
        },
        "deviation_count": len(deviation_records),
        "todo_compliance": run_state["todo_compliance"],
        "config": str(write_path),
    }

    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"plan: {run_state['plan']['path']}")
        print(f"status: {run_state['status']}")
        print(f"steps: {done_count}/{len(steps)} done")
        print(f"deviations: {len(deviation_records)}")
        if compliance_violations:
            print("todo_compliance: FAIL")
            for prompt in remediation_prompts(compliance_violations):
                print(f"- {prompt}")
        print(f"config: {write_path}")
    return 0 if status == "completed" else 1


def read_runtime_state() -> tuple[dict[str, Any], Path]:
    config, write_path = load_state()
    runtime = config.get(SECTION)
    if not isinstance(runtime, dict):
        runtime = {}
    return runtime, write_path


def command_status(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    json_output = "--json" in args
    runtime, write_path = read_runtime_state()
    raw_steps = runtime.get("steps")
    steps: list[Any] = raw_steps if isinstance(raw_steps, list) else []
    counts = {
        "total": len(steps),
        "done": sum(
            1
            for step in steps
            if isinstance(step, dict)
            and normalize_todo_state(step.get("state")) == "done"
        ),
        "in_progress": sum(
            1
            for step in steps
            if isinstance(step, dict)
            and normalize_todo_state(step.get("state")) == "in_progress"
        ),
        "pending": sum(
            1
            for step in steps
            if isinstance(step, dict)
            and normalize_todo_state(step.get("state")) == "pending"
        ),
        "skipped": sum(
            1
            for step in steps
            if isinstance(step, dict)
            and normalize_todo_state(step.get("state")) == "skipped"
        ),
    }
    report = {
        "result": "PASS",
        "status": runtime.get("status", "idle"),
        "plan": runtime.get("plan", {}),
        "step_counts": counts,
        "todo_compliance": runtime.get("todo_compliance", {}),
        "config": str(write_path),
    }
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"status: {report['status']}")
        print(f"steps: {counts['done']}/{counts['total']} done")
        if isinstance(report.get("todo_compliance"), dict):
            print(
                f"todo_compliance: {report['todo_compliance'].get('result', 'unknown')}"
            )
        print(f"config: {write_path}")
    return 0


def command_deviations(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    json_output = "--json" in args
    runtime, write_path = read_runtime_state()
    raw_deviations = runtime.get("deviations")
    deviations: list[Any] = raw_deviations if isinstance(raw_deviations, list) else []
    report = {
        "result": "PASS",
        "deviations": deviations,
        "count": len(deviations),
        "config": str(write_path),
    }
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"deviations: {len(deviations)}")
        for entry in deviations:
            if isinstance(entry, dict):
                print(f"- {entry.get('type', 'note')}: {entry.get('reason', '')}")
    return 0


def command_doctor(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    json_output = "--json" in args
    runtime, write_path = read_runtime_state()

    warnings: list[str] = []
    problems: list[str] = []
    status = str(runtime.get("status") or "idle")
    if status not in ALLOWED_STATUSES:
        problems.append(f"unknown plan execution status: {status}")

    raw_steps = runtime.get("steps")
    steps: list[Any] = raw_steps if isinstance(raw_steps, list) else []
    in_progress_count = sum(
        1
        for step in steps
        if isinstance(step, dict)
        and normalize_todo_state(step.get("state")) == "in_progress"
    )
    if in_progress_count > 1:
        problems.append("multiple steps marked in_progress; expected at most one")

    if not runtime:
        warnings.append("no plan execution run recorded yet")

    normalized_steps = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        normalized = dict(step)
        normalized["state"] = normalize_todo_state(step.get("state"))
        normalized_steps.append(normalized)

    for violation in validate_todo_set(normalized_steps):
        message = str(
            violation.get("message") or violation.get("code") or "todo violation"
        )
        if message not in problems:
            problems.append(message)

    if status == "completed":
        for violation in validate_plan_completion(normalized_steps):
            message = str(
                violation.get("message") or violation.get("code") or "todo violation"
            )
            if message not in problems:
                problems.append(message)

    compliance = runtime.get("todo_compliance")
    if isinstance(compliance, dict) and compliance.get("result") == "FAIL":
        for prompt in compliance.get("remediation", []):
            if isinstance(prompt, str) and prompt not in warnings:
                warnings.append(prompt)

    resume_meta = runtime.get("resume")
    if isinstance(resume_meta, dict):
        interruption_class = str(
            resume_meta.get("last_interruption_class") or "tool_failure"
        )
        eligibility = evaluate_resume_eligibility(runtime, interruption_class)
        if not eligibility.get("eligible"):
            reason = str(eligibility.get("reason_code") or "resume blocked")
            warnings.append(
                "resume eligibility: "
                + explain_resume_reason(
                    reason,
                    cooldown_remaining=int(
                        eligibility.get("cooldown_remaining", 0) or 0
                    ),
                )
            )

    report = {
        "result": "PASS" if not problems else "FAIL",
        "status": status,
        "plan": runtime.get("plan", {}),
        "step_count": len(steps),
        "todo_compliance": runtime.get("todo_compliance", {}),
        "resume": runtime.get("resume", {}),
        "warnings": warnings,
        "problems": problems,
        "quick_fixes": [
            "/start-work path/to/plan.md --json",
            "/start-work status --json",
        ],
        "config": str(write_path),
    }

    if json_output:
        print(json.dumps(report, indent=2))
        return 0 if report["result"] == "PASS" else 1

    print(f"result: {report['result']}")
    print(f"status: {status}")
    print(f"step_count: {len(steps)}")
    if warnings:
        print("warnings:")
        for warning in warnings:
            print(f"- {warning}")
    if problems:
        print("problems:")
        for problem in problems:
            print(f"- {problem}")
    print(f"config: {write_path}")
    return 0 if report["result"] == "PASS" else 1


def command_recover(args: list[str]) -> int:
    json_output = "--json" in args
    interruption_class = ""
    approved_steps: set[int] = set()

    index = 0
    while index < len(args):
        token = args[index]
        if token == "--json":
            index += 1
            continue
        if token == "--interruption-class":
            if index + 1 >= len(args):
                return usage()
            interruption_class = args[index + 1].strip()
            index += 2
            continue
        if token == "--approve-step":
            if index + 1 >= len(args):
                return usage()
            try:
                approved_steps.add(int(args[index + 1]))
            except ValueError:
                return usage()
            index += 2
            continue
        return usage()

    if not interruption_class:
        return usage()

    runtime, write_path = read_runtime_state()
    if not runtime:
        report = {
            "result": "FAIL",
            "code": "resume_missing_checkpoint",
            "hint": "run /start-work <plan.md> before attempting recovery",
            "config": str(write_path),
        }
        print(json.dumps(report, indent=2) if json_output else report["hint"])
        return 1

    actor = "system"
    raw_plan = runtime.get("plan")
    if isinstance(raw_plan, dict):
        raw_metadata = raw_plan.get("metadata")
        if isinstance(raw_metadata, dict):
            actor = str(raw_metadata.get("owner") or actor)

    result = execute_resume(
        runtime,
        interruption_class,
        approved_steps=approved_steps,
        actor=actor,
    )

    config, _ = load_state()
    next_runtime = result.get("runtime")
    if isinstance(next_runtime, dict):
        save_state(config, write_path, next_runtime)

    report = {
        "result": result.get("result", "FAIL"),
        "status": next_runtime.get("status")
        if isinstance(next_runtime, dict)
        else None,
        "reason_code": result.get("reason_code"),
        "reason": explain_resume_reason(
            str(result.get("reason_code") or "unknown"),
            cooldown_remaining=int(result.get("cooldown_remaining", 0) or 0),
        ),
        "cooldown_remaining": int(result.get("cooldown_remaining", 0) or 0),
        "checkpoint": result.get("checkpoint"),
        "resumed_steps": result.get("resumed_steps", []),
        "config": str(write_path),
    }
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"result: {report['result']}")
        print(f"status: {report['status']}")
        print(f"reason: {report['reason']}")
        print(f"resumed_steps: {len(report['resumed_steps'])}")
        print(f"config: {write_path}")
    return 0 if report["result"] == "PASS" else 1


def main(argv: list[str]) -> int:
    if not argv:
        return usage()
    command = argv[0]
    rest = argv[1:]

    if command in ("help", "--help", "-h"):
        return usage()
    if command == "status":
        return command_status(rest)
    if command == "deviations":
        return command_deviations(rest)
    if command == "recover":
        return command_recover(rest)
    if command == "doctor":
        return command_doctor(rest)
    return command_start(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
