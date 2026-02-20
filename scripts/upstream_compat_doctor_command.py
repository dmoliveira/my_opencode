#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
UPSTREAM_BG_SCRIPT = SCRIPT_DIR / "upstream_bg_compat_command.py"
UPSTREAM_AGENT_SCRIPT = SCRIPT_DIR / "upstream_agent_compat_command.py"


def _run(script: Path, args: list[str]) -> tuple[int, dict[str, Any] | None, str]:
    proc = subprocess.run(
        [sys.executable, str(script), *args, "--json"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(SCRIPT_DIR.parent),
    )
    if proc.returncode != 0 and not proc.stdout.strip():
        return proc.returncode, None, proc.stderr.strip()
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc.returncode, None, proc.stderr.strip() or "invalid json output"
    return proc.returncode, payload, proc.stderr.strip()


def _doctor_payload() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    rc, payload, err = _run(UPSTREAM_BG_SCRIPT, ["status"])
    checks.append(
        {
            "name": "upstream-bg-status",
            "ok": rc == 0
            and isinstance(payload, dict)
            and payload.get("result") == "PASS",
            "payload": payload,
            "error": err,
        }
    )

    rc, payload, err = _run(UPSTREAM_AGENT_SCRIPT, ["status"])
    checks.append(
        {
            "name": "upstream-agent-map-status",
            "ok": rc == 0
            and isinstance(payload, dict)
            and payload.get("result") in {"PASS", "WARN"},
            "payload": payload,
            "error": err,
        }
    )

    rc, payload, err = _run(UPSTREAM_AGENT_SCRIPT, ["map", "--role", "sisyphus"])
    checks.append(
        {
            "name": "upstream-agent-map-sisyphus",
            "ok": rc == 0
            and isinstance(payload, dict)
            and payload.get("local_agent") == "orchestrator",
            "payload": payload,
            "error": err,
        }
    )

    problems = [c["name"] for c in checks if not c.get("ok")]
    warnings: list[str] = []
    agent_payload = checks[1].get("payload") if len(checks) > 1 else None
    if isinstance(agent_payload, dict) and agent_payload.get("result") == "WARN":
        warnings.append(
            "upstream agent map status is WARN; inspect hook_bridge diagnostics"
        )

    return {
        "result": "PASS" if not problems else "FAIL",
        "checks": checks,
        "warnings": warnings,
        "problems": problems,
        "quick_fixes": [
            "/upstream-bg-status",
            "/upstream-agent-map-status",
            "/upstream-agent-map --role sisyphus",
        ],
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="upstream_compat_doctor_command.py",
        description="Doctor checks for upstream compatibility facade readiness.",
    )
    parser.add_argument("subcommand", nargs="?", default="doctor", choices=["doctor"])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = _doctor_payload()
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"result: {payload['result']}")
        for check in payload["checks"]:
            print(f"- {check['name']}: {'PASS' if check['ok'] else 'FAIL'}")
        if payload["warnings"]:
            print("warnings:")
            for warning in payload["warnings"]:
                print(f"- {warning}")
        if payload["problems"]:
            print("problems:")
            for problem in payload["problems"]:
                print(f"- {problem}")
    return 0 if payload["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
