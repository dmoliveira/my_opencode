#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from hotfix_runtime import load_runtime, resolve_write_path, runtime_path  # type: ignore


HOTFIX_RUNTIME_SCRIPT = SCRIPT_DIR / "hotfix_runtime.py"


def usage() -> int:
    print(
        "usage: /hotfix [start|status|close|postmortem|remind|doctor] [args] [--json] | "
        "/hotfix start --incident-id <id> --scope <patch|rollback|config_only> --impact <sev1|sev2|sev3> [--json] | "
        "/hotfix close --outcome <resolved|mitigated|rolled_back> --followup-issue <id> --deferred-validation-owner <owner> --deferred-validation-due <date> --postmortem-id <id> --risk-ack <text> [--json] | "
        "/hotfix postmortem [--write <path>] [--link-followup] [--json]"
    )
    return 2


def emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def run_runtime(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOTFIX_RUNTIME_SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def resolve_followup_url(followup_issue: str) -> tuple[str | None, str]:
    if not followup_issue:
        return None, "followup_missing"
    completed = subprocess.run(
        ["gh", "issue", "view", followup_issue, "--json", "url"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None, "followup_lookup_failed"
    try:
        payload = json.loads(completed.stdout)
    except Exception:
        return None, "followup_lookup_invalid_json"
    url = str(payload.get("url") or "").strip()
    if not url:
        return None, "followup_lookup_empty"
    return url, "followup_link_resolved"


def command_passthrough(args: list[str]) -> int:
    proc = run_runtime(args)
    if proc.stdout:
        print(proc.stdout.strip())
    elif proc.stderr:
        print(proc.stderr.strip())
    return proc.returncode


def command_remind(args: list[str]) -> int:
    as_json = "--json" in args
    if any(arg not in ("--json",) for arg in args):
        return usage()

    write_path = resolve_write_path()
    state = load_runtime(write_path)
    timeline = (
        state.get("timeline", []) if isinstance(state.get("timeline"), list) else []
    )
    closed_events = [
        e for e in timeline if isinstance(e, dict) and e.get("event") == "closed"
    ]
    latest = closed_events[-1] if closed_events else None
    details = latest.get("details", {}) if isinstance(latest, dict) else {}

    reminders = [
        "run make selftest and make install-test for deferred full validation",
        "confirm follow-up issue includes prevention and test-hardening tasks",
        "remove temporary overrides introduced during incident mitigation",
    ]

    payload = {
        "result": "PASS",
        "active": bool(state.get("active")),
        "incident_id": state.get("incident_id"),
        "followup_issue": details.get("followup_issue")
        if isinstance(details, dict)
        else None,
        "deferred_validation": details.get("deferred_validation")
        if isinstance(details, dict)
        else None,
        "reminders": reminders,
        "runtime": str(runtime_path(write_path)),
    }
    emit(payload, as_json)
    return 0


def command_doctor(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    as_json = "--json" in args
    runtime_exists = HOTFIX_RUNTIME_SCRIPT.exists()
    policy_exists = (
        SCRIPT_DIR.parent / "instructions" / "hotfix_mode_policy_contract.md"
    ).exists()
    report = {
        "result": "PASS" if runtime_exists else "FAIL",
        "runtime_exists": runtime_exists,
        "policy_exists": policy_exists,
        "warnings": [] if policy_exists else ["missing hotfix policy contract"],
        "problems": [] if runtime_exists else ["missing scripts/hotfix_runtime.py"],
        "quick_fixes": [
            "/hotfix start --incident-id INC-1 --scope patch --impact sev2 --json",
            "/hotfix status --json",
            "/hotfix remind --json",
        ],
    }
    emit(report, as_json)
    return 0 if report["result"] == "PASS" else 1


def command_postmortem(args: list[str]) -> int:
    as_json = "--json" in args
    write_path_arg: Path | None = None
    link_followup = False
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--json":
            index += 1
            continue
        if token == "--write":
            if index + 1 >= len(args):
                return usage()
            write_path_arg = Path(args[index + 1]).expanduser()
            index += 2
            continue
        if token == "--link-followup":
            link_followup = True
            index += 1
            continue
        return usage()

    write_path = resolve_write_path()
    state = load_runtime(write_path)
    timeline = (
        state.get("timeline", []) if isinstance(state.get("timeline"), list) else []
    )
    closed_events = [
        entry
        for entry in timeline
        if isinstance(entry, dict) and entry.get("event") == "closed"
    ]
    latest = closed_events[-1] if closed_events else None
    details = latest.get("details", {}) if isinstance(latest, dict) else {}
    if not isinstance(details, dict):
        details = {}

    deferred = details.get("deferred_validation")
    if not isinstance(deferred, dict):
        deferred = {}

    postmortem_id = str(details.get("postmortem_id") or "")
    followup_issue = str(details.get("followup_issue") or "")
    risk_ack = str(details.get("risk_ack") or "")
    followup_url: str | None = None
    followup_link_status = "followup_link_skipped"
    if link_followup:
        followup_url, followup_link_status = resolve_followup_url(followup_issue)

    payload = {
        "result": "PASS",
        "reason_code": "hotfix_postmortem_template",
        "incident_id": state.get("incident_id"),
        "postmortem_id": postmortem_id or None,
        "followup_issue": followup_issue or None,
        "followup_url": followup_url,
        "followup_link_status": followup_link_status,
        "risk_ack": risk_ack or None,
        "template_markdown": "\n".join(
            [
                f"# Postmortem {postmortem_id or '<postmortem-id>'}",
                "",
                "## Incident Linkback",
                f"- Incident: {state.get('incident_id') or '<incident-id>'}",
                f"- Follow-up issue: {followup_issue or '<followup-issue>'}",
                f"- Risk acknowledgement: {risk_ack or '<risk-ack>'}",
                "",
                "## Timeline",
                "- <impact start>",
                "- <mitigation>",
                "- <validation>",
                "- <closure>",
                "",
                "## Deferred Validation",
                f"- Owner: {deferred.get('owner') or '<owner>'}",
                f"- Due: {deferred.get('due') or '<date>'}",
                "",
                "## Preventive Actions",
                "- <tests/hardening/tasks>",
            ]
        ),
        "runtime": str(runtime_path(write_path)),
    }

    if write_path_arg is not None:
        write_path_arg.parent.mkdir(parents=True, exist_ok=True)
        template_body = str(payload.get("template_markdown") or "")
        write_path_arg.write_text(template_body + "\n", encoding="utf-8")
        payload["written_path"] = str(write_path_arg.resolve())

    emit(payload, as_json)
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        return command_passthrough(["status", "--json"])

    cmd, *rest = argv
    if cmd in {"help", "--help", "-h"}:
        return usage()
    if cmd == "status":
        return command_passthrough(["status", *rest])
    if cmd == "start":
        return command_passthrough(["start", *rest])
    if cmd == "close":
        return command_passthrough(["close", *rest])
    if cmd == "doctor":
        return command_doctor(rest)
    if cmd == "postmortem":
        return command_postmortem(rest)
    if cmd == "remind":
        return command_remind(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
