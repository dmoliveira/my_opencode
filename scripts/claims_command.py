#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


DEFAULT_STATE_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_CLAIMS_PATH", "~/.config/opencode/my_opencode/runtime/claims.json"
    )
).expanduser()


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def usage() -> int:
    print(
        "usage: /claims claim <issue_id> --by <human:name|agent:type> [--json] | "
        "/claims handoff <issue_id> --to <human:name|agent:type> [--json] | "
        "/claims accept-handoff <issue_id> [--json] | /claims reject-handoff <issue_id> [--reason <text>] [--json] | "
        "/claims release <issue_id> [--json] | /claims status [--id <issue_id>] [--json] | "
        "/claims list [--json] | /claims expire-stale [--hours <n>] [--apply] [--json] | /claims doctor [--json]"
    )
    return 2


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "claims": {}}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {"version": 1, "claims": {}}
    claims = raw.get("claims") if isinstance(raw.get("claims"), dict) else {}
    return {"version": int(raw.get("version", 1) or 1), "claims": claims}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def claims_map(state: dict[str, Any]) -> dict[str, Any]:
    raw_claims = state.get("claims")
    if isinstance(raw_claims, dict):
        return raw_claims
    state["claims"] = {}
    return state["claims"]


def parse_flag_value(argv: list[str], flag: str) -> str | None:
    if flag not in argv:
        return None
    idx = argv.index(flag)
    if idx + 1 >= len(argv):
        raise ValueError(f"{flag} requires a value")
    value = argv[idx + 1]
    del argv[idx : idx + 2]
    return value


