#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import subprocess
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


PR_PATTERN = re.compile(r"/pull/(\d+)")


def usage() -> int:
    print(
        "usage: /release-train [status|prepare|draft|rollup|publish|doctor] "
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
    write_summary_raw = pop_value(args, "--write-summary")
    write_summary = Path(write_summary_raw).expanduser() if write_summary_raw else None

    def emit_with_summary(payload: dict[str, Any]) -> None:
        if write_summary is not None:
            write_summary.parent.mkdir(parents=True, exist_ok=True)
            write_summary.write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8"
            )
            payload["summary_path"] = str(write_summary.resolve())
        emit(payload, as_json=as_json)

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
        create_tag = pop_flag(args, "--create-tag")
        create_release = pop_flag(args, "--create-release")
        notes_file_raw = pop_value(args, "--notes-file")
        notes_file = Path(notes_file_raw).expanduser() if notes_file_raw else None
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
        if args:
            return usage()
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
        emit_with_summary(payload)
        return 1

    reason_codes: list[str] = []
    remediation: list[str] = []
    if create_release and notes_file is None:
        reason_codes.append("release_notes_required_for_create_release")
        remediation.append("provide --notes-file <path> when using --create-release")
    if notes_file is not None and not notes_file.exists():
        reason_codes.append("release_notes_missing_file")
        remediation.append("ensure --notes-file path exists")
    if reason_codes:
        payload = {
            "result": "FAIL",
            "reason_codes": reason_codes,
            "remediation": remediation,
            "version": version,
            "dry_run": dry_run,
            "confirmed": confirm,
        }
        emit_with_summary(payload)
        return 1

    tag_name = f"v{version}"
    publish_plan: list[str] = []
    if create_tag:
        publish_plan.append(f"create and push annotated tag {tag_name}")
    if create_release:
        publish_plan.append(f"create GitHub release {tag_name} from notes file")
    if not publish_plan:
        publish_plan.append("no external publish actions selected")

    if dry_run:
        payload = {
            "result": "PASS",
            "version": version,
            "dry_run": True,
            "confirmed": confirm,
            "publish_stage": "dry_run_plan",
            "publish_plan": publish_plan,
            "tag_name": tag_name,
            "notes_file": str(notes_file.resolve()) if notes_file is not None else None,
            "reason_codes": [],
            "remediation": [],
        }
        emit_with_summary(payload)
        return 0

    if not dry_run and not confirm:
        payload = {
            "result": "FAIL",
            "reason_codes": ["confirmation_required"],
            "remediation": ["re-run with --confirm or add --dry-run"],
            "publish_plan": publish_plan,
            "tag_name": tag_name,
            "notes_file": str(notes_file.resolve()) if notes_file is not None else None,
        }
        emit_with_summary(payload)
        return 1

    executed_actions: list[str] = []
    failure_reason_codes: list[str] = []
    remediation_actions: list[str] = []

    if create_tag:
        create_tag_proc = subprocess.run(
            ["git", "tag", "-a", tag_name, "-m", f"release {tag_name}"],
            capture_output=True,
            text=True,
            check=False,
            cwd=repo_root,
        )
        if create_tag_proc.returncode != 0:
            failure_reason_codes.append("tag_create_failed")
            remediation_actions.append(
                create_tag_proc.stderr.strip()
                or create_tag_proc.stdout.strip()
                or "verify tag does not already exist"
            )
        else:
            executed_actions.append(f"tag_created:{tag_name}")
            push_tag_proc = subprocess.run(
                ["git", "push", "origin", tag_name],
                capture_output=True,
                text=True,
                check=False,
                cwd=repo_root,
            )
            if push_tag_proc.returncode != 0:
                failure_reason_codes.append("tag_push_failed")
                remediation_actions.append(
                    push_tag_proc.stderr.strip()
                    or push_tag_proc.stdout.strip()
                    or "verify remote origin and push permissions"
                )
            else:
                executed_actions.append(f"tag_pushed:{tag_name}")

    if create_release and notes_file is not None:
        release_proc = subprocess.run(
            [
                "gh",
                "release",
                "create",
                tag_name,
                "--title",
                tag_name,
                "--notes-file",
                str(notes_file.resolve()),
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=repo_root,
        )
        if release_proc.returncode != 0:
            failure_reason_codes.append("release_create_failed")
            remediation_actions.append(
                release_proc.stderr.strip()
                or release_proc.stdout.strip()
                or "verify gh auth and release permissions"
            )
        else:
            executed_actions.append(f"release_created:{tag_name}")

    payload = {
        "result": "PASS" if not failure_reason_codes else "FAIL",
        "version": version,
        "dry_run": False,
        "confirmed": True,
        "publish_stage": "executed",
        "publish_plan": publish_plan,
        "tag_name": tag_name,
        "notes_file": str(notes_file.resolve()) if notes_file is not None else None,
        "executed_actions": executed_actions,
        "reason_codes": failure_reason_codes,
        "remediation": remediation_actions,
        "rollback_actions": [
            "if publish fails after tag creation, delete local and remote tag",
            "if publish succeeded, keep tag and open post-release follow-up issue",
        ],
        "manual_followups": [
            "confirm generated release notes",
            "broadcast release announcement",
        ],
    }
    emit_with_summary(payload)
    return 0 if payload["result"] == "PASS" else 1


def _extract_pr_numbers(text: str) -> list[int]:
    values = [int(match.group(1)) for match in PR_PATTERN.finditer(text)]
    deduped: list[int] = []
    seen: set[int] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def command_rollup(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    title = pop_value(args, "--title", "Release Rollup Draft") or "Release Rollup Draft"
    write_path_raw = pop_value(args, "--write")
    write_path = Path(write_path_raw).expanduser() if write_path_raw else None

    milestone_paths: list[Path] = []
    while True:
        value = pop_value(args, "--milestone")
        if value is None:
            break
        milestone_paths.append(Path(value).expanduser())

    if args or not milestone_paths:
        return usage()

    missing = [str(path) for path in milestone_paths if not path.exists()]
    if missing:
        payload = {
            "result": "FAIL",
            "reason_codes": ["rollup_milestone_missing"],
            "missing": missing,
        }
        emit(payload, as_json=as_json)
        return 1

    pr_numbers: list[int] = []
    source_lines: list[str] = []
    for path in milestone_paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for pr in _extract_pr_numbers(text):
            if pr not in pr_numbers:
                pr_numbers.append(pr)
        source_lines.append(f"- {path}")

    markdown = "\n".join(
        [
            f"# {title}",
            "",
            "## Milestone Sources",
            *source_lines,
            "",
            "## Included PRs",
            *([f"- #{pr}" for pr in pr_numbers] or ["- <none detected>"]),
            "",
            "## Validation Evidence",
            "- make validate",
            "- make selftest",
            "- make install-test",
            "- pre-commit run --all-files",
        ]
    )

    if write_path is not None:
        write_path.parent.mkdir(parents=True, exist_ok=True)
        write_path.write_text(markdown + "\n", encoding="utf-8")

    payload = {
        "result": "PASS",
        "reason_codes": ["rollup_draft_generated"],
        "title": title,
        "milestones": [str(path) for path in milestone_paths],
        "pr_numbers": pr_numbers,
        "markdown": markdown,
        "written_path": str(write_path.resolve()) if write_path is not None else None,
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
    if cmd == "rollup":
        return command_rollup(rest)
    if cmd == "publish":
        return command_publish(rest)
    if cmd == "doctor":
        return command_doctor(rest)
    return command_status(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
