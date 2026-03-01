#!/usr/bin/env python3

from __future__ import annotations

import os

from flow_reason_codes import (  # type: ignore
    REVIEWER_POLICY_CONFLICT,
    REVIEWER_POLICY_OK,
)


def normalize_reviewers(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip().lstrip("@")
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def parse_reviewer_flags(args: list[str], flag: str) -> list[str]:
    values: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token != flag:
            index += 1
            continue
        if index + 1 >= len(args):
            break
        values.append(args[index + 1])
        del args[index : index + 2]
    return normalize_reviewers(values)


def env_reviewer_values(env_key: str) -> list[str]:
    raw = os.environ.get(env_key, "")
    if not raw:
        return []
    return normalize_reviewers(raw.split(","))


def resolve_reviewer_policy(
    cli_allow: list[str],
    cli_deny: list[str],
    env_allow: list[str],
    env_deny: list[str],
) -> tuple[list[str], list[str], str]:
    allow = cli_allow or env_allow
    deny = cli_deny + [
        item
        for item in env_deny
        if item.lower() not in {value.lower() for value in cli_deny}
    ]
    source = (
        "cli"
        if cli_allow or cli_deny
        else "env"
        if env_allow or env_deny
        else "default"
    )
    return allow, deny, source


def apply_reviewer_policy(
    reviewers: list[str], *, allow_list: list[str], deny_list: list[str]
) -> tuple[list[str], list[str]]:
    allow_set = {item.lower() for item in allow_list}
    deny_set = {item.lower() for item in deny_list}
    filtered: list[str] = []
    filtered_out: list[str] = []
    for reviewer in reviewers:
        key = reviewer.lower()
        if key in deny_set:
            filtered_out.append(reviewer)
            continue
        if allow_set and key not in allow_set:
            filtered_out.append(reviewer)
            continue
        filtered.append(reviewer)
    return filtered, filtered_out


def diagnose_reviewer_policy(
    *, allow_list: list[str], deny_list: list[str], source: str
) -> dict[str, object]:
    allow_set = {item.lower() for item in allow_list}
    deny_set = {item.lower() for item in deny_list}
    overlap = sorted(allow_set & deny_set)
    reason_codes = [REVIEWER_POLICY_OK]
    warnings: list[str] = []
    remediation: list[str] = []
    status = "pass"
    if overlap:
        status = "warn"
        reason_codes = [REVIEWER_POLICY_CONFLICT]
        overlap_list = ", ".join(overlap)
        warnings.append(
            f"reviewers present in both allow and deny lists: {overlap_list}; deny takes precedence"
        )
        remediation.append("remove overlap between allow and deny reviewer policies")
    if not allow_list and not deny_list:
        reason_codes.append("reviewer_policy_default")

    return {
        "status": status,
        "source": source,
        "allow_reviewers": allow_list,
        "deny_reviewers": deny_list,
        "overlap_reviewers": overlap,
        "reason_codes": reason_codes,
        "warnings": warnings,
        "remediation": remediation,
    }
