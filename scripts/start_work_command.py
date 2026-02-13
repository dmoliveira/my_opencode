#!/usr/bin/env python3

from __future__ import annotations

import json
import re
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


SECTION = "plan_execution"
PLAN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-_]{2,63}$")
STEP_RE = re.compile(r"^- \[(?P<mark>[ xX])\] (?P<text>.+)$")
ORDINAL_RE = re.compile(r"^(?P<ordinal>\d+)\.\s+(?P<detail>.+)$")
REQUIRED_KEYS = ("id", "title", "owner", "created_at", "version")


def usage() -> int:
    print(
        "usage: /start-work <plan.md> [--deviation <note> ...] [--json] | /start-work status [--json] | /start-work deviations [--json]"
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
                "text": ordinal_match.group("detail").strip(),
                "line": index + 1,
                "checked": match.group("mark").lower() == "x",
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
    deviations: list[str] = []
    filtered: list[str] = []

    index = 0
    while index < len(args):
        token = args[index]
        if token == "--json":
            json_output = True
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
    deviation_records: list[dict[str, Any]] = []

    for step in steps:
        state = "completed" if step["checked"] else "pending"
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
        step["state"] = "in_progress"
        transitions.append(
            {"step_ordinal": step["ordinal"], "to": "in_progress", "at": now_iso()}
        )
        step["state"] = "completed"
        transitions.append(
            {"step_ordinal": step["ordinal"], "to": "completed", "at": now_iso()}
        )

    completed = sum(1 for step in steps if step["state"] == "completed")
    status = "completed" if completed == len(steps) else "failed"
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
                "state": step["state"],
            }
            for step in steps
        ],
        "transitions": transitions,
        "deviations": deviation_records,
        "started_at": now_iso(),
        "finished_at": now_iso(),
    }

    config, write_path = load_state()
    save_state(config, write_path, run_state)

    report = {
        "result": "PASS",
        "status": run_state["status"],
        "plan": run_state["plan"],
        "step_counts": {
            "total": len(steps),
            "completed": completed,
            "pending": len(steps) - completed,
        },
        "deviation_count": len(deviation_records),
        "config": str(write_path),
    }

    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"plan: {run_state['plan']['path']}")
        print(f"status: {run_state['status']}")
        print(f"steps: {completed}/{len(steps)} completed")
        print(f"deviations: {len(deviation_records)}")
        print(f"config: {write_path}")
    return 0


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
        "completed": sum(
            1
            for step in steps
            if isinstance(step, dict) and step.get("state") == "completed"
        ),
        "in_progress": sum(
            1
            for step in steps
            if isinstance(step, dict) and step.get("state") == "in_progress"
        ),
        "pending": sum(
            1
            for step in steps
            if isinstance(step, dict) and step.get("state") == "pending"
        ),
    }
    report = {
        "result": "PASS",
        "status": runtime.get("status", "idle"),
        "plan": runtime.get("plan", {}),
        "step_counts": counts,
        "config": str(write_path),
    }
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"status: {report['status']}")
        print(f"steps: {counts['completed']}/{counts['total']} completed")
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
    return command_start(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
