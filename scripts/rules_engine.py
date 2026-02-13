#!/usr/bin/env python3

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
from typing import Any


def _parse_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        return int(value)
    except ValueError:
        return value


def parse_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, markdown

    frontmatter_lines: list[str] = []
    end_index = -1
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_index = idx
            break
        frontmatter_lines.append(lines[idx])

    if end_index == -1:
        return {}, markdown

    payload: dict[str, Any] = {}
    current_key: str | None = None
    for raw in frontmatter_lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("- ") and current_key:
            item = line.lstrip()[2:].strip()
            payload.setdefault(current_key, [])
            if isinstance(payload[current_key], list):
                payload[current_key].append(_parse_scalar(item))
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current_key = key.strip()
        value = value.strip()
        if not value:
            payload[current_key] = []
            continue
        payload[current_key] = _parse_scalar(value)

    body = "\n".join(lines[end_index + 1 :]).lstrip("\n")
    return payload, body


def normalize_rule_id(raw: str | None, fallback_stem: str) -> str:
    value = (raw or "").strip().lower()
    if value:
        return value
    return fallback_stem.strip().lower().replace(" ", "-")


def validate_rule(rule: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if (
        not isinstance(rule.get("description"), str)
        or not str(rule["description"]).strip()
    ):
        problems.append("description is required")
    priority = rule.get("priority")
    if not isinstance(priority, int) or priority < 0 or priority > 100:
        problems.append("priority must be an integer between 0 and 100")
    if "alwaysApply" in rule and not isinstance(rule.get("alwaysApply"), bool):
        problems.append("alwaysApply must be a boolean")
    if "globs" in rule:
        globs = rule.get("globs")
        if not isinstance(globs, list) or not all(
            isinstance(item, str) for item in globs
        ):
            problems.append("globs must be a list of strings")
    return problems


def discover_rules(
    project_root: Path, home: Path | None = None
) -> list[dict[str, Any]]:
    base_home = home or Path.home()
    user_root = base_home / ".config" / "opencode" / "rules"
    project_root_rules = project_root / ".opencode" / "rules"

    roots = [("user", user_root), ("project", project_root_rules)]
    discovered: list[dict[str, Any]] = []
    for scope, root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            frontmatter, body = parse_frontmatter(text)
            rule = dict(frontmatter)
            rule["id"] = normalize_rule_id(
                str(frontmatter.get("id"))
                if frontmatter.get("id") is not None
                else None,
                path.stem,
            )
            rule["scope"] = scope
            rule["path"] = str(path)
            rule["body"] = body
            rule["problems"] = validate_rule(rule)
            discovered.append(rule)
    return discovered


def rule_applies(rule: dict[str, Any], target_path: str) -> bool:
    if rule.get("problems"):
        return False
    if rule.get("alwaysApply") is True:
        return True
    globs = rule.get("globs")
    if isinstance(globs, list):
        return any(
            isinstance(pattern, str) and fnmatch(target_path, pattern)
            for pattern in globs
        )
    return False


def resolve_effective_rules(
    rules: list[dict[str, Any]], target_path: str
) -> dict[str, Any]:
    applicable = [rule for rule in rules if rule_applies(rule, target_path)]
    sorted_rules = sorted(
        applicable,
        key=lambda rule: (
            -int(rule.get("priority", 0)),
            0 if rule.get("scope") == "project" else 1,
            str(rule.get("id", "")),
        ),
    )

    effective: list[dict[str, Any]] = []
    conflicts: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for rule in sorted_rules:
        rule_id = str(rule.get("id", ""))
        if rule_id in seen_ids:
            conflicts.append(
                {
                    "id": rule_id,
                    "path": str(rule.get("path", "")),
                    "reason": "duplicate_rule_id_overridden",
                }
            )
            continue
        seen_ids.add(rule_id)
        effective.append(rule)

    return {
        "target_path": target_path,
        "effective_rules": effective,
        "conflicts": conflicts,
        "discovered_count": len(rules),
        "applicable_count": len(applicable),
    }
