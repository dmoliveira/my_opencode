#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = REPO_ROOT / "agent" / "specs"
OUTPUT_DIR = REPO_ROOT / "agent"

TOKEN_PATTERN = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


def _load_json(path: Path) -> dict[str, Any]:
    """Load a UTF-8 JSON file into a dictionary."""
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_tools(name: str, tools: Any) -> dict[str, bool]:
    """Validate and normalize tool permission mapping for an agent spec."""
    if not isinstance(tools, dict):
        raise ValueError(f"{name}: tools must be an object")
    normalized: dict[str, bool] = {}
    for key, value in tools.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{name}: invalid tool key")
        if not isinstance(value, bool):
            raise ValueError(f"{name}: tool '{key}' must be boolean")
        normalized[key] = value
    return normalized


def _collect_vars(spec: dict[str, Any], profile: str) -> dict[str, str]:
    """Merge default and profile-specific template variables."""
    default_vars_any = spec.get("default_vars", {})
    if not isinstance(default_vars_any, dict):
        raise ValueError(f"{spec.get('name')}: default_vars must be an object")
    vars_map: dict[str, str] = {str(k): str(v) for k, v in default_vars_any.items()}

    profiles_any = spec.get("profiles", {})
    if not isinstance(profiles_any, dict):
        raise ValueError(f"{spec.get('name')}: profiles must be an object")
    if profile in profiles_any:
        profile_vars_any = profiles_any.get(profile)
        if not isinstance(profile_vars_any, dict):
            raise ValueError(
                f"{spec.get('name')}: profile '{profile}' must map to object"
            )
        for key, value in profile_vars_any.items():
            vars_map[str(key)] = str(value)
    return vars_map


def _render_template(template: str, vars_map: dict[str, str], *, name: str) -> str:
    """Render template tokens and fail on unresolved placeholders."""
    missing: set[str] = set()

    def repl(match: re.Match[str]) -> str:
        token = match.group(1)
        if token not in vars_map:
            missing.add(token)
            return match.group(0)
        return vars_map[token]

    rendered = TOKEN_PATTERN.sub(repl, template)
    if missing:
        missing_tokens = ", ".join(sorted(missing))
        raise ValueError(f"{name}: missing template vars: {missing_tokens}")
    return rendered


def _render_agent(spec: dict[str, Any], profile: str) -> tuple[str, str]:
    """Render a single agent markdown document from one JSON spec."""
    name = str(spec.get("name") or "").strip()
    if not name:
        raise ValueError("agent spec missing name")
    mode = str(spec.get("mode") or "").strip()
    if mode not in {"primary", "subagent"}:
        raise ValueError(f"{name}: mode must be 'primary' or 'subagent'")
    description_template = str(spec.get("description_template") or "").strip()
    if not description_template:
        raise ValueError(f"{name}: description_template is required")
    body_template = str(spec.get("body_template") or "")
    if not body_template.strip():
        raise ValueError(f"{name}: body_template is required")

    tools = _validate_tools(name, spec.get("tools"))
    vars_map = _collect_vars(spec, profile)
    description = _render_template(description_template, vars_map, name=name)
    body = _render_template(body_template, vars_map, name=name)

    header_lines = [
        "---",
        "description: >-",
        f"  {description}",
        f"mode: {mode}",
        "tools:",
    ]
    for tool_name, enabled in tools.items():
        header_lines.append(f"  {tool_name}: {'true' if enabled else 'false'}")
    header_lines.append("---")
    header_lines.append(body.rstrip())
    content = "\n".join(header_lines).rstrip() + "\n"
    return name, content


def _spec_paths() -> list[Path]:
    """Return all available agent spec file paths."""
    if not SPEC_DIR.exists():
        raise ValueError(f"missing spec directory: {SPEC_DIR}")
    return sorted(SPEC_DIR.glob("*.json"))


def build_agents(profile: str, *, check_only: bool = False) -> int:
    """Build or verify generated agent markdown files for a profile."""
    paths = _spec_paths()
    if not paths:
        raise ValueError("no agent specs found")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    changed = 0
    for path in paths:
        spec = _load_json(path)
        name, content = _render_agent(spec, profile)
        out_path = OUTPUT_DIR / f"{name}.md"
        current = out_path.read_text(encoding="utf-8") if out_path.exists() else None
        if current != content:
            changed += 1
            if not check_only:
                out_path.write_text(content, encoding="utf-8")
    if check_only:
        if changed:
            print(f"agent build check: FAIL ({changed} file(s) out of date)")
            return 1
        print("agent build check: PASS")
        return 0

    print(f"agent build: wrote/updated {changed} file(s)")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command line arguments for agent generation."""
    parser = argparse.ArgumentParser(
        description="Build markdown agents from JSON specs"
    )
    parser.add_argument("--profile", default="balanced", help="generation profile")
    parser.add_argument(
        "--check",
        action="store_true",
        help="check that generated agents are up-to-date without writing files",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Entrypoint for agent generation/check workflow."""
    args = parse_args(argv)
    return build_agents(args.profile, check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