def emit(payload: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        if payload.get("result") != "PASS":
            print(f"error: {payload.get('error', 'claims command failed')}")
            return 1
        cmd = payload.get("command")
        if cmd == "list":
            print(f"count: {payload.get('count', 0)}")
            for row in payload.get("claims", []):
                print(
                    f"- {row.get('issue_id')} | status={row.get('status')} | owner={row.get('owner')}"
                )
        elif cmd == "doctor":
            print(f"result: {payload.get('result')}")
            for warning in payload.get("warnings", []):
                print(f"- warning: {warning}")
        else:
            print(f"result: {payload.get('result')}")
            if payload.get("issue_id"):
                print(f"issue_id: {payload.get('issue_id')}")
            if payload.get("status"):
                print(f"status: {payload.get('status')}")
    return 0 if payload.get("result") == "PASS" else 1


def normalize_claimant(raw: str) -> str:
    text = raw.strip()
    if text.startswith("human:") or text.startswith("agent:"):
        return text
    return f"human:{text}"


def stale_claims(state: dict[str, Any], stale_hours: int = 48) -> list[str]:
    claims = claims_map(state)
    cutoff = datetime.now(UTC) - timedelta(hours=stale_hours)
    stale: list[str] = []
    for issue_id, item in claims.items():
        if not isinstance(item, dict):
            continue
        updated = str(item.get("updated_at") or "")
        if not updated.endswith("Z"):
            continue
        try:
            when = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when < cutoff and str(item.get("status") or "") in {
            "active",
            "paused",
            "blocked",
        }:
            stale.append(str(issue_id))
    return stale


def cmd_claim(argv: list[str], path: Path) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if not argv:
        return usage()
    issue_id = argv.pop(0)
    try:
        owner = normalize_claimant(parse_flag_value(argv, "--by") or "")
    except ValueError:
        return usage()
    if not owner:
        return usage()
    state = load_state(path)
    claims = claims_map(state)
    current = claims.get(issue_id)
    if isinstance(current, dict) and str(current.get("status")) == "active":
        return emit(
            {
                "result": "FAIL",
                "command": "claim",
                "error": f"issue already claimed by {current.get('owner')}",
                "issue_id": issue_id,
                "status": current.get("status"),
            },
            as_json,
        )
    claims[issue_id] = {
        "issue_id": issue_id,
        "owner": owner,
        "status": "active",
        "claimed_at": now_iso(),
        "updated_at": now_iso(),
        "handoff_to": None,
    }
    save_state(path, state)
    return emit({"result": "PASS", "command": "claim", **claims[issue_id]}, as_json)


def cmd_handoff(argv: list[str], path: Path) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if not argv:
        return usage()
    issue_id = argv.pop(0)
    try:
        to_owner = normalize_claimant(parse_flag_value(argv, "--to") or "")
    except ValueError:
        return usage()
    if not to_owner:
        return usage()
    state = load_state(path)
    claims = claims_map(state)
    item = claims.get(issue_id)
    if not isinstance(item, dict):
        return emit(
            {
                "result": "FAIL",
                "command": "handoff",
                "error": f"issue not claimed: {issue_id}",
            },
            as_json,
        )
    item["handoff_to"] = to_owner
    item["status"] = "handoff-pending"
    item["updated_at"] = now_iso()
    save_state(path, state)
    return emit({"result": "PASS", "command": "handoff", **item}, as_json)


def cmd_release(argv: list[str], path: Path) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if not argv:
        return usage()
    issue_id = argv[0]
    state = load_state(path)
    claims = claims_map(state)
    item = claims.get(issue_id)
    if not isinstance(item, dict):
        return emit(
            {
                "result": "FAIL",
                "command": "release",
                "error": f"issue not found: {issue_id}",
            },
            as_json,
        )
    item["status"] = "completed"
    item["updated_at"] = now_iso()
    save_state(path, state)
    return emit({"result": "PASS", "command": "release", **item}, as_json)


def cmd_accept_handoff(argv: list[str], path: Path) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if not argv:
        return usage()
    issue_id = argv[0]
    state = load_state(path)
    claims = claims_map(state)
    item = claims.get(issue_id)
    if not isinstance(item, dict):
        return emit(
            {
                "result": "FAIL",
                "command": "accept-handoff",
                "error": f"issue not found: {issue_id}",
            },
            as_json,
        )
    handoff_to = str(item.get("handoff_to") or "").strip()
    if str(item.get("status") or "") != "handoff-pending" or not handoff_to:
        return emit(
            {
                "result": "FAIL",
                "command": "accept-handoff",
                "error": "no pending handoff to accept",
                "issue_id": issue_id,
                "status": item.get("status"),
            },
            as_json,
        )
    item["owner"] = handoff_to
    item["handoff_to"] = None
    item["status"] = "active"
    item["updated_at"] = now_iso()
    save_state(path, state)
    return emit({"result": "PASS", "command": "accept-handoff", **item}, as_json)


def cmd_reject_handoff(argv: list[str], path: Path) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if not argv:
        return usage()
    issue_id = argv.pop(0)
    reason = "handoff rejected"
    try:
        reason_arg = parse_flag_value(argv, "--reason")
    except ValueError:
        return usage()
    if reason_arg:
        reason = reason_arg
    state = load_state(path)
    claims = claims_map(state)
    item = claims.get(issue_id)
    if not isinstance(item, dict):
        return emit(
            {
                "result": "FAIL",
                "command": "reject-handoff",
                "error": f"issue not found: {issue_id}",
            },
            as_json,
        )
    if str(item.get("status") or "") != "handoff-pending":
        return emit(
            {
                "result": "FAIL",
                "command": "reject-handoff",
                "error": "no pending handoff to reject",
                "issue_id": issue_id,
                "status": item.get("status"),
            },
            as_json,
        )
    item["status"] = "active"
    item["handoff_to"] = None
    item["handoff_rejected_reason"] = reason
    item["updated_at"] = now_iso()
    save_state(path, state)
    return emit({"result": "PASS", "command": "reject-handoff", **item}, as_json)


def cmd_expire_stale(argv: list[str], path: Path) -> int:
    as_json = "--json" in argv
    apply_mode = "--apply" in argv
    argv = [a for a in argv if a not in {"--json", "--apply"}]
    stale_hours = 48
    try:
        hours_arg = parse_flag_value(argv, "--hours")
    except ValueError:
        return usage()
    if hours_arg is not None:
        try:
            stale_hours = max(1, int(hours_arg))
        except ValueError:
            return usage()

    state = load_state(path)
    stale = stale_claims(state, stale_hours=stale_hours)
    updated: list[str] = []
    if apply_mode and stale:
        claims = claims_map(state)
        for issue_id in stale:
            item = claims.get(issue_id)
            if not isinstance(item, dict):
                continue
            item["status"] = "expired"
            item["updated_at"] = now_iso()
            updated.append(issue_id)
        save_state(path, state)

    return emit(
        {
            "result": "PASS",
            "command": "expire-stale",
            "hours": stale_hours,
            "apply": apply_mode,
            "stale": stale,
            "updated": updated,
            "count": len(stale),
        },
        as_json,
    )


def cmd_status(argv: list[str], path: Path) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    issue_id = None
    try:
        issue_id = parse_flag_value(argv, "--id")
    except ValueError:
        return usage()
    state = load_state(path)
    claims = claims_map(state)
    if issue_id:
        item = claims.get(issue_id)
        if not isinstance(item, dict):
            return emit(
                {
                    "result": "FAIL",
                    "command": "status",
                    "error": f"issue not found: {issue_id}",
                },
                as_json,
            )
        return emit({"result": "PASS", "command": "status", **item}, as_json)
    active = sum(
        1
        for v in claims.values()
        if isinstance(v, dict) and v.get("status") == "active"
    )
    pending = sum(
        1
        for v in claims.values()
        if isinstance(v, dict) and v.get("status") == "handoff-pending"
    )
    return emit(
        {
            "result": "PASS",
            "command": "status",
            "count": len(claims),
            "active": active,
            "handoff_pending": pending,
            "stale": stale_claims(state),
        },
        as_json,
    )


def cmd_list(argv: list[str], path: Path) -> int:
    as_json = "--json" in argv
    state = load_state(path)
    claims = claims_map(state)
    rows: list[dict[str, Any]] = []
    for item in claims.values():
        if isinstance(item, dict):
            rows.append(item)
    rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    return emit(
        {"result": "PASS", "command": "list", "count": len(rows), "claims": rows},
        as_json,
    )


def cmd_doctor(argv: list[str], path: Path) -> int:
    as_json = "--json" in argv
    state = load_state(path)
    stale = stale_claims(state)
    warnings: list[str] = []
    if stale:
        warnings.append("stale claims detected; use /claims handoff or /claims release")
    return emit(
        {
            "result": "PASS",
            "command": "doctor",
            "path": str(path),
            "stale": stale,
            "warnings": warnings,
            "quick_fixes": [
                "/claims list --json",
                "/claims status --json",
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
    if command == "claim":
        return cmd_claim(rest, DEFAULT_STATE_PATH)
    if command == "handoff":
        return cmd_handoff(rest, DEFAULT_STATE_PATH)
    if command == "accept-handoff":
        return cmd_accept_handoff(rest, DEFAULT_STATE_PATH)
    if command == "reject-handoff":
        return cmd_reject_handoff(rest, DEFAULT_STATE_PATH)
    if command == "release":
        return cmd_release(rest, DEFAULT_STATE_PATH)
    if command == "expire-stale":
        return cmd_expire_stale(rest, DEFAULT_STATE_PATH)
    if command == "status":
        return cmd_status(rest, DEFAULT_STATE_PATH)
    if command == "list":
        return cmd_list(rest, DEFAULT_STATE_PATH)
    if command == "doctor":
        return cmd_doctor(rest, DEFAULT_STATE_PATH)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
