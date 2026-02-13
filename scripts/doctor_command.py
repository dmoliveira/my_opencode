#!/usr/bin/env python3

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def script_path(name: str) -> Path:
    return REPO_ROOT / "scripts" / name


CHECKS = [
    {
        "name": "mcp",
        "kind": "doctor-json",
        "command": [
            sys.executable,
            str(script_path("mcp_command.py")),
            "doctor",
            "--json",
        ],
    },
    {
        "name": "plugin",
        "kind": "doctor-json",
        "command": [
            sys.executable,
            str(script_path("plugin_command.py")),
            "doctor",
            "--json",
        ],
    },
    {
        "name": "notify",
        "kind": "doctor-json",
        "command": [
            sys.executable,
            str(script_path("notify_command.py")),
            "doctor",
            "--json",
        ],
    },
    {
        "name": "digest",
        "kind": "doctor-json",
        "command": [
            sys.executable,
            str(script_path("session_digest.py")),
            "doctor",
            "--json",
        ],
    },
    {
        "name": "telemetry",
        "kind": "doctor-json",
        "command": [
            sys.executable,
            str(script_path("telemetry_command.py")),
            "doctor",
            "--json",
        ],
    },
    {
        "name": "post-session",
        "kind": "status-only",
        "command": [
            sys.executable,
            str(script_path("post_session_command.py")),
            "status",
        ],
    },
    {
        "name": "policy",
        "kind": "status-only",
        "command": [
            sys.executable,
            str(script_path("policy_command.py")),
            "status",
        ],
    },
    {
        "name": "bg",
        "kind": "doctor-json",
        "command": [
            sys.executable,
            str(script_path("background_task_manager.py")),
            "doctor",
            "--json",
        ],
    },
    {
        "name": "refactor-lite",
        "kind": "doctor-json",
        "optional": True,
        "required_path": str(script_path("refactor_lite_command.py")),
        "command": [
            sys.executable,
            str(script_path("refactor_lite_command.py")),
            "profile",
            "--scope",
            "scripts/*.py",
            "--dry-run",
            "--json",
        ],
    },
    {
        "name": "hooks",
        "kind": "doctor-json",
        "optional": True,
        "required_path": str(script_path("hooks_command.py")),
        "command": [
            sys.executable,
            str(script_path("hooks_command.py")),
            "doctor",
            "--json",
        ],
    },
    {
        "name": "model-routing",
        "kind": "doctor-json",
        "optional": True,
        "required_path": str(script_path("model_routing_command.py")),
        "command": [
            sys.executable,
            str(script_path("model_routing_command.py")),
            "resolve",
            "--json",
        ],
    },
    {
        "name": "keyword-mode",
        "kind": "doctor-json",
        "optional": True,
        "required_path": str(script_path("keyword_mode_command.py")),
        "command": [
            sys.executable,
            str(script_path("keyword_mode_command.py")),
            "doctor",
            "--json",
        ],
    },
    {
        "name": "rules",
        "kind": "doctor-json",
        "optional": True,
        "required_path": str(script_path("rules_command.py")),
        "command": [
            sys.executable,
            str(script_path("rules_command.py")),
            "doctor",
            "--json",
        ],
    },
    {
        "name": "resilience",
        "kind": "doctor-json",
        "optional": True,
        "required_path": str(script_path("context_resilience_command.py")),
        "command": [
            sys.executable,
            str(script_path("context_resilience_command.py")),
            "doctor",
            "--json",
        ],
    },
]


def usage() -> int:
    print("usage: /doctor status | /doctor help | /doctor run [--json]")
    return 2


def run_check(entry: dict) -> dict:
    if entry.get("optional"):
        required = Path(str(entry.get("required_path") or ""))
        if not required.exists():
            return {
                "name": entry["name"],
                "kind": entry["kind"],
                "exit_code": 0,
                "ok": True,
                "stdout": "",
                "stderr": "",
                "skipped": True,
                "skip_reason": f"optional check unavailable: {required}",
            }

    result = subprocess.run(
        entry["command"],
        capture_output=True,
        text=True,
        check=False,
        env=os.environ.copy(),
    )

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    item = {
        "name": entry["name"],
        "kind": entry["kind"],
        "exit_code": result.returncode,
        "ok": result.returncode == 0,
        "stdout": stdout,
        "stderr": stderr,
    }

    if entry["kind"] == "doctor-json":
        try:
            parsed = json.loads(stdout)
            item["report"] = parsed
            item["report_result"] = parsed.get("result")
        except Exception as exc:
            item["ok"] = False
            item["parse_error"] = str(exc)

    return item


def summarize(items: list[dict]) -> dict:
    failed = [item for item in items if not item.get("ok")]
    warnings = []
    for item in items:
        if item.get("skipped"):
            warnings.append(f"{item['name']}: {item.get('skip_reason')}")
        report = item.get("report")
        if isinstance(report, dict):
            for warning in report.get("warnings", []):
                warnings.append(f"{item['name']}: {warning}")

    return {
        "result": "PASS" if not failed else "FAIL",
        "checks": items,
        "failed_count": len(failed),
        "warning_count": len(warnings),
        "warnings": warnings,
    }


def print_human(summary: dict) -> int:
    print("doctor")
    print("------")
    for item in summary["checks"]:
        state = "PASS" if item["ok"] else "FAIL"
        detail = ""
        if item.get("report_result"):
            detail = f" report={item['report_result']}"
        print(f"- {item['name']}: {state} (exit={item['exit_code']}){detail}")

    if summary["warnings"]:
        print("\nwarnings:")
        for warning in summary["warnings"]:
            print(f"- {warning}")

    print(f"\nresult: {summary['result']}")
    return 0 if summary["result"] == "PASS" else 1


def command_run(argv: list[str]) -> int:
    json_output = "--json" in argv
    if any(arg not in ("--json",) for arg in argv):
        return usage()

    items = [run_check(entry) for entry in CHECKS]
    summary = summarize(items)

    if json_output:
        print(json.dumps(summary, indent=2))
        return 0 if summary["result"] == "PASS" else 1

    return print_human(summary)


def main(argv: list[str]) -> int:
    if not argv or argv[0] == "status":
        return command_run([])
    if argv[0] == "help":
        return usage()
    if argv[0] == "run":
        return command_run(argv[1:])
    return usage()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
