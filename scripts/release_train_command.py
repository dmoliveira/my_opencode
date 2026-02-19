#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from release_train_engine import (  # type: ignore
    DEFAULT_ALLOWED_BRANCH_RE,
    REPO_ROOT,
    current_branch,
    draft_release_notes,
    evaluate_prepare,
    is_clean_tree,
    latest_tag,
)


def usage() -> int:
    print(
        "usage: /release-train [status|prepare|draft|publish|doctor] "
        "[--json] [--version <x.y.z>]"
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


def emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def command_status(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    repo_root = Path(pop_value(args, "--repo-root", str(REPO_ROOT)) or str(REPO_ROOT))
    payload = {
        "result": "PASS",
        "branch": current_branch(repo_root),
        "latest_tag": latest_tag(repo_root),
        "clean_worktree": is_clean_tree(repo_root),
    }
    emit(payload, as_json=as_json)
    return 0


def command_prepare(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    try:
        repo_root = Path(
            pop_value(args, "--repo-root", str(REPO_ROOT)) or str(REPO_ROOT)
        )
        version = pop_value(args, "--version")
        if not version:
            print("--version is required", file=sys.stderr)
            return 2
        payload = evaluate_prepare(
            repo_root,
            version=version,
            allow_version_jump=pop_flag(args, "--allow-version-jump"),
            breaking_change=pop_flag(args, "--breaking-change"),
            allowed_branch_re=pop_value(
                args, "--allowed-branch-re", DEFAULT_ALLOWED_BRANCH_RE
            )
            or DEFAULT_ALLOWED_BRANCH_RE,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    checks = payload.get("checks", {})
    payload["checklist"] = [
        {
            "id": "clean_worktree",
            "status": "pass" if checks.get("clean_worktree") else "fail",
        },
        {
            "id": "validation_suite",
            "status": "pass"
            if checks.get("validate")
            and checks.get("selftest")
            and checks.get("install_test")
            else "fail",
        },
        {
            "id": "changelog_evidence",
            "status": "pass" if checks.get("changelog_has_version") else "fail",
        },
    ]
    emit(payload, as_json=as_json)
    return 0 if payload.get("ready") else 1


def command_draft(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    try:
        repo_root = Path(
            pop_value(args, "--repo-root", str(REPO_ROOT)) or str(REPO_ROOT)
        )
        base_tag = pop_value(args, "--base-tag")
        head = pop_value(args, "--head", "HEAD") or "HEAD"
        include_milestones = pop_flag(args, "--include-milestones")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    payload = draft_release_notes(
        repo_root,
        base_tag=base_tag,
        head=head,
        include_milestones=include_milestones,
    )
    emit(payload, as_json=as_json)
    return 0 if payload.get("result") == "PASS" else 1


def command_publish(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    try:
        repo_root = Path(
            pop_value(args, "--repo-root", str(REPO_ROOT)) or str(REPO_ROOT)
        )
        version = pop_value(args, "--version")
        if not version:
            print("--version is required", file=sys.stderr)
            return 2
        dry_run = pop_flag(args, "--dry-run")
        confirm = pop_flag(args, "--confirm")
        prepare = evaluate_prepare(
            repo_root,
            version=version,
            allow_version_jump=pop_flag(args, "--allow-version-jump"),
            breaking_change=pop_flag(args, "--breaking-change"),
            allowed_branch_re=pop_value(
                args, "--allowed-branch-re", DEFAULT_ALLOWED_BRANCH_RE
            )
            or DEFAULT_ALLOWED_BRANCH_RE,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if not prepare.get("ready"):
        payload = {
            "result": "FAIL",
            "reason_codes": prepare.get("reason_codes", []),
            "remediation": prepare.get("remediation", []),
            "prepare": prepare,
        }
        emit(payload, as_json=as_json)
        return 1

    if not dry_run and not confirm:
        payload = {
            "result": "FAIL",
            "reason_codes": ["confirmation_required"],
            "remediation": ["re-run with --confirm or add --dry-run"],
        }
        emit(payload, as_json=as_json)
        return 1

    payload = {
        "result": "PASS",
        "version": version,
        "dry_run": dry_run,
        "confirmed": confirm,
        "publish_stage": "pre_publish_checks",
        "rollback_actions": [
            "if publish fails after tag creation, delete local and remote tag",
            "if publish succeeded, keep tag and open post-release follow-up issue",
        ],
        "manual_followups": [
            "confirm generated release notes",
            "broadcast release announcement",
        ],
        "reason_codes": [],
    }
    emit(payload, as_json=as_json)
    return 0


def command_doctor(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    as_json = "--json" in args
    engine_exists = (SCRIPT_DIR / "release_train_engine.py").exists()
    contract_exists = (
        SCRIPT_DIR.parent / "instructions" / "release_train_policy_contract.md"
    ).exists()
    report = {
        "result": "PASS" if engine_exists else "FAIL",
        "engine_exists": engine_exists,
        "contract_exists": contract_exists,
        "warnings": [] if contract_exists else ["missing release policy contract"],
        "problems": []
        if engine_exists
        else ["missing scripts/release_train_engine.py"],
        "quick_fixes": [
            "/release-train status --json",
            "/release-train prepare --version 0.0.0 --json",
        ],
    }
    emit(report, as_json=as_json)
    return 0 if report["result"] == "PASS" else 1


def main(argv: list[str]) -> int:
    if not argv:
        return command_status([])
    cmd, *rest = argv
    if cmd in {"help", "--help", "-h"}:
        return usage()
    if cmd == "status":
        return command_status(rest)
    if cmd == "prepare":
        return command_prepare(rest)
    if cmd == "draft":
        return command_draft(rest)
    if cmd == "publish":
        return command_publish(rest)
    if cmd == "doctor":
        return command_doctor(rest)
    return command_status(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
