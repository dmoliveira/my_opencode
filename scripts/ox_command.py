#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


NAMESPACE = "ox"
VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[1]

ECOSYSTEM_LINKS: dict[str, dict[str, str]] = {
    "my_opencode": {
        "label": "my_opencode runtime",
        "url": "https://github.com/dmoliveira/my_opencode",
        "notes": "OpenCode runtime, slash-command surface, automation docs, and delivery workflows.",
    },
    "agents-md": {
        "label": "agents.md playbook",
        "url": "https://github.com/dmoliveira/agents.md",
        "notes": "Reusable delivery contract, validation policy, and shareable orchestration guidance.",
    },
    "top-uni": {
        "label": "Top Uni",
        "url": "https://dmoliveira.github.io/top-uni/",
        "notes": "Reference public site for browser-first UX audits and polish loops.",
    },
    "my-cv-public": {
        "label": "my-cv-public",
        "url": "https://dmoliveira.github.io/my-cv-public/cv/human/",
        "notes": "Linked public profile surface used by the Top Uni project ecosystem.",
    },
}

COMMAND_SPECS: dict[str, dict[str, Any]] = {
    "ux": {
        "slash": "/ox-ux",
        "title": "Browser UX audit and polish",
        "summary": "Use Playwright/browser tooling to inspect the full experience, capture UI/UX friction, and improve the product with visible polish.",
        "agent": "orchestrator",
        "mcp_profiles": ["playwright", "web"],
        "startup": [
            "/browser ensure --json",
            "/mcp profile playwright",
            "/browser doctor --json",
        ],
        "workflow": [
            "Run browser preflight first so Playwright/provider friction is surfaced as exact remediation instead of vague 'not installed' failures.",
            "Inspect the target application section by section with browser automation or screenshots before editing.",
            "Record concrete UX/UI problems with evidence, then prioritize the highest-friction issues first.",
            "Implement polish that improves clarity, hierarchy, spacing, copy, responsiveness, states, and overall trust.",
            "Re-check the touched flows after changes and summarize what improved plus anything still out of scope.",
        ],
        "acceptance": [
            "Every audited section has a short finding or an explicit 'looks good' note.",
            "The final changes improve visual consistency or interaction quality, not just code style.",
            "Responsive, loading, empty, and error-state regressions are considered where relevant.",
        ],
        "defaults": {
            "goal": "Audit the experience end to end, note weak UI/UX, and implement polish that improves clarity, flow, and trust.",
            "scope": "all primary user-facing sections",
            "focus": ["hierarchy", "copy", "spacing", "responsiveness", "states"],
            "repo": "top-uni",
            "target": "https://dmoliveira.github.io/top-uni/",
        },
    },
    "design": {
        "slash": "/ox-design",
        "title": "Design concept and asset planning",
        "summary": "Shape UX/UI directions, repo-native design artifacts, and image-generation-ready prompts before or alongside implementation.",
        "agent": "orchestrator",
        "mcp_profiles": ["playwright", "web"],
        "startup": [
            "/browser ensure --json",
            "/mcp profile playwright",
            "/image doctor --json",
        ],
        "workflow": [
            "Inspect the current product, screenshots, or brief first so the design work stays grounded in a real flow or concrete concept target.",
            "Produce a small set of strong visual directions covering hierarchy, layout, iconography, palette, and typography instead of broad speculative branching.",
            "Translate the chosen direction into reusable prompt/spec output that can drive `/image prompt` or `/image generate` later.",
            "Store or reference design artifacts under `artifacts/design/` so they are repo-native, reviewable, and committable when relevant.",
            "Explicitly separate concept generation from browser validation of the implemented UI so synthetic design work does not get mistaken for product truth.",
        ],
        "acceptance": [
            "The output includes concrete design directions or findings tied to the requested flow, screen, or component family.",
            "At least one prompt/spec is ready for later image generation or human handoff without another planning pass.",
            "Artifact paths or naming guidance under `artifacts/design/` are explicit when visuals are in scope.",
        ],
        "defaults": {
            "goal": "Explore or refine a strong UX/UI direction, then prepare prompt-ready design artifacts that can be saved under artifacts/design/.",
            "scope": "one focused product flow, screen, or component family",
            "focus": ["wireframes", "icons", "palette", "layout", "visual hierarchy"],
            "repo": "my_opencode",
        },
    },
    "review": {
        "slash": "/ox-review",
        "title": "End-to-end code review and improvement",
        "summary": "Review the selected code path or latest work end to end, then refine rough edges and improve correctness, consistency, maintainability, tests, docs, and ship readiness in one bounded pass.",
        "agent": "orchestrator",
        "mcp_profiles": ["research"],
        "startup": ["git status --short", "/review local --json"],
        "workflow": [
            "Map the relevant files and behavior before changing anything.",
            "Identify correctness, consistency, maintainability, test, docs, and migration risks, especially after a first implementation pass.",
            "Do a second-pass refinement over the latest work to polish rough edges, resolve inconsistencies, and tighten the solution rather than stopping at 'good enough'.",
            "Implement pragmatic improvements end to end rather than isolated micro-edits.",
            "Validate the touched area and summarize the main fixes plus residual risk.",
        ],
        "acceptance": [
            "The result is cleaner or safer in behavior, not just restyled.",
            "The pass catches and improves at least one meaningful weakness, rough edge, inconsistency, or risk when one exists.",
            "Relevant tests/docs/validation notes are updated or explicitly called out.",
            "The final summary explains why the branch is in a better state than before.",
        ],
        "defaults": {
            "goal": "Review the latest work end to end, refine rough edges pragmatically, detect inconsistencies or missed risks, and leave the result cleaner, safer, and easier to maintain.",
            "scope": "current branch diff, latest work, or selected feature area",
            "focus": [
                "correctness",
                "consistency",
                "maintainability",
                "polish",
                "tests",
                "docs",
                "ship-readiness",
            ],
            "repo": "my_opencode",
        },
    },
    "ship": {
        "slash": "/ox-ship",
        "title": "Ship-readiness pass",
        "summary": "Prepare the current branch for delivery with a compact validation, review, and PR-readiness loop.",
        "agent": "orchestrator",
        "mcp_profiles": [],
        "startup": ["git status --short", "git diff --stat", "/ship doctor --json"],
        "workflow": [
            "Review the current branch diff, commit story, and validation surface before shipping.",
            "Run the fastest high-signal checks first, then broaden only if risk or failures require it.",
            "Fix clear blockers directly when safe; otherwise surface exact ship blockers with evidence.",
            "Produce a concise PR-ready summary with validation evidence and remaining risk.",
        ],
        "acceptance": [
            "There is a clear ship or no-ship recommendation.",
            "Validation evidence is explicit and tied to the current diff.",
            "PR summary material is ready or nearly ready to paste.",
        ],
        "defaults": {
            "goal": "Validate this branch, fix obvious blockers when safe, and leave it PR-ready with clear evidence.",
            "scope": "current branch diff",
            "focus": ["validation", "risk", "pr-summary"],
            "repo": "my_opencode",
        },
    },
    "start": {
        "slash": "/ox-start",
        "title": "Task bootstrap",
        "summary": "Turn a loose request into a ready-to-execute task frame with worktree, scope, and validation cues.",
        "agent": "orchestrator",
        "mcp_profiles": [],
        "startup": ["git fetch --all --prune", "/delivery status --json"],
        "workflow": [
            "Clarify the objective, scope, expected output, and validation bar.",
            "Check current remote/issue/PR state before implementation.",
            "Move work into a dedicated worktree branch and preserve the main checkout as read-only.",
            "State the first implementation slice instead of stopping at planning.",
        ],
        "acceptance": [
            "Scope, branch/worktree posture, and first validation target are explicit.",
            "The task is ready to execute without another planning round.",
        ],
        "defaults": {
            "goal": "Bootstrap this task cleanly so execution can start immediately with the right branch, scope, and validation cues.",
            "scope": "one focused issue or objective",
            "focus": ["scope", "worktree", "validation"],
            "repo": "my_opencode",
        },
    },
    "wrap": {
        "slash": "/ox-wrap",
        "title": "Session wrap-up and handoff",
        "summary": "Close a work session cleanly with digest, handoff notes, and next actions.",
        "agent": "build",
        "mcp_profiles": [],
        "startup": ["/digest run --reason manual", "/session handoff --json"],
        "workflow": [
            "Capture a concise summary of what changed and what remains.",
            "Run digest/handoff flows if useful so the next session can resume quickly.",
            "Highlight blockers, validation status, and the single best next slice.",
        ],
        "acceptance": [
            "The next operator/agent can continue without reconstructing context.",
            "Validation state and outstanding work are explicit.",
        ],
        "defaults": {
            "goal": "Wrap this session with a clean summary, continuation cues, and explicit validation status.",
            "scope": "current session",
            "focus": ["digest", "handoff", "next-actions"],
            "repo": "my_opencode",
        },
    },
    "debug": {
        "slash": "/ox-debug",
        "title": "Debug and fix loop",
        "summary": "Reproduce an issue, isolate the likely root cause, implement a fix, and prove it with regression coverage or explicit evidence.",
        "agent": "orchestrator",
        "mcp_profiles": [],
        "startup": ["/doctor run", "git status --short"],
        "workflow": [
            "Reproduce the failure or define the exact missing behavior.",
            "Narrow to the smallest credible root-cause area before editing.",
            "Implement the fix plus a regression guard where practical.",
            "Re-run the failing path and document why the issue is resolved.",
        ],
        "acceptance": [
            "The bug is reproduced or tightly evidenced before the fix.",
            "Post-fix validation directly exercises the original failure mode.",
        ],
        "defaults": {
            "goal": "Debug this issue end to end, fix the root cause, and leave behind regression evidence.",
            "scope": "reported bug or failing path",
            "focus": ["reproduction", "root-cause", "regression"],
            "repo": "my_opencode",
        },
    },
    "refactor": {
        "slash": "/ox-refactor",
        "title": "Safe refactor pass",
        "summary": "Refactor with a safety-first workflow that keeps behavior stable while improving structure and readability.",
        "agent": "orchestrator",
        "mcp_profiles": [],
        "startup": ["/refactor-lite <target> --dry-run --json", "git status --short"],
        "workflow": [
            "Map the current behavior and identify the boundaries that must remain stable.",
            "Reduce scope until the refactor is safe, reviewable, and testable.",
            "Apply semantically structured improvements instead of broad churn.",
            "Validate unchanged behavior after the refactor and call out any intentional deltas.",
        ],
        "acceptance": [
            "Behavior stays stable unless an explicit improvement is part of scope.",
            "The final diff is smaller and easier to reason about than the starting point.",
        ],
        "defaults": {
            "goal": "Run a safe, bounded refactor that improves structure without introducing behavior drift.",
            "scope": "selected module or path",
            "focus": ["safety", "structure", "readability"],
            "repo": "my_opencode",
        },
    },
}


