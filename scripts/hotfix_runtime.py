#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config_layering import load_layered_config, resolve_write_path  # type: ignore


RUNTIME_FILE_NAME = "hotfix_mode.json"
ALLOWED_SCOPES = {"patch", "rollback", "config_only"}
ALLOWED_IMPACTS = {"sev1", "sev2", "sev3"}
ALLOWED_OUTCOMES = {"resolved", "mitigated", "rolled_back"}

REQUIRED_CLOSE_EVENTS = {
    "started",
    "checkpoint_created",
    "validation_completed",
    "closed",
}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def runtime_path(write_path: Path) -> Path:
    return write_path.parent / "my_opencode" / "runtime" / RUNTIME_FILE_NAME


def load_runtime(write_path: Path) -> dict[str, Any]:
    path = runtime_path(write_path)
    if not path.exists():
        return {
            "active": False,
            "incident_id": None,
            "scope": None,
            "impact": None,
            "started_at": None,
            "closed_at": None,
            "branch": None,
            "timeline": [],
            "rollback_checkpoint": None,
            "validation": {},
            "profile": {
                "budget": {
                    "wall_clock_seconds": 900,
                    "tool_call_count": 100,
                    "token_estimate": 100000,
                },
                "permissions": {
                    "allow": ["read", "edit", "bash"],
                    "deny": ["external_network", "destructive_git"],
                },
                "mandatory_checks": ["validate"],
            },
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "active": False,
            "timeline": [],
            "validation": {},
            "profile": {
                "budget": {
                    "wall_clock_seconds": 900,
                    "tool_call_count": 100,
                    "token_estimate": 100000,
                },
                "permissions": {
                    "allow": ["read", "edit", "bash"],
                    "deny": ["external_network", "destructive_git"],
                },
                "mandatory_checks": ["validate"],
            },
        }
    return (
        payload
        if isinstance(payload, dict)
        else {"active": False, "timeline": [], "validation": {}}
    )


def save_runtime(write_path: Path, state: dict[str, Any]) -> Path:
    path = runtime_path(write_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return path


def run_git(repo_root: Path, args: list[str]) -> tuple[int, str]:
    proc = __import__("subprocess").run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True, check=False
    )
    return proc.returncode, proc.stdout.strip()


