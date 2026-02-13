#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_edit_adapters import (  # type: ignore
    BACKEND_BINARIES,
    OPERATION_BACKENDS,
    collect_binary_availability,
    detect_language,
    evaluate_semantic_capability,
)


SUPPORTED_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".go",
    ".rs",
}
IGNORED_DIRS = {".git", ".beads", "node_modules", "__pycache__", ".ruff_cache"}


def usage() -> int:
    print(
        "usage: /safe-edit status [--json] | "
        "/safe-edit plan --operation <rename|extract|organize_imports|scoped_replace> --scope <glob[,glob...]> [--allow-text-fallback] [--json] | "
        "/safe-edit doctor [--json]"
    )
    return 2


def _split_scope(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _discover_files(root: Path, patterns: list[str]) -> list[Path]:
    seen: dict[str, Path] = {}
    for pattern in patterns:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            if any(part in IGNORED_DIRS for part in path.parts):
                continue
            resolved = path.resolve()
            seen[str(resolved)] = resolved
    return sorted(seen.values(), key=lambda item: str(item))


def command_status(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    json_output = "--json" in args

    binaries = collect_binary_availability()
    backends: dict[str, dict[str, bool]] = {}
    for language, mapping in BACKEND_BINARIES.items():
        backends[language] = {}
        for backend, required in mapping.items():
            backends[language][backend] = all(
                binaries.get(binary, False) for binary in required
            )

    report = {
        "result": "PASS",
        "operations": sorted(OPERATION_BACKENDS.keys()),
        "backend_status": backends,
        "binaries": binaries,
    }
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print("operations: " + ", ".join(report["operations"]))
        print("backend_status:")
        for language in sorted(backends.keys()):
            lsp = "yes" if backends[language].get("lsp") else "no"
            ast = "yes" if backends[language].get("ast") else "no"
            print(f"- {language}: lsp={lsp}, ast={ast}")
    return 0


def command_plan(args: list[str]) -> int:
    json_output = "--json" in args
    allow_text_fallback = "--allow-text-fallback" in args
    operation = ""
    scope_patterns: list[str] = []

    index = 0
    while index < len(args):
        token = args[index]
        if token in ("--json", "--allow-text-fallback"):
            index += 1
            continue
        if token == "--operation":
            if index + 1 >= len(args):
                return usage()
            operation = args[index + 1].strip()
            index += 2
            continue
        if token == "--scope":
            if index + 1 >= len(args):
                return usage()
            scope_patterns = _split_scope(args[index + 1])
            index += 2
            continue
        return usage()

    if not operation or not scope_patterns:
        return usage()

    root = Path.cwd()
    files = _discover_files(root, scope_patterns)
    if not files:
        report = {
            "result": "FAIL",
            "reason_code": "safe_edit_empty_scope",
            "operation": operation,
            "scope": scope_patterns,
        }
        print(json.dumps(report, indent=2) if json_output else "no files matched scope")
        return 1

    capability = evaluate_semantic_capability(
        operation,
        files,
        allow_text_fallback=allow_text_fallback,
        scope_explicit=True,
    )
    report = {
        "result": capability.get("result"),
        "reason_code": capability.get("reason_code"),
        "operation": operation,
        "scope": scope_patterns,
        "target_files": [str(path.relative_to(root)) for path in files],
        "adapters": capability.get("adapters", []),
        "language_counts": {},
    }
    counts: dict[str, int] = {}
    for path in files:
        language = detect_language(path)
        counts[language] = counts.get(language, 0) + 1
    report["language_counts"] = counts

    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"result: {report['result']}")
        print(f"reason_code: {report['reason_code']}")
        print(f"operation: {report['operation']}")
        print(f"files: {len(files)}")
    return 0 if report["result"] == "PASS" else 1


def command_doctor(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    json_output = "--json" in args

    binaries = collect_binary_availability()
    warnings: list[str] = []
    problems: list[str] = []
    supported_any_language = False
    for language, mapping in BACKEND_BINARIES.items():
        lsp_ok = all(binaries.get(binary, False) for binary in mapping.get("lsp", ()))
        ast_ok = all(binaries.get(binary, False) for binary in mapping.get("ast", ()))
        if lsp_ok or ast_ok:
            supported_any_language = True
        else:
            warnings.append(
                f"{language}: neither lsp nor ast backend is fully available"
            )
    if not supported_any_language:
        problems.append("no semantic safe-edit backend is available")

    report = {
        "result": "PASS" if not problems else "FAIL",
        "warnings": warnings,
        "problems": problems,
        "quick_fixes": [
            "/safe-edit status --json",
            "install language servers or parser toolchains for your repo languages",
        ],
    }
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"result: {report['result']}")
        for warning in warnings:
            print(f"- warning: {warning}")
        for problem in problems:
            print(f"- problem: {problem}")
    return 0 if report["result"] == "PASS" else 1


def main(argv: list[str]) -> int:
    if not argv:
        return usage()
    command = argv[0]
    rest = argv[1:]
    if command in ("help", "--help", "-h"):
        return usage()
    if command == "status":
        return command_status(rest)
    if command == "plan":
        return command_plan(rest)
    if command == "doctor":
        return command_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
