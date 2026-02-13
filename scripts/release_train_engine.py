#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CHANGELOG_PATH = "CHANGELOG.md"
DEFAULT_ALLOWED_BRANCH_RE = r"^(main|release/.+)$"


@dataclass(frozen=True, order=True)
class SemVer:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, raw: str) -> SemVer | None:
        match = re.fullmatch(r"([1-9]\d*|0)\.([1-9]\d*|0)\.([1-9]\d*|0)", raw.strip())
        if not match:
            return None
        return cls(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    def bump_kind_from(self, prior: SemVer) -> str:
        if self.major > prior.major:
            return "major"
        if self.minor > prior.minor:
            return "minor"
        if self.patch > prior.patch:
            return "patch"
        return "none"


def run_git(repo_root: Path, args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def latest_tag(repo_root: Path) -> str | None:
    rc, out, _ = run_git(repo_root, ["describe", "--tags", "--abbrev=0"])
    return out if rc == 0 and out else None


def current_branch(repo_root: Path) -> str | None:
    rc, out, _ = run_git(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"])
    return out if rc == 0 and out else None


def is_clean_tree(repo_root: Path) -> bool:
    rc, out, _ = run_git(repo_root, ["status", "--porcelain"])
    if rc != 0:
        return False
    filtered = [
        line for line in out.splitlines() if not line.strip().endswith(".beads/")
    ]
    return len(filtered) == 0


def branch_behind_remote(repo_root: Path, branch: str) -> bool:
    upstream = f"origin/{branch}"
    rc, _, _ = run_git(repo_root, ["rev-parse", "--verify", upstream])
    if rc != 0:
        return False
    rc, out, _ = run_git(
        repo_root, ["rev-list", "--left-right", "--count", f"HEAD...{upstream}"]
    )
    if rc != 0:
        return False
    parts = out.split()
    if len(parts) != 2:
        return False
    behind = int(parts[1])
    return behind > 0


def check_validation_targets(repo_root: Path) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for target in ["validate", "selftest", "install-test"]:
        proc = subprocess.run(
            ["make", "-n", target],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        results[target] = proc.returncode == 0
    return results


def changelog_contains_version(repo_root: Path, version: str) -> bool:
    changelog = repo_root / CHANGELOG_PATH
    if not changelog.exists():
        return False
    text = changelog.read_text(encoding="utf-8")
    return f"## v{version}" in text


def looks_breaking_change(repo_root: Path) -> bool:
    changelog = repo_root / CHANGELOG_PATH
    if not changelog.exists():
        return False
    text = changelog.read_text(encoding="utf-8").lower()
    return "breaking" in text


def evaluate_prepare(
    repo_root: Path,
    *,
    version: str,
    allow_version_jump: bool,
    breaking_change: bool,
    allowed_branch_re: str,
) -> dict[str, Any]:
    reason_codes: list[str] = []
    remediation: list[str] = []

    branch = current_branch(repo_root)
    clean = is_clean_tree(repo_root)
    validations = check_validation_targets(repo_root)
    tag = latest_tag(repo_root)

    if not clean:
        reason_codes.append("dirty_worktree")
        remediation.append("commit or stash local changes before preparing a release")

    if not branch or not re.match(allowed_branch_re, branch):
        reason_codes.append("branch_not_allowed")
        remediation.append("switch to main or a release/* branch")

    if branch and branch_behind_remote(repo_root, branch):
        reason_codes.append("branch_behind_remote")
        remediation.append("pull/rebase to align with origin before release")

    if not validations.get("validate", False):
        reason_codes.append("validate_failed")
        remediation.append("run make validate and resolve failures")
    if not validations.get("selftest", False):
        reason_codes.append("selftest_failed")
        remediation.append("run make selftest and resolve failures")
    if not validations.get("install-test", False):
        reason_codes.append("install_test_failed")
        remediation.append("run make install-test and resolve failures")

    if not changelog_contains_version(repo_root, version):
        reason_codes.append("changelog_missing_version")
        remediation.append(f"add a changelog heading for v{version}")

    parsed_target = SemVer.parse(version)
    parsed_tag: SemVer | None = None
    if tag and tag.startswith("v"):
        parsed_tag = SemVer.parse(tag[1:])

    if parsed_target is None:
        reason_codes.append("version_not_incremented")
        remediation.append("provide a semantic version in MAJOR.MINOR.PATCH format")
    elif parsed_tag and parsed_target <= parsed_tag:
        reason_codes.append("version_not_incremented")
        remediation.append("choose a target version greater than the latest tag")
    elif parsed_target and parsed_tag:
        bump_kind = parsed_target.bump_kind_from(parsed_tag)
        if bump_kind == "major" and not breaking_change:
            reason_codes.append("major_requires_breaking_flag")
            remediation.append("add --breaking-change when publishing a major release")
        if (
            bump_kind == "minor"
            and parsed_target.major == parsed_tag.major
            and (parsed_target.minor - parsed_tag.minor > 1)
            and not allow_version_jump
        ):
            reason_codes.append("version_jump_requires_override")
            remediation.append(
                "add --allow-version-jump for intentional multi-minor jumps"
            )
        if (
            bump_kind == "patch"
            and parsed_target.minor == parsed_tag.minor
            and (parsed_target.patch - parsed_tag.patch > 1)
            and not allow_version_jump
        ):
            reason_codes.append("version_jump_requires_override")
            remediation.append(
                "add --allow-version-jump for intentional multi-patch jumps"
            )

    if parsed_target and parsed_tag and looks_breaking_change(repo_root):
        if parsed_target.major == parsed_tag.major:
            reason_codes.append("version_mismatch_breaking_change")
            remediation.append("breaking changes require a major version bump")

    ready = len(reason_codes) == 0
    return {
        "ready": ready,
        "version": version,
        "latest_tag": tag,
        "branch": branch,
        "reason_codes": sorted(set(reason_codes)),
        "remediation": sorted(set(remediation)),
        "checks": {
            "clean_worktree": clean,
            "allowed_branch": bool(branch and re.match(allowed_branch_re, branch)),
            "validate": validations.get("validate", False),
            "selftest": validations.get("selftest", False),
            "install_test": validations.get("install-test", False),
            "changelog_has_version": changelog_contains_version(repo_root, version),
        },
    }


def draft_release_notes(
    repo_root: Path, *, base_tag: str | None, head: str
) -> dict[str, Any]:
    start = base_tag or latest_tag(repo_root)
    if start:
        range_ref = f"{start}..{head}"
        rc, out, err = run_git(repo_root, ["log", "--oneline", range_ref])
    else:
        rc, out, err = run_git(repo_root, ["log", "--oneline", "-20", head])
    if rc != 0:
        return {
            "result": "FAIL",
            "reason_codes": ["draft_generation_failed"],
            "error": err or "unable to compute release notes",
            "base_tag": start,
            "head": head,
            "entries": [],
        }
    entries = [line.strip() for line in out.splitlines() if line.strip()]
    bullets = [f"- {line}" for line in entries]
    return {
        "result": "PASS",
        "base_tag": start,
        "head": head,
        "entry_count": len(entries),
        "entries": entries,
        "markdown": "\n".join(bullets),
    }


def usage() -> int:
    print(
        "usage: /release-train-engine <status|prepare|draft|publish|doctor> [--json] "
        "[--repo-root <path>]"
    )
    return 2


def print_payload(payload: dict[str, Any], as_json: bool) -> None:
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


def main(argv: list[str]) -> int:
    args = list(argv)
    as_json = pop_flag(args, "--json")
    repo_root_raw = pop_value(args, "--repo-root", str(REPO_ROOT))
    repo_root = Path(repo_root_raw or str(REPO_ROOT)).resolve()

    if not args:
        return usage()
    cmd = args.pop(0)

    if cmd == "status":
        payload = {
            "result": "PASS",
            "repo_root": str(repo_root),
            "branch": current_branch(repo_root),
            "latest_tag": latest_tag(repo_root),
            "clean_worktree": is_clean_tree(repo_root),
        }
        print_payload(payload, as_json)
        return 0

    if cmd == "prepare":
        try:
            version = pop_value(args, "--version")
            if not version:
                print("--version is required for prepare", file=sys.stderr)
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
        print_payload(payload, as_json)
        return 0 if payload.get("ready") else 1

    if cmd == "draft":
        try:
            base_tag = pop_value(args, "--base-tag")
            head = pop_value(args, "--head", "HEAD") or "HEAD"
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        payload = draft_release_notes(repo_root, base_tag=base_tag, head=head)
        print_payload(payload, as_json)
        return 0 if payload.get("result") == "PASS" else 1

    if cmd == "publish":
        try:
            version = pop_value(args, "--version")
            if not version:
                print("--version is required for publish", file=sys.stderr)
                return 2
            dry_run = pop_flag(args, "--dry-run")
            confirm = pop_flag(args, "--confirm")
            prepare_payload = evaluate_prepare(
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

        if not prepare_payload.get("ready"):
            payload = {
                "result": "FAIL",
                "reason_codes": prepare_payload.get("reason_codes", []),
                "remediation": prepare_payload.get("remediation", []),
                "prepare": prepare_payload,
            }
            print_payload(payload, as_json)
            return 1

        if not dry_run and not confirm:
            payload = {
                "result": "FAIL",
                "reason_codes": ["confirmation_required"],
                "remediation": ["re-run publish with --confirm or use --dry-run"],
            }
            print_payload(payload, as_json)
            return 1

        payload = {
            "result": "PASS",
            "dry_run": dry_run,
            "confirmed": confirm,
            "version": version,
            "publish_stage": "pre_publish_checks",
            "rollback_actions": [
                "if tag was created and publish failed, delete local/remote tag",
                "if publish completed, keep tag and create follow-up issue",
            ],
            "manual_followups": [
                "verify release notes and assets",
                "announce release in operator channel",
            ],
            "reason_codes": [],
        }
        print_payload(payload, as_json)
        return 0

    if cmd == "doctor":
        contract = repo_root / "instructions" / "release_train_policy_contract.md"
        payload = {
            "result": "PASS" if contract.exists() else "FAIL",
            "engine_exists": Path(__file__).exists(),
            "contract_exists": contract.exists(),
            "contract_path": str(contract),
        }
        print_payload(payload, as_json)
        return 0 if payload["result"] == "PASS" else 1

    return usage()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