def usage() -> int:
    print(
        "usage: /ox [list|doctor|ecosystem] [--json] | "
        "/ox-ux [--target <url>] [--scope <text>] [--focus <csv>] [--sections <csv>] [--repo <name>] [--goal <text>] [--notes <text>] [--json] | "
        "/ox-design [--target <url|path>] [--scope <text>] [--focus <csv>] [--sections <csv>] [--repo <name>] [--goal <text>] [--notes <text>] [--json] | "
        "/ox-review [--scope <text>] [--focus <csv>] [--repo <name>] [--goal <text>] [--notes <text>] [--json] | "
        "/ox-ship [--scope <text>] [--base <ref>] [--head <ref>] [--goal <text>] [--notes <text>] [--json] | "
        "/ox-start [--issue <id>] [--scope <text>] [--repo <name>] [--goal <text>] [--notes <text>] [--json] | "
        "/ox-wrap [--scope <text>] [--repo <name>] [--goal <text>] [--notes <text>] [--json] | "
        "/ox-debug [--target <bug>] [--scope <text>] [--repo <name>] [--goal <text>] [--notes <text>] [--json] | "
        "/ox-refactor [--scope <text>] [--focus <csv>] [--repo <name>] [--goal <text>] [--notes <text>] [--json]"
    )
    return 2


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _repo_root() -> str:
    return str(REPO_ROOT)


