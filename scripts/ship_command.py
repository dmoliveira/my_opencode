#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from flow_reason_codes import SHIP_PREPARE_BLOCKED, SHIP_READY  # type: ignore


SCRIPT_DIR = Path(__file__).resolve().parent
RELEASE_TRAIN_SCRIPT = SCRIPT_DIR / "release_train_command.py"


def usage() -> int:
    print(
        "usage: /ship --version <x.y.z> [--allow-version-jump] [--breaking-change] [--emit-pr-template] [--json] | "
        "/ship create-pr --version <x.y.z> [--base <ref>] [--head <ref>] [--confirm] [--json]"
    )
    return 2


def _pop_flag(args: list[str], flag: str) -> bool:
    if flag in args:
        args.remove(flag)
        return True
    return False


def _pop_value(args: list[str], flag: str) -> str | None:
    if flag not in args:
        return None
    idx = args.index(flag)
    if idx + 1 >= len(args):
        raise ValueError(f"{flag} requires a value")
    value = args[idx + 1]
    del args[idx : idx + 2]
    return value


def _build_pr_template(version: str) -> dict[str, str]:
    return {
        "title": f"ship {version}",
        "body_markdown": "\n".join(
            [
                "## Summary",
                "- <1-3 bullets on why this release is shipping>",
                "",
                "## Risk",
                "- <known risk or 'none'>",
                "",
                "## Validation Evidence",
                "- make validate",
                "- make selftest",
                "- make install-test",
                "- pre-commit run --all-files",
                "",
                "## Migration Notes",
                "- <operator migration notes or 'none'>",
            ]
        ),
    }


def _prepare_payload(
    *, version: str, allow_jump: bool, breaking: bool, emit_pr_template: bool
) -> tuple[dict[str, Any], int]:
    prepare_cmd = [
        sys.executable,
        str(RELEASE_TRAIN_SCRIPT),
        "prepare",
        "--version",
        version,
        "--json",
    ]
    if allow_jump:
        prepare_cmd.append("--allow-version-jump")
    if breaking:
        prepare_cmd.append("--breaking-change")

    prepare = subprocess.run(
        prepare_cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if prepare.returncode not in (0, 1):
        payload = {
            "result": "FAIL",
            "reason_code": "ship_prepare_exec_failed",
            "detail": prepare.stderr.strip() or prepare.stdout.strip(),
        }
        return payload, prepare.returncode

    try:
        prepare_payload = json.loads(prepare.stdout) if prepare.stdout else {}
    except json.JSONDecodeError:
        prepare_payload = {}

    ready = bool(prepare_payload.get("ready"))
    payload: dict[str, Any] = {
        "result": "PASS" if ready else "FAIL",
        "reason_code": SHIP_READY if ready else SHIP_PREPARE_BLOCKED,
        "version": version,
        "prepare": prepare_payload,
        "required_evidence": [
            "make validate",
            "make selftest",
            "make install-test",
            "pre-commit run --all-files",
            "PR summary/body prepared",
        ],
        "next_actions": [
            "/release-train draft --include-milestones --head HEAD --json",
            "gh pr create --title '<title>' --body '<summary>'",
        ]
        if ready
        else ["fix prepare blockers then re-run /ship --version <x.y.z> --json"],
    }
    if emit_pr_template:
        payload["pr_template"] = _build_pr_template(version)
    return payload, 0 if ready else 1


def _command_create_pr(args: list[str], as_json: bool) -> int:
    try:
        version = _pop_value(args, "--version")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    base_ref = _pop_value(args, "--base") or "main"
    head_ref = _pop_value(args, "--head") or "HEAD"
    confirm = _pop_flag(args, "--confirm")
    if args or not version:
        return usage()

    payload, code = _prepare_payload(
        version=version,
        allow_jump=False,
        breaking=False,
        emit_pr_template=True,
    )
    template = payload.get("pr_template") if isinstance(payload, dict) else None
    if not isinstance(template, dict):
        template = _build_pr_template(version)

    if code != 0:
        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"result: {payload.get('result')}")
            print(f"reason_code: {payload.get('reason_code')}")
        return 1

    if not confirm:
        preview = {
            "result": "FAIL",
            "reason_code": "confirmation_required",
            "version": version,
            "base": base_ref,
            "head": head_ref,
            "pr_template": template,
            "next_actions": ["re-run with --confirm to create PR"],
        }
        if as_json:
            print(json.dumps(preview, indent=2))
        else:
            print("reason_code: confirmation_required")
            print("re-run with --confirm to create PR")
        return 1

    body = str(template.get("body_markdown") or "")
    title = str(template.get("title") or f"ship {version}")
    created = subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--base",
            base_ref,
            "--head",
            head_ref,
            "--title",
            title,
            "--body",
            body,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode != 0:
        failure = {
            "result": "FAIL",
            "reason_code": "ship_pr_create_failed",
            "detail": created.stderr.strip() or created.stdout.strip(),
        }
        if as_json:
            print(json.dumps(failure, indent=2))
        else:
            print(failure["reason_code"])
        return created.returncode

    success = {
        "result": "PASS",
        "reason_code": "ship_pr_created",
        "version": version,
        "url": created.stdout.strip(),
        "title": title,
        "base": base_ref,
        "head": head_ref,
    }
    if as_json:
        print(json.dumps(success, indent=2))
    else:
        print(f"result: {success['result']}")
        print(f"url: {success['url']}")
    return 0


def main(argv: list[str]) -> int:
    args = list(argv)
    as_json = _pop_flag(args, "--json")

    if args and args[0] == "create-pr":
        return _command_create_pr(args[1:], as_json)

    try:
        version = _pop_value(args, "--version")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    allow_jump = _pop_flag(args, "--allow-version-jump")
    breaking = _pop_flag(args, "--breaking-change")
    emit_pr_template = _pop_flag(args, "--emit-pr-template")

    if args or not version:
        return usage()

    payload, code = _prepare_payload(
        version=version,
        allow_jump=allow_jump,
        breaking=breaking,
        emit_pr_template=emit_pr_template,
    )

    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"result: {payload['result']}")
        print(f"reason_code: {payload['reason_code']}")
        print(f"version: {payload['version']}")
        if emit_pr_template:
            print("pr_template: enabled")
        print("next_actions:")
        for action in payload["next_actions"]:
            print(f"- {action}")
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
