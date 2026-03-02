#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from hashlib import sha256
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
WAVE_PLAN_RE = re.compile(r"^(v(\d+)\.(\d+))-flow-wave-plan\.md$")
PUBLISH_SUMMARY_SCHEMA_VERSION = "1.0"
PUBLISH_PROFILE_PRESETS: dict[str, dict[str, bool]] = {
    "docs-only": {"create_tag": True, "create_release": False},
    "runtime": {"create_tag": True, "create_release": True},
}
PLAN_HYGIENE_CHECK_SCRIPT = SCRIPT_DIR / "plan_hygiene_check.py"


def usage() -> int:
    print(
        "usage: /release-train [status|prepare|draft|rollup|publish|doctor] "
        "[--json] [--version <x.y.z>] [--profile docs-only|runtime] [--repo-root <path>]"
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


def run_plan_hygiene_check(repo_root: Path) -> dict[str, Any]:
    if not PLAN_HYGIENE_CHECK_SCRIPT.exists():
        return {
            "result": "FAIL",
            "reason_codes": ["plan_hygiene_checker_missing"],
            "findings": [
                {
                    "path": str(PLAN_HYGIENE_CHECK_SCRIPT),
                    "line": 1,
                    "reason_code": "plan_hygiene_checker_missing",
                    "message": "missing scripts/plan_hygiene_check.py",
                }
            ],
            "quick_fixes": ["restore scripts/plan_hygiene_check.py"],
        }
    completed = subprocess.run(
        [
            sys.executable,
            str(PLAN_HYGIENE_CHECK_SCRIPT),
            "--repo-root",
            str(repo_root),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo_root,
    )
    if not completed.stdout.strip():
        detail = (
            completed.stderr.strip() or "plan hygiene checker returned empty output"
        )
        return {
            "result": "FAIL",
            "reason_codes": ["plan_hygiene_checker_unparseable"],
            "findings": [
                {
                    "path": str(PLAN_HYGIENE_CHECK_SCRIPT),
                    "line": 1,
                    "reason_code": "plan_hygiene_checker_unparseable",
                    "message": detail,
                }
            ],
            "quick_fixes": ["python3 scripts/plan_hygiene_check.py --json"],
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        detail = completed.stderr.strip() or completed.stdout.strip()
        return {
            "result": "FAIL",
            "reason_codes": ["plan_hygiene_checker_unparseable"],
            "findings": [
                {
                    "path": str(PLAN_HYGIENE_CHECK_SCRIPT),
                    "line": 1,
                    "reason_code": "plan_hygiene_checker_unparseable",
                    "message": detail,
                }
            ],
            "quick_fixes": ["python3 scripts/plan_hygiene_check.py --json"],
        }
    if "result" not in payload:
        payload["result"] = "FAIL"
    return payload


def run_wave_closure_readiness(repo_root: Path) -> dict[str, Any]:
    plan_dir = repo_root / "docs" / "plan"
    candidates: list[tuple[int, int, str, Path]] = []
    for path in sorted(plan_dir.glob("*-flow-wave-plan.md")):
        match = WAVE_PLAN_RE.match(path.name)
        if not match:
            continue
        wave = match.group(1)
        major = int(match.group(2))
        minor = int(match.group(3))
        candidates.append((major, minor, wave, path))

    if not candidates:
        return {
            "recommended": False,
            "reason_codes": [],
            "quick_fixes": [],
            "active_wave": None,
            "active_plan_path": None,
            "completion_path": None,
            "all_epics_complete": False,
            "completion_exists": False,
        }

    _, _, wave, plan_path = max(candidates)
    plan_text = plan_path.read_text(encoding="utf-8", errors="replace")
    has_done_checkbox = bool(
        re.search(r"^\s*- \[[xX]\]", plan_text, flags=re.MULTILINE)
    )
    has_pending_checkbox = bool(
        re.search(r"^\s*- \[ \]", plan_text, flags=re.MULTILINE)
    )
    all_epics_complete = has_done_checkbox and not has_pending_checkbox
    completion_path = plan_path.with_name(
        plan_path.name.replace("-plan.md", "-completion.md")
    )
    completion_exists = completion_path.exists()
    recommended = all_epics_complete and not completion_exists
    quick_fixes = []
    if recommended:
        quick_fixes.append(
            f"python3 scripts/update_wave_completion_doc.py --wave {wave} --pr <number>"
        )
    return {
        "recommended": recommended,
        "reason_codes": ["wave_completion_artifact_recommended"] if recommended else [],
        "quick_fixes": quick_fixes,
        "active_wave": wave,
        "active_plan_path": str(plan_path),
        "completion_path": str(completion_path),
        "all_epics_complete": all_epics_complete,
        "completion_exists": completion_exists,
    }


def _local_tag_exists(repo_root: Path, tag_name: str) -> bool:
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag_name}"],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo_root,
    )
    return proc.returncode == 0


def _resolve_publish_profile(
    *,
    profile: str | None,
    create_tag: bool,
    create_release: bool,
    explicit_create_tag: bool,
    explicit_create_release: bool,
) -> tuple[bool, bool, str]:
    if profile is None:
        return create_tag, create_release, "custom"
    preset = PUBLISH_PROFILE_PRESETS.get(profile)
    if preset is None:
        raise ValueError(
            "--profile must be one of: " + ", ".join(sorted(PUBLISH_PROFILE_PRESETS))
        )
    resolved_create_tag = create_tag if explicit_create_tag else preset["create_tag"]
    resolved_create_release = (
        create_release if explicit_create_release else preset["create_release"]
    )
    return resolved_create_tag, resolved_create_release, profile


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
    plan_hygiene = run_plan_hygiene_check(repo_root)
    plan_hygiene_pass = plan_hygiene.get("result") == "PASS"
    wave_closure = run_wave_closure_readiness(repo_root)
    payload["plan_hygiene"] = plan_hygiene
    payload["wave_closure_readiness"] = wave_closure
    if not plan_hygiene_pass:
        reason_codes = list(payload.get("reason_codes", []))
        if "plan_hygiene_findings_present" not in reason_codes:
            reason_codes.append("plan_hygiene_findings_present")
        payload["reason_codes"] = reason_codes
        payload["ready"] = False
        next_actions = list(payload.get("next_actions", []))
        if "/release-train doctor --json" not in next_actions:
            next_actions.append("/release-train doctor --json")
        payload["next_actions"] = next_actions
    if wave_closure.get("recommended"):
        next_actions = list(payload.get("next_actions", []))
        recommendation = f"python3 scripts/update_wave_completion_doc.py --wave {wave_closure.get('active_wave')} --pr <number>"
        if recommendation not in next_actions:
            next_actions.append(recommendation)
        payload["next_actions"] = next_actions
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
        {
            "id": "plan_hygiene",
            "status": "pass" if plan_hygiene_pass else "fail",
        },
        {
            "id": "wave_completion_artifact",
            "status": "fail" if wave_closure.get("recommended") else "pass",
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
        payload["summary_schema_version"] = PUBLISH_SUMMARY_SCHEMA_VERSION
        if write_summary is not None:
            serializable_payload = dict(payload)
            summary_checksum = sha256(
                json.dumps(serializable_payload, sort_keys=True).encode("utf-8")
            ).hexdigest()
            serializable_payload["summary_checksum"] = summary_checksum
            write_summary.parent.mkdir(parents=True, exist_ok=True)
            write_summary.write_text(
                json.dumps(serializable_payload, indent=2) + "\n", encoding="utf-8"
            )
            payload["summary_path"] = str(write_summary.resolve())
            payload["summary_checksum"] = summary_checksum
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
        explicit_create_tag = "--create-tag" in args
        explicit_create_release = "--create-release" in args
        create_tag = pop_flag(args, "--create-tag")
        create_release = pop_flag(args, "--create-release")
        publish_profile = pop_value(args, "--profile")
        create_tag, create_release, publish_profile = _resolve_publish_profile(
            profile=publish_profile,
            create_tag=create_tag,
            create_release=create_release,
            explicit_create_tag=explicit_create_tag,
            explicit_create_release=explicit_create_release,
        )
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

    tag_name = f"v{version}"
    preflight_reason_codes: list[str] = []
    preflight_remediation: list[str] = []
    if create_tag and _local_tag_exists(repo_root, tag_name):
        preflight_reason_codes.append("publish_tag_already_exists")
        preflight_remediation.append(
            f"delete or bump version before publishing: git tag -d {tag_name}"
        )
    if create_release and not create_tag and not _local_tag_exists(repo_root, tag_name):
        preflight_reason_codes.append("publish_release_tag_missing")
        preflight_remediation.append(
            "create and push the release tag first, or add --create-tag for one-step publish"
        )

    if not prepare.get("ready"):
        merged_reason_codes = sorted(
            set([*prepare.get("reason_codes", []), *preflight_reason_codes])
        )
        merged_remediation = [
            *prepare.get("remediation", []),
            *preflight_remediation,
        ]
        payload = {
            "result": "FAIL",
            "reason_codes": merged_reason_codes,
            "remediation": merged_remediation,
            "prepare": prepare,
            "publish_profile": publish_profile,
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
            "publish_profile": publish_profile,
        }
        emit_with_summary(payload)
        return 1

    publish_plan: list[str] = []
    if create_tag:
        publish_plan.append(f"create and push annotated tag {tag_name}")
    if create_release:
        publish_plan.append(f"create GitHub release {tag_name} from notes file")
    if not publish_plan:
        publish_plan.append("no external publish actions selected")

    if preflight_reason_codes:
        payload = {
            "result": "FAIL",
            "version": version,
            "dry_run": dry_run,
            "confirmed": confirm,
            "publish_stage": "preflight_failed",
            "publish_profile": publish_profile,
            "publish_plan": publish_plan,
            "tag_name": tag_name,
            "notes_file": str(notes_file.resolve()) if notes_file is not None else None,
            "reason_codes": preflight_reason_codes,
            "remediation": preflight_remediation,
        }
        emit_with_summary(payload)
        return 1

    action_matrix = [
        {
            "action": "create_tag",
            "requested": create_tag,
            "status": "planned" if create_tag else "skipped",
        },
        {
            "action": "create_release",
            "requested": create_release,
            "status": "planned" if create_release else "skipped",
        },
    ]
    if not create_tag and not create_release:
        action_matrix.append(
            {
                "action": "external_publish",
                "requested": False,
                "status": "none_selected",
            }
        )

    if dry_run:
        payload = {
            "result": "PASS",
            "version": version,
            "dry_run": True,
            "confirmed": confirm,
            "publish_profile": publish_profile,
            "publish_stage": "dry_run_plan",
            "publish_plan": publish_plan,
            "tag_name": tag_name,
            "notes_file": str(notes_file.resolve()) if notes_file is not None else None,
            "action_matrix": action_matrix,
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
            "publish_profile": publish_profile,
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
        "publish_profile": publish_profile,
        "publish_stage": "executed",
        "publish_plan": publish_plan,
        "tag_name": tag_name,
        "notes_file": str(notes_file.resolve()) if notes_file is not None else None,
        "action_matrix": action_matrix,
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

    provenance = {
        "generated_by": "release_train_command.rollup",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_milestone_count": len(milestone_paths),
        "source_pr_count": len(pr_numbers),
    }

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
            "## Provenance",
            f"- generated_by: {provenance['generated_by']}",
            f"- generated_at_utc: {provenance['generated_at_utc']}",
            f"- source_milestone_count: {provenance['source_milestone_count']}",
            f"- source_pr_count: {provenance['source_pr_count']}",
            "",
            "## Validation Evidence",
            "- make validate",
            "- make selftest",
            "- make install-test",
            "- npm --prefix plugin/gateway-core run lint",
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
        "provenance": provenance,
        "markdown": markdown,
        "written_path": str(write_path.resolve()) if write_path is not None else None,
    }
    emit(payload, as_json=as_json)
    return 0


def command_doctor(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    try:
        repo_root = Path(
            pop_value(args, "--repo-root", str(REPO_ROOT)) or str(REPO_ROOT)
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args:
        return usage()
    engine_exists = (SCRIPT_DIR / "release_train_engine.py").exists()
    contract_exists = (
        SCRIPT_DIR.parent / "instructions" / "release_train_policy_contract.md"
    ).exists()
    plan_hygiene = run_plan_hygiene_check(repo_root)
    plan_hygiene_pass = plan_hygiene.get("result") == "PASS"
    wave_closure = run_wave_closure_readiness(repo_root)
    wave_closure_recommended = bool(wave_closure.get("recommended"))
    plan_hygiene_reason_codes = [
        str(code)
        for code in plan_hygiene.get("reason_codes", [])
        if isinstance(code, str)
    ]
    wave_closure_reason_codes = [
        str(code)
        for code in wave_closure.get("reason_codes", [])
        if isinstance(code, str)
    ]
    warnings = [] if contract_exists else ["missing release policy contract"]
    if not plan_hygiene_pass:
        warnings.append("plan hygiene findings detected")
    if wave_closure_recommended:
        warnings.append("wave completion artifact is recommended")
    problems = [] if engine_exists else ["missing scripts/release_train_engine.py"]
    if not plan_hygiene_pass:
        problems.append("stale done plan entries missing closure evidence links")
    quick_fixes = [
        "/release-train status --json",
        "/release-train prepare --version 0.0.0 --json",
    ]
    if not plan_hygiene_pass:
        quick_fixes.append("python3 scripts/plan_hygiene_check.py --json")
    if wave_closure_recommended:
        quick_fixes.extend(
            [
                f"python3 scripts/update_wave_completion_doc.py --wave {wave_closure.get('active_wave')} --pr <number>",
                f"create {wave_closure.get('completion_path')}",
            ]
        )
    report = {
        "result": "PASS" if (engine_exists and plan_hygiene_pass) else "FAIL",
        "engine_exists": engine_exists,
        "contract_exists": contract_exists,
        "repo_root": str(repo_root),
        "plan_hygiene_pass": plan_hygiene_pass,
        "plan_hygiene_reason_codes": plan_hygiene_reason_codes,
        "wave_closure_recommended": wave_closure_recommended,
        "wave_closure_reason_codes": wave_closure_reason_codes,
        "wave_closure": wave_closure,
        "warnings": warnings,
        "problems": problems,
        "quick_fixes": quick_fixes,
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
