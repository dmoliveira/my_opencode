#!/usr/bin/env python3

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Iterable


OPERATION_BACKENDS: dict[str, tuple[str, str | None]] = {
    "rename": ("lsp", "ast"),
    "extract": ("ast", "lsp"),
    "organize_imports": ("lsp", "ast"),
    "scoped_replace": ("ast", "lsp"),
}

LANGUAGE_SUFFIXES: dict[str, tuple[str, ...]] = {
    "python": (".py",),
    "typescript": (".ts", ".tsx"),
    "javascript": (".js", ".jsx", ".mjs", ".cjs"),
    "go": (".go",),
    "rust": (".rs",),
}

BACKEND_BINARIES: dict[str, dict[str, tuple[str, ...]]] = {
    "python": {
        "lsp": ("pyright-langserver",),
        "ast": ("python3",),
    },
    "typescript": {
        "lsp": ("typescript-language-server",),
        "ast": ("node",),
    },
    "javascript": {
        "lsp": ("typescript-language-server",),
        "ast": ("node",),
    },
    "go": {
        "lsp": ("gopls",),
        "ast": ("go",),
    },
    "rust": {
        "lsp": ("rust-analyzer",),
        "ast": ("cargo",),
    },
}


def detect_language(path: str | Path) -> str:
    suffix = Path(path).suffix.lower()
    for language, suffixes in LANGUAGE_SUFFIXES.items():
        if suffix in suffixes:
            return language
    return "unknown"


def collect_binary_availability() -> dict[str, bool]:
    seen: dict[str, bool] = {}
    for backend_map in BACKEND_BINARIES.values():
        for binaries in backend_map.values():
            for binary in binaries:
                if binary not in seen:
                    seen[binary] = shutil.which(binary) is not None
    return seen


def _backend_available(
    language: str, backend: str, available_binaries: dict[str, bool]
) -> bool:
    backend_map = BACKEND_BINARIES.get(language, {})
    required = backend_map.get(backend, ())
    if not required:
        return False
    return all(available_binaries.get(binary, False) for binary in required)


def evaluate_semantic_capability(
    operation: str,
    file_paths: Iterable[str | Path],
    *,
    available_binaries: dict[str, bool] | None = None,
    allow_text_fallback: bool = False,
    scope_explicit: bool = False,
    ambiguous_target: bool = False,
) -> dict:
    op = operation.strip()
    if op not in OPERATION_BACKENDS:
        return {
            "result": "FAIL",
            "reason_code": "safe_edit_unknown_operation",
            "operation": op,
            "adapters": [],
        }

    files = [Path(path) for path in file_paths]
    if not files:
        return {
            "result": "FAIL",
            "reason_code": "safe_edit_empty_scope",
            "operation": op,
            "adapters": [],
        }

    availability = (
        available_binaries
        if available_binaries is not None
        else collect_binary_availability()
    )
    preferred, secondary = OPERATION_BACKENDS[op]
    adapters: list[dict[str, str]] = []

    for path in files:
        language = detect_language(path)
        if language == "unknown":
            return {
                "result": "FAIL",
                "reason_code": "safe_edit_unknown_language",
                "operation": op,
                "adapters": adapters,
                "path": str(path),
            }

        chosen_backend = None
        if _backend_available(language, preferred, availability):
            chosen_backend = preferred
        elif secondary and _backend_available(language, secondary, availability):
            chosen_backend = secondary

        if chosen_backend is None:
            if op == "extract":
                return {
                    "result": "FAIL",
                    "reason_code": "safe_edit_ast_unavailable",
                    "operation": op,
                    "adapters": adapters,
                    "path": str(path),
                    "language": language,
                }
            if not allow_text_fallback:
                return {
                    "result": "FAIL",
                    "reason_code": "safe_edit_fallback_requires_opt_in",
                    "operation": op,
                    "adapters": adapters,
                    "path": str(path),
                    "language": language,
                }
            if not scope_explicit:
                return {
                    "result": "FAIL",
                    "reason_code": "safe_edit_fallback_blocked_scope",
                    "operation": op,
                    "adapters": adapters,
                    "path": str(path),
                    "language": language,
                }
            if ambiguous_target:
                return {
                    "result": "FAIL",
                    "reason_code": "safe_edit_fallback_blocked_ambiguity",
                    "operation": op,
                    "adapters": adapters,
                    "path": str(path),
                    "language": language,
                }
            chosen_backend = "text"

        adapters.append(
            {
                "path": str(path),
                "language": language,
                "backend": chosen_backend,
            }
        )

    return {
        "result": "PASS",
        "reason_code": "safe_edit_allowed",
        "operation": op,
        "adapters": adapters,
    }


def validate_changed_references(
    before: str, after: str, old_symbol: str, new_symbol: str
) -> dict:
    old_name = old_symbol.strip()
    new_name = new_symbol.strip()
    if not old_name or not new_name:
        return {
            "result": "FAIL",
            "reason_code": "safe_edit_validation_failed",
            "changed_references": 0,
            "remaining_old_references": 0,
        }

    old_pattern = re.compile(rf"\b{re.escape(old_name)}\b")
    new_pattern = re.compile(rf"\b{re.escape(new_name)}\b")
    before_old = len(old_pattern.findall(before))
    after_old = len(old_pattern.findall(after))
    before_new = len(new_pattern.findall(before))
    after_new = len(new_pattern.findall(after))
    changed = max(0, after_new - before_new)

    ok = changed > 0 and after_old == 0
    return {
        "result": "PASS" if ok else "FAIL",
        "reason_code": "safe_edit_allowed" if ok else "safe_edit_validation_failed",
        "changed_references": changed,
        "remaining_old_references": after_old,
    }
