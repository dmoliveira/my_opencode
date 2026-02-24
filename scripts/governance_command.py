#!/usr/bin/env python3

from __future__ import annotations

import json
import sys

from governance_policy import (  # type: ignore
    DEFAULT_POLICY_PATH,
    authorize_operation,
    load_policy,
    now_iso,
    revoke_operation,
    save_policy,
)


def usage() -> int:
    print(
        "usage: /governance status [--json] | /governance profile <off|balanced|strict> [--json] | "
        "/governance authorize <operation|*> [--ttl-minutes <n>] [--json] | /governance revoke <operation|*> [--json] | /governance doctor [--json]"
    )
    return 2


def emit(payload: dict, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        if payload.get("result") != "PASS":
            print(f"error: {payload.get('error', 'governance command failed')}")
            return 1
        print(f"result: {payload.get('result')}")
        if payload.get("profile"):
            print(f"profile: {payload.get('profile')}")
    return 0 if payload.get("result") == "PASS" else 1


def cmd_status(argv: list[str]) -> int:
    as_json = "--json" in argv
    policy = load_policy(DEFAULT_POLICY_PATH)
    return emit(
        {
            "result": "PASS",
            "command": "status",
            "profile": policy.get("profile", "balanced"),
            "grants": policy.get("grants", {}),
            "path": str(DEFAULT_POLICY_PATH),
        },
        as_json,
    )


def cmd_profile(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if not argv:
        return usage()
    profile = argv[0].strip()
    if profile not in {"off", "balanced", "strict"}:
        return usage()
    policy = load_policy(DEFAULT_POLICY_PATH)
    policy["profile"] = profile
    policy["updated_at"] = now_iso()
    save_policy(policy, DEFAULT_POLICY_PATH)
    return emit(
        {
            "result": "PASS",
            "command": "profile",
            "profile": profile,
            "path": str(DEFAULT_POLICY_PATH),
        },
        as_json,
    )


def cmd_authorize(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if not argv:
        return usage()
    operation = argv.pop(0)
    ttl = 30
    if "--ttl-minutes" in argv:
        idx = argv.index("--ttl-minutes")
        if idx + 1 >= len(argv):
            return usage()
        try:
            ttl = max(1, int(argv[idx + 1]))
        except ValueError:
            return usage()
    grant = authorize_operation(operation, ttl_minutes=ttl, path=DEFAULT_POLICY_PATH)
    return emit(
        {
            "result": "PASS",
            "command": "authorize",
            "grant": grant,
            "profile": load_policy(DEFAULT_POLICY_PATH).get("profile", "balanced"),
        },
        as_json,
    )


def cmd_revoke(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if not argv:
        return usage()
    operation = argv[0]
    existed = revoke_operation(operation, path=DEFAULT_POLICY_PATH)
    return emit(
        {
            "result": "PASS",
            "command": "revoke",
            "operation": operation,
            "removed": existed,
        },
        as_json,
    )


def cmd_doctor(argv: list[str]) -> int:
    as_json = "--json" in argv
    policy = load_policy(DEFAULT_POLICY_PATH)
    warnings: list[str] = []
    if policy.get("profile") == "strict" and not policy.get("grants"):
        warnings.append("strict profile active with no grants")
    return emit(
        {
            "result": "PASS",
            "command": "doctor",
            "profile": policy.get("profile", "balanced"),
            "grants": policy.get("grants", {}),
            "warnings": warnings,
            "quick_fixes": [
                "/governance profile balanced",
                "/governance authorize workflow.execute --ttl-minutes 30",
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
    if command == "status":
        return cmd_status(rest)
    if command == "profile":
        return cmd_profile(rest)
    if command == "authorize":
        return cmd_authorize(rest)
    if command == "revoke":
        return cmd_revoke(rest)
    if command == "doctor":
        return cmd_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