def current_branch(repo_root: Path) -> str | None:
    rc, out = run_git(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"])
    return out if rc == 0 and out else None


def clean_worktree(repo_root: Path) -> bool:
    rc, out = run_git(repo_root, ["status", "--porcelain"])
    if rc != 0:
        return False
    lines = [line for line in out.splitlines() if not line.strip().endswith(".beads/")]
    return len(lines) == 0


def append_event(
    state: dict[str, Any], *, event: str, actor: str, details: dict[str, Any]
) -> None:
    timeline_any = state.get("timeline")
    timeline = timeline_any if isinstance(timeline_any, list) else []
    timeline.append(
        {
            "event": event,
            "timestamp": now_iso(),
            "actor": actor,
            "details": details,
        }
    )
    state["timeline"] = timeline


def usage() -> int:
    print(
        "usage: /hotfix-runtime status [--json] | "
        "/hotfix-runtime start --incident-id <id> --scope <patch|rollback|config_only> --impact <sev1|sev2|sev3> [--json] | "
        "/hotfix-runtime checkpoint [--label <name>] [--json] | "
        "/hotfix-runtime mark-patch --summary <text> [--json] | "
        "/hotfix-runtime validate --target <name> --result <pass|fail> [--json] | "
        "/hotfix-runtime close --outcome <resolved|mitigated|rolled_back> --followup-issue <id> --deferred-validation-owner <owner> --deferred-validation-due <date> [--json] | "
        "/hotfix-runtime doctor [--json]"
    )
    return 2


def emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


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


def command_status(args: list[str], write_path: Path) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    as_json = "--json" in args
    state = load_runtime(write_path)
    payload = {
        "result": "PASS",
        "active": bool(state.get("active")),
        "incident_id": state.get("incident_id"),
        "scope": state.get("scope"),
        "impact": state.get("impact"),
        "rollback_checkpoint": state.get("rollback_checkpoint"),
        "timeline_events": len(state.get("timeline", []))
        if isinstance(state.get("timeline"), list)
        else 0,
        "profile": state.get("profile", {}),
        "runtime": str(runtime_path(write_path)),
    }
    emit(payload, as_json)
    return 0


def command_start(args: list[str], write_path: Path, repo_root: Path) -> int:
    as_json = pop_flag(args, "--json")
    try:
        incident_id = pop_value(args, "--incident-id")
        scope = pop_value(args, "--scope")
        impact = pop_value(args, "--impact")
        actor = pop_value(args, "--actor", "operator") or "operator"
    except ValueError:
        return usage()
    if args:
        return usage()

    reason_codes: list[str] = []
    remediation: list[str] = []

    if not incident_id:
        reason_codes.append("incident_id_required")
        remediation.append("provide --incident-id")
    if not scope:
        reason_codes.append("scope_required")
        remediation.append("provide --scope patch|rollback|config_only")
    elif scope not in ALLOWED_SCOPES:
        return usage()
    if not impact:
        reason_codes.append("impact_required")
        remediation.append("provide --impact sev1|sev2|sev3")
    elif impact not in ALLOWED_IMPACTS:
        return usage()
    if not clean_worktree(repo_root):
        reason_codes.append("dirty_worktree")
        remediation.append("commit or stash local changes before starting hotfix mode")

    if reason_codes:
        payload = {
            "result": "FAIL",
            "reason_codes": sorted(set(reason_codes)),
            "remediation": sorted(set(remediation)),
        }
        emit(payload, as_json)
        return 1

    state = load_runtime(write_path)
    state["active"] = True
    state["incident_id"] = incident_id
    state["scope"] = scope
    state["impact"] = impact
    state["branch"] = current_branch(repo_root)
    state["started_at"] = now_iso()
    state["closed_at"] = None
    state["rollback_checkpoint"] = None
    state["validation"] = {}
    state["timeline"] = []
    append_event(
        state,
        event="started",
        actor=actor,
        details={"incident_id": incident_id, "scope": scope, "impact": impact},
    )
    save_runtime(write_path, state)
    payload = {
        "result": "PASS",
        "active": True,
        "incident_id": incident_id,
        "scope": scope,
        "impact": impact,
        "branch": state.get("branch"),
        "runtime": str(runtime_path(write_path)),
    }
    emit(payload, as_json)
    return 0


def command_checkpoint(args: list[str], write_path: Path, repo_root: Path) -> int:
    as_json = pop_flag(args, "--json")
    try:
        label = pop_value(args, "--label", "rollback") or "rollback"
        actor = pop_value(args, "--actor", "operator") or "operator"
    except ValueError:
        return usage()
    if args:
        return usage()

    state = load_runtime(write_path)
    if not state.get("active"):
        emit({"result": "FAIL", "reason_codes": ["hotfix_not_active"]}, as_json)
        return 1

    _, head = run_git(repo_root, ["rev-parse", "HEAD"])
    checkpoint_id = f"hkcp_{now_iso().replace(':', '').replace('-', '')}"
    checkpoint = {
        "id": checkpoint_id,
        "label": label,
        "head": head,
        "created_at": now_iso(),
    }
    state["rollback_checkpoint"] = checkpoint
    append_event(state, event="checkpoint_created", actor=actor, details=checkpoint)
    save_runtime(write_path, state)
    emit(
        {
            "result": "PASS",
            "rollback_checkpoint": checkpoint,
            "runtime": str(runtime_path(write_path)),
        },
        as_json,
    )
    return 0


def command_mark_patch(args: list[str], write_path: Path) -> int:
    as_json = pop_flag(args, "--json")
    try:
        summary = pop_value(args, "--summary")
        actor = pop_value(args, "--actor", "operator") or "operator"
    except ValueError:
        return usage()
    if not summary or args:
        return usage()
    state = load_runtime(write_path)
    if not state.get("active"):
        emit({"result": "FAIL", "reason_codes": ["hotfix_not_active"]}, as_json)
        return 1
    event = "rollback_applied" if state.get("scope") == "rollback" else "patch_applied"
    append_event(state, event=event, actor=actor, details={"summary": summary})
    save_runtime(write_path, state)
    emit({"result": "PASS", "event": event}, as_json)
    return 0


def command_validate(args: list[str], write_path: Path) -> int:
    as_json = pop_flag(args, "--json")
    try:
        target = pop_value(args, "--target")
        result_value = pop_value(args, "--result")
        actor = pop_value(args, "--actor", "operator") or "operator"
    except ValueError:
        return usage()
    if not target or result_value not in {"pass", "fail"} or args:
        return usage()
    state = load_runtime(write_path)
    if not state.get("active"):
        emit({"result": "FAIL", "reason_codes": ["hotfix_not_active"]}, as_json)
        return 1
    validation_any = state.get("validation")
    validation = validation_any if isinstance(validation_any, dict) else {}
    validation[target] = {"result": result_value, "at": now_iso()}
    state["validation"] = validation
    append_event(
        state,
        event="validation_completed",
        actor=actor,
        details={"target": target, "result": result_value},
    )
    save_runtime(write_path, state)
    emit(
        {"result": "PASS", "target": target, "validation_result": result_value}, as_json
    )
    return 0


def command_close(args: list[str], write_path: Path) -> int:
    as_json = pop_flag(args, "--json")
    try:
        outcome = pop_value(args, "--outcome")
        followup_issue = pop_value(args, "--followup-issue")
        deferred_owner = pop_value(args, "--deferred-validation-owner")
        deferred_due = pop_value(args, "--deferred-validation-due")
        actor = pop_value(args, "--actor", "operator") or "operator"
    except ValueError:
        return usage()
    if outcome not in ALLOWED_OUTCOMES or args:
        return usage()

    state = load_runtime(write_path)
    if not state.get("active"):
        emit({"result": "FAIL", "reason_codes": ["hotfix_not_active"]}, as_json)
        return 1

    reason_codes: list[str] = []
    remediation: list[str] = []

    if not state.get("rollback_checkpoint"):
        reason_codes.append("rollback_checkpoint_missing")
        remediation.append("create rollback checkpoint before closing hotfix")

    timeline = (
        state.get("timeline", []) if isinstance(state.get("timeline"), list) else []
    )
    seen_events = {entry.get("event") for entry in timeline if isinstance(entry, dict)}
    required = set(REQUIRED_CLOSE_EVENTS)
    required.discard("closed")
    if not required.issubset(seen_events):
        reason_codes.append("timeline_event_missing")
        remediation.append("ensure started/checkpoint/validation events are present")

    validation = (
        state.get("validation", {}) if isinstance(state.get("validation"), dict) else {}
    )
    validate_report = validation.get("validate")
    if not isinstance(validate_report, dict) or validate_report.get("result") != "pass":
        reason_codes.append("validate_failed")
        remediation.append(
            "record successful validate check with /hotfix-runtime validate"
        )

    if not followup_issue:
        reason_codes.append("followup_issue_required")
        remediation.append("provide --followup-issue for post-incident hardening")
    if not deferred_owner or not deferred_due:
        reason_codes.append("deferred_validation_plan_required")
        remediation.append("provide deferred validation owner and due date")

    if reason_codes:
        emit(
            {
                "result": "FAIL",
                "reason_codes": sorted(set(reason_codes)),
                "remediation": sorted(set(remediation)),
            },
            as_json,
        )
        return 1

    append_event(
        state,
        event="closed",
        actor=actor,
        details={
            "outcome": outcome,
            "followup_issue": followup_issue,
            "deferred_validation": {"owner": deferred_owner, "due": deferred_due},
        },
    )
    state["active"] = False
    state["closed_at"] = now_iso()
    save_runtime(write_path, state)
    emit(
        {
            "result": "PASS",
            "outcome": outcome,
            "followup_issue": followup_issue,
            "runtime": str(runtime_path(write_path)),
        },
        as_json,
    )
    return 0


def command_doctor(args: list[str], write_path: Path) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    as_json = "--json" in args
    policy_exists = (
        SCRIPT_DIR.parent / "instructions" / "hotfix_mode_policy_contract.md"
    ).exists()
    report = {
        "result": "PASS" if policy_exists else "WARN",
        "runtime_exists": Path(__file__).exists(),
        "policy_exists": policy_exists,
        "runtime_path": str(runtime_path(write_path)),
        "warnings": []
        if policy_exists
        else ["missing instructions/hotfix_mode_policy_contract.md"],
        "problems": [],
        "quick_fixes": [
            "/hotfix-runtime start --incident-id INC-1 --scope patch --impact sev2 --json",
            "/hotfix-runtime status --json",
        ],
    }
    emit(report, as_json)
    return 0


def main(argv: list[str]) -> int:
    config, _ = load_layered_config()
    del config
    write_path = resolve_write_path()
    repo_root = Path.cwd()

    if not argv:
        return command_status(["--json"], write_path)

    cmd = argv[0]
    args = argv[1:]
    if cmd in {"help", "--help", "-h"}:
        return usage()
    if cmd == "status":
        return command_status(args, write_path)
    if cmd == "start":
        return command_start(args, write_path, repo_root)
    if cmd == "checkpoint":
        return command_checkpoint(args, write_path, repo_root)
    if cmd == "mark-patch":
        return command_mark_patch(args, write_path)
    if cmd == "validate":
        return command_validate(args, write_path)
    if cmd == "close":
        return command_close(args, write_path)
    if cmd == "doctor":
        return command_doctor(args, write_path)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