def _parse_common_args(argv: list[str]) -> dict[str, Any] | None:
    parsed: dict[str, Any] = {
        "json": False,
        "goal": None,
        "scope": None,
        "target": None,
        "repo": None,
        "notes": None,
        "focus": [],
        "sections": [],
        "issue": None,
        "base": None,
        "head": None,
        "tail": [],
    }
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--json":
            parsed["json"] = True
            index += 1
            continue
        if token in {
            "--goal",
            "--scope",
            "--target",
            "--url",
            "--repo",
            "--notes",
            "--focus",
            "--sections",
            "--issue",
            "--base",
            "--head",
        }:
            if index + 1 >= len(argv):
                return None
            value = argv[index + 1].strip()
            if token in {"--target", "--url"}:
                parsed["target"] = value
            elif token in {"--focus", "--sections"}:
                parsed[token[2:]] = _split_csv(value)
            else:
                parsed[token[2:]] = value
            index += 2
            continue
        parsed["tail"].append(token)
        index += 1
    return parsed


def _ecosystem_keys_for_repo(repo: str | None) -> list[str]:
    normalized = (repo or "").strip().lower()
    if normalized == "top-uni":
        return ["top-uni", "my-cv-public", "my_opencode", "agents-md"]
    return ["my_opencode", "agents-md", "top-uni", "my-cv-public"]


