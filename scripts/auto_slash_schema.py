#!/usr/bin/env python3

from __future__ import annotations

import re
from typing import Any


COMMANDS = {
    "doctor": {
        "description": "Run integrated diagnostics.",
        "default_args": ["run"],
        "script": "doctor_command.py",
    },
    "stack": {
        "description": "Apply or inspect stack profiles.",
        "default_args": ["status"],
        "script": "stack_profile_command.py",
    },
    "nvim": {
        "description": "Manage Neovim integration state.",
        "default_args": ["status"],
        "script": "nvim_integration_command.py",
    },
    "devtools": {
        "description": "Inspect/install developer tooling.",
        "default_args": ["status"],
        "script": "devtools_command.py",
    },
}


INTENT_RULES = {
    "doctor": {
        "keywords": {
            "doctor",
            "diagnose",
            "diagnostics",
            "health",
            "broken",
            "verify",
            "check",
        },
        "phrases": {
            "run doctor",
            "health check",
            "why is this broken",
            "diagnose this setup",
        },
    },
    "stack": {
        "keywords": {
            "stack",
            "profile",
            "focus",
            "research",
            "quiet",
            "ci",
            "mode",
        },
        "phrases": {
            "switch profile",
            "apply profile",
            "focus mode",
            "research mode",
            "quiet ci",
        },
    },
    "nvim": {
        "keywords": {
            "nvim",
            "neovim",
            "vim",
            "init",
            "plugin",
            "lua",
            "editor",
        },
        "phrases": {
            "nvim doctor",
            "neovim integration",
            "install nvim",
            "link init",
        },
    },
    "devtools": {
        "keywords": {
            "devtools",
            "tooling",
            "pre-commit",
            "lefthook",
            "direnv",
            "gh-dash",
            "ripgrep",
            "hooks",
            "install",
        },
        "phrases": {
            "install devtools",
            "install tooling",
            "setup hooks",
            "devtools doctor",
        },
    },
}


def tokenize_prompt(prompt: str) -> list[str]:
    if not prompt:
        return []
    cleaned = re.sub(r"```[\s\S]*?```", " ", prompt)
    cleaned = re.sub(r"`[^`]*`", " ", cleaned)
    return [token.lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9-]*", cleaned)]


def _phrase_hits(prompt_lower: str, phrases: set[str]) -> int:
    return sum(1 for phrase in phrases if phrase in prompt_lower)


def _score_candidate(
    tokens: set[str], prompt_lower: str, command: str
) -> dict[str, Any]:
    spec = INTENT_RULES[command]
    keywords = spec["keywords"]
    matched_keywords = sorted(token for token in tokens if token in keywords)
    keyword_score = 0.0
    if keywords:
        keyword_score = min(1.0, len(matched_keywords) / max(1.0, len(keywords) / 2.0))
    phrase_hits = _phrase_hits(prompt_lower, spec["phrases"])
    phrase_score = min(1.0, phrase_hits * 0.45)
    score = min(1.0, keyword_score * 0.6 + phrase_score)
    return {
        "command": command,
        "score": round(score, 4),
        "matched_keywords": matched_keywords,
        "phrase_hits": phrase_hits,
    }


def _resolve_args(command: str, tokens: set[str], prompt_lower: str) -> list[str]:
    if command == "doctor":
        if "json" in tokens:
            return ["run", "--json"]
        return ["run"]

    if command == "stack":
        if "focus" in tokens:
            return ["apply", "focus"]
        if "research" in tokens:
            return ["apply", "research"]
        if "quiet" in tokens and "ci" in tokens:
            return ["apply", "quiet-ci"]
        return ["status"]

    if command == "nvim":
        if "doctor" in tokens or "diagnose" in tokens:
            return ["doctor", "--json"]
        if "install" in tokens:
            profile = "power" if "power" in tokens else "minimal"
            args = ["install", profile]
            if "link" in tokens or "init" in tokens or "init.lua" in prompt_lower:
                args.append("--link-init")
            return args
        if "snippet" in tokens:
            profile = "power" if "power" in tokens else "minimal"
            return ["snippet", profile]
        return ["status"]

    if command == "devtools":
        if "doctor" in tokens or "diagnose" in tokens:
            return ["doctor", "--json"]
        if "hook" in tokens or "hooks" in tokens:
            if "install" in tokens or "setup" in tokens:
                return ["hooks-install"]
        if "install" in tokens:
            targets = [
                name
                for name in [
                    "direnv",
                    "gh-dash",
                    "ripgrep-all",
                    "pre-commit",
                    "lefthook",
                ]
                if name in tokens
            ]
            if not targets:
                targets = ["all"]
            return ["install", *targets]
        return ["status"]

    return COMMANDS[command]["default_args"]


