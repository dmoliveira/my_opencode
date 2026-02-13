#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
from pathlib import Path


IGNORED_DIRS = {".git", ".beads", "__pycache__", "node_modules", ".ruff_cache"}
TEXT_EXTENSIONS = {
    ".py",
    ".md",
    ".json",
    ".jsonc",
    ".txt",
    ".sh",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
}


def parse_scope_patterns(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def is_candidate_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if any(part in IGNORED_DIRS for part in path.parts):
        return False
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return False
    return True


def discover_scope_files(root: Path, patterns: list[str]) -> list[Path]:
    found: dict[str, Path] = {}
    if patterns:
        for pattern in patterns:
            for path in root.glob(pattern):
                if is_candidate_file(path):
                    found[str(path.resolve())] = path.resolve()
    else:
        for path in root.rglob("*"):
            if is_candidate_file(path):
                found[str(path.resolve())] = path.resolve()
    return sorted(found.values(), key=lambda p: str(p))


def analyze_target(root: Path, files: list[Path], target: str) -> dict:
    needle = target.lower()
    matched_files: list[dict] = []
    total_matches = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        line_hits: list[int] = []
        for idx, line in enumerate(lines, start=1):
            if needle in line.lower():
                line_hits.append(idx)
        if not line_hits:
            continue
        rel = str(path.relative_to(root))
        total_matches += len(line_hits)
        matched_files.append(
            {
                "path": rel,
                "match_count": len(line_hits),
                "line_hits": line_hits[:20],
            }
        )

    return {
        "matched_files": matched_files,
        "matched_file_count": len(matched_files),
        "total_matches": total_matches,
    }


def run_hook(command: list[str], cwd: Path) -> dict:
    proc = subprocess.run(command, capture_output=True, text=True, check=False, cwd=cwd)
    return {
        "name": " ".join(command),
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def fail_payload(
    target: str,
    strategy: str,
    scope: list[str],
    error_code: str,
    reason: str,
    remediation: list[str],
) -> dict:
    return {
        "result": "FAIL",
        "target": target,
        "scope": scope,
        "strategy": strategy,
        "changed_files": 0,
        "validations": [],
        "error_code": error_code,
        "reason": reason,
        "remediation": remediation,
        "next": [],
    }


def print_payload(payload: dict, json_output: bool) -> int:
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("result") == "PASS" else 1

    print(f"result: {payload.get('result')}")
    if payload.get("result") == "FAIL":
        print(f"error_code: {payload.get('error_code')}")
        print(f"reason: {payload.get('reason')}")
        for item in payload.get("remediation", []):
            print(f"remediation: {item}")
        return 1

    print(f"target: {payload.get('target')}")
    print(f"scope: {','.join(payload.get('scope', [])) or '(auto)'}")
    print(f"strategy: {payload.get('strategy')}")
    print(f"changed_files: {payload.get('changed_files')}")
    print("validations:")
    for check in payload.get("validations", []):
        state = "PASS" if check.get("ok") else "FAIL"
        print(f"- {check.get('name')}: {state} (exit={check.get('exit_code')})")
    print("next:")
    for item in payload.get("next", []):
        print(f"- {item}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="/refactor-lite",
        description="Safe refactor workflow backend",
    )
    parser.add_argument("target", nargs="?")
    parser.add_argument("--scope")
    parser.add_argument(
        "--strategy", choices=["safe", "balanced", "aggressive"], default="safe"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--run-selftest", action="store_true")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    target = (args.target or "").strip()
    scope_patterns = parse_scope_patterns(args.scope)
    root = Path.cwd()

    if not target:
        payload = fail_payload(
            target=target,
            strategy=args.strategy,
            scope=scope_patterns,
            error_code="target_required",
            reason="target is required",
            remediation=[
                "run /refactor-lite <target>",
                "use --scope <path|glob> to narrow search",
            ],
        )
        return print_payload(payload, args.json)

    files = discover_scope_files(root, scope_patterns)
    analysis = analyze_target(root, files, target)

    if analysis["matched_file_count"] == 0:
        payload = fail_payload(
            target=target,
            strategy=args.strategy,
            scope=scope_patterns,
            error_code="target_not_found",
            reason="target did not match any files in scope",
            remediation=[
                "adjust target phrase",
                "expand scope with --scope <glob>",
                "run /refactor-lite <target> --dry-run --json for diagnostics",
            ],
        )
        return print_payload(payload, args.json)

    if (
        args.strategy == "safe"
        and not scope_patterns
        and analysis["matched_file_count"] > 25
    ):
        payload = fail_payload(
            target=target,
            strategy=args.strategy,
            scope=scope_patterns,
            error_code="ambiguous_target",
            reason="safe mode requires narrower scope for high-match targets",
            remediation=[
                "rerun with --scope src/**/*.py (or similar)",
                "switch to --strategy balanced if intentional",
            ],
        )
        return print_payload(payload, args.json)

    validations: list[dict] = []
    if not args.dry_run:
        makefile = root / "Makefile"
        if makefile.exists():
            validations.append(run_hook(["make", "validate"], cwd=root))
            if args.run_selftest:
                validations.append(run_hook(["make", "selftest"], cwd=root))
        else:
            validations.append(
                {
                    "name": "make validate",
                    "ok": False,
                    "exit_code": 2,
                    "stdout": "",
                    "stderr": "Makefile not found",
                }
            )

    if any(not item.get("ok") for item in validations):
        payload = fail_payload(
            target=target,
            strategy=args.strategy,
            scope=scope_patterns,
            error_code="verification_failed",
            reason="post-change verification hooks failed",
            remediation=[
                "fix validation errors and rerun",
                "use --dry-run to inspect plan without hooks",
            ],
        )
        payload["validations"] = validations
        return print_payload(payload, args.json)

    payload = {
        "result": "PASS",
        "target": target,
        "scope": scope_patterns,
        "strategy": args.strategy,
        "changed_files": 0,
        "validations": validations,
        "error_code": None,
        "reason": None,
        "remediation": [],
        "preflight": {
            "matched_file_count": analysis["matched_file_count"],
            "total_matches": analysis["total_matches"],
            "file_map": analysis["matched_files"],
            "dry_run": args.dry_run,
        },
        "next": [
            "review preflight file_map before enabling write path",
            "run with --run-selftest for stronger verification",
        ],
    }
    return print_payload(payload, args.json)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