def _build_context(mode: str, parsed: dict[str, Any]) -> dict[str, Any]:
    spec = COMMAND_SPECS[mode]
    defaults = spec.get("defaults", {})
    repo = str(parsed.get("repo") or defaults.get("repo") or "my_opencode")
    target = str(parsed.get("target") or defaults.get("target") or "").strip()
    if repo.lower() == "top-uni" and not target:
        target = str(ECOSYSTEM_LINKS["top-uni"]["url"])
    goal = str(parsed.get("goal") or defaults.get("goal") or "").strip()
    tail = " ".join(
        str(item) for item in parsed.get("tail", []) if str(item).strip()
    ).strip()
    if tail:
        goal = goal if goal else tail
    notes = str(parsed.get("notes") or "").strip()
    if tail and parsed.get("goal") is not None:
        notes = f"{notes} {tail}".strip()
    focus = parsed.get("focus") or defaults.get("focus") or []
    sections = parsed.get("sections") or []
    scope = str(parsed.get("scope") or defaults.get("scope") or _repo_root()).strip()
    return {
        "mode": mode,
        "repo": repo,
        "goal": goal,
        "scope": scope,
        "target": target or None,
        "notes": notes or None,
        "focus": [str(item) for item in focus if str(item).strip()],
        "sections": [str(item) for item in sections if str(item).strip()],
        "issue": parsed.get("issue"),
        "base": parsed.get("base"),
        "head": parsed.get("head"),
        "ecosystem_keys": _ecosystem_keys_for_repo(repo),
    }


def _render_links(keys: list[str]) -> list[str]:
    lines: list[str] = []
    for key in keys:
        entry = ECOSYSTEM_LINKS.get(key)
        if not entry:
            continue
        lines.append(f"- {entry['label']}: {entry['url']} ({entry['notes']})")
    return lines


def _render_prompt_block(spec: dict[str, Any], context: dict[str, Any]) -> str:
    lines = [
        f"OX-AUTOMATION namespace={NAMESPACE} mode={context['mode']} version={VERSION}",
        f"Command: {spec['slash']}",
        f"Recommended agent: {spec['agent']}",
        f"Objective: {context['goal']}",
        f"Scope: {context['scope']}",
        f"Repo context: {context['repo']}",
    ]
    if context.get("target"):
        lines.append(f"Target: {context['target']}")
    if context.get("issue"):
        lines.append(f"Issue/task: {context['issue']}")
    if context.get("base") or context.get("head"):
        lines.append(
            f"Git range: {context.get('base') or 'main'}...{context.get('head') or 'HEAD'}"
        )
    if context.get("focus"):
        lines.append(f"Focus: {', '.join(context['focus'])}")
    if context.get("sections"):
        lines.append(f"Sections: {', '.join(context['sections'])}")
    if context.get("notes"):
        lines.append(f"Extra notes: {context['notes']}")
    lines.extend(["", "Execution contract:"])
    for index, step in enumerate(spec.get("workflow", []), start=1):
        lines.append(f"{index}. {step}")
    lines.extend(["", "Acceptance checklist:"])
    for item in spec.get("acceptance", []):
        lines.append(f"- {item}")
    startup = spec.get("startup") or []
    if startup:
        lines.extend(["", "Recommended setup commands:"])
        for item in startup:
            lines.append(f"- {item}")
    mcp_profiles = spec.get("mcp_profiles") or []
    if mcp_profiles:
        lines.extend(["", "Recommended context/tooling:"])
        for item in mcp_profiles:
            lines.append(f"- MCP/browser profile: {item}")
    lines.extend(["", "Linked ecosystem references:"])
    lines.extend(_render_links(context.get("ecosystem_keys", [])))
    lines.extend(
        [
            "",
            "Operating note: execute the work directly after using this expansion; do not stop at plan-only output when the next implementation step is clear.",
        ]
    )
    return "\n".join(lines)