def detect_intent(
    prompt: str,
    *,
    enabled: bool,
    enabled_commands: set[str],
    min_confidence: float,
    ambiguity_delta: float,
) -> dict[str, Any]:
    tokens = tokenize_prompt(prompt)
    token_set = set(tokens)
    prompt_lower = prompt.lower()

    if not enabled:
        return {
            "result": "NOOP",
            "reason": "global_disabled",
            "tokens": tokens,
            "candidates": [],
            "selected": None,
        }

    if any(token.startswith("/") for token in prompt.split()):
        return {
            "result": "NOOP",
            "reason": "explicit_slash_present",
            "tokens": tokens,
            "candidates": [],
            "selected": None,
        }

    candidates = [
        _score_candidate(token_set, prompt_lower, command)
        for command in COMMANDS
        if command in enabled_commands
    ]
    candidates.sort(key=lambda item: item["score"], reverse=True)

    if not candidates or candidates[0]["score"] <= 0:
        return {
            "result": "NOOP",
            "reason": "no_match",
            "tokens": tokens,
            "candidates": candidates,
            "selected": None,
        }

    top = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    if top["score"] < min_confidence:
        return {
            "result": "NOOP",
            "reason": "low_confidence",
            "tokens": tokens,
            "candidates": candidates,
            "selected": None,
            "min_confidence": min_confidence,
        }

    if second and (top["score"] - second["score"]) < ambiguity_delta:
        return {
            "result": "NOOP",
            "reason": "ambiguous",
            "tokens": tokens,
            "candidates": candidates,
            "selected": None,
            "ambiguity_delta": ambiguity_delta,
        }

    command = top["command"]
    args = _resolve_args(command, token_set, prompt_lower)
    slash_command = f"/{command} {' '.join(args)}".strip()
    selected = {
        "command": command,
        "args": args,
        "slash_command": slash_command,
        "score": top["score"],
        "matched_keywords": top["matched_keywords"],
        "phrase_hits": top["phrase_hits"],
        "script": COMMANDS[command]["script"],
    }
    return {
        "result": "MATCH",
        "reason": "matched",
        "tokens": tokens,
        "candidates": candidates,
        "selected": selected,
    }


def evaluate_precision(
    dataset: list[dict[str, str | None]], **kwargs: Any
) -> dict[str, Any]:
    predicted = 0
    correct = 0
    unsafe = 0
    rows: list[dict[str, Any]] = []

    for row in dataset:
        prompt = str(row.get("prompt", ""))
        expected = row.get("expected")
        report = detect_intent(prompt, **kwargs)
        selected = report.get("selected") or {}
        predicted_command = selected.get("command")
        if predicted_command:
            predicted += 1
        if predicted_command is not None and predicted_command == expected:
            correct += 1
        if expected is None and predicted_command is not None:
            unsafe += 1
        rows.append(
            {
                "prompt": prompt,
                "expected": expected,
                "predicted": predicted_command,
                "result": report.get("result"),
                "reason": report.get("reason"),
            }
        )

    precision = 1.0 if predicted == 0 else (correct / predicted)
    return {
        "samples": len(dataset),
        "predicted": predicted,
        "correct": correct,
        "precision": round(precision, 4),
        "unsafe_predictions": unsafe,
        "rows": rows,
    }