def _command_payload(mode: str, parsed: dict[str, Any]) -> dict[str, Any]:
    spec = COMMAND_SPECS[mode]
    context = _build_context(mode, parsed)
    return {
        "result": "PASS",
        "namespace": NAMESPACE,
        "version": VERSION,
        "command": mode,
        "slash_command": spec["slash"],
        "title": spec["title"],
        "summary": spec["summary"],
        "recommended_agent": spec["agent"],
        "recommended_mcp_profiles": spec.get("mcp_profiles", []),
        "recommended_setup": spec.get("startup", []),
        "context": context,
        "ecosystem": [
            ECOSYSTEM_LINKS[key] | {"key": key} for key in context["ecosystem_keys"]
        ],
        "prompt_block": _render_prompt_block(spec, context),
    }


def _emit(payload: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("result") == "PASS" else 1
    prompt_block = payload.get("prompt_block")
    if isinstance(prompt_block, str) and prompt_block.strip():
        print(prompt_block)
        return 0
    for line in payload.get("lines", []):
        print(line)
    return 0 if payload.get("result") == "PASS" else 1


def command_catalog(as_json: bool) -> int:
    commands = [
        {
            "name": "/ox",
            "description": "Namespace catalog, doctor, and ecosystem links",
        },
        *[
            {"name": spec["slash"], "description": spec["summary"]}
            for spec in COMMAND_SPECS.values()
        ],
    ]
    payload = {
        "result": "PASS",
        "namespace": NAMESPACE,
        "version": VERSION,
        "commands": commands,
        "lines": [
            f"/{NAMESPACE} namespace v{VERSION}",
            "Use `/ox` for catalog/doctor/ecosystem and `/ox-*` for stable prompt expansions.",
            *[f"- {item['name']}: {item['description']}" for item in commands],
        ],
    }
    return _emit(payload, as_json)


def command_doctor(as_json: bool) -> int:
    payload = {
        "result": "PASS",
        "namespace": NAMESPACE,
        "version": VERSION,
        "command_count": len(COMMAND_SPECS) + 1,
        "commands": sorted(["ox", *[f"ox-{name}" for name in COMMAND_SPECS]]),
        "ecosystem_keys": sorted(ECOSYSTEM_LINKS),
        "backend": str(Path(__file__).resolve()),
        "lines": [
            f"result: PASS",
            f"namespace: {NAMESPACE}",
            f"version: {VERSION}",
            f"commands: {','.join(sorted(['ox', *[f'ox-{name}' for name in COMMAND_SPECS]]))}",
            f"ecosystem_keys: {','.join(sorted(ECOSYSTEM_LINKS))}",
            f"backend: {Path(__file__).resolve()}",
        ],
    }
    return _emit(payload, as_json)


def command_ecosystem(as_json: bool) -> int:
    entries = [{"key": key, **value} for key, value in ECOSYSTEM_LINKS.items()]
    payload = {
        "result": "PASS",
        "namespace": NAMESPACE,
        "version": VERSION,
        "ecosystem": entries,
        "lines": [
            f"/{NAMESPACE} ecosystem links:",
            *[f"- {item['key']}: {item['url']}" for item in entries],
        ],
    }
    return _emit(payload, as_json)


def main(argv: list[str]) -> int:
    if not argv:
        return command_catalog(False)

    command = argv[0].strip().lower()
    rest = argv[1:]
    if command in {"help", "list", "catalog"}:
        return command_catalog("--json" in rest)
    if command == "doctor":
        if any(arg != "--json" for arg in rest):
            return usage()
        return command_doctor("--json" in rest)
    if command == "ecosystem":
        if any(arg != "--json" for arg in rest):
            return usage()
        return command_ecosystem("--json" in rest)
    if command not in COMMAND_SPECS:
        return usage()
    parsed = _parse_common_args(rest)
    if parsed is None:
        return usage()
    payload = _command_payload(command, parsed)
    return _emit(payload, bool(parsed.get("json")))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
