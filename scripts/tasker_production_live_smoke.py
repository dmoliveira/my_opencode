#!/usr/bin/env python3
"""Exercise the real OpenCode plugin and OC backend with a controlled local model."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import tasker_e2e_sandbox as sandbox

SCOPE = "tasker-production-smoke"
CONSTRAINTS = [
    "read-only",
    "no writes",
    "no Codememory",
    "no delegation",
    "no tests or builds",
    "no git or gh",
]


def tool_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "tool":
            value = message.get("content", "")
            return value if isinstance(value, str) else json.dumps(value)
    return ""


class Probe:
    def __init__(self, root: Path, victim: Path) -> None:
        self.root = root
        self.victim = victim
        self.lock = threading.Lock()
        self.index = 0
        self.child_index = 0
        self.calls: list[str] = []
        self.errors: list[str] = []
        provenance = f"--scope {SCOPE} --worktree {root} --branch sandbox/tasker-probe"
        packet = json.dumps(
            {
                "objective": "Inspect planning documentation.",
                "paths": ["docs/codememory-workflow.md"],
                "acceptance": "Identify scope discovery rules.",
                "checks": "Read-only inspection.",
                "evidence": "File and line references.",
                "constraints": CONSTRAINTS,
            }
        )

        def bash(
            command: str, workdir: Path | None = None
        ) -> tuple[str, dict[str, Any]]:
            return "bash", {
                "command": command,
                "description": "Exercise isolated planning protocol",
                "workdir": str(workdir or root),
            }

        def apply(verb: str):
            def render(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
                match = re.search(
                    r'"plan_hash"\s*:\s*"([a-f0-9]{64})"',
                    tool_text(payload.get("messages", [])),
                )
                if not match:
                    raise AssertionError(
                        f"{verb} did not receive a native preview hash"
                    )
                return bash(
                    f"oc {verb} memory_1 --reason probe --apply {match.group(1)} --format json"
                )

            return render

        self.steps: list[Any] = [
            bash("command -v oc"),
            bash("oc config --doctor --format json"),
            bash(
                "oc db migrate --format json", victim
            ),  # Must not create the victim database.
            bash("oc db migrate --format json"),
            bash("oc config --doctor --format json"),
            (
                "task",
                {
                    "subagent_type": "explore",
                    "description": "Inspect planning documentation",
                    "prompt": packet,
                },
            ),
            bash(
                f'oc find "Probe task" --type task --scope {SCOPE} --limit 100 --format json'
            ),
            bash(f'oc add task "Probe task" --kind chore {provenance} --format json'),
            bash(
                f'oc find "Probe note" --type memory --scope {SCOPE} --limit 100 --format json'
            ),
            bash(
                f'oc add memory "Probe note" --kind note --body "Research synthesis: scope is explicit" {provenance} --format json'
            ),
            bash("oc get task_1 --view full --format json"),
            bash("oc get memory_1 --view full --format json"),
            bash(f"oc list link --scope {SCOPE} --limit 1000 --format json"),
            bash("oc link memory_1 about task_1 --format json"),
            bash("oc get task_1 --view full --format json"),
            bash("oc history task_1 --format json"),
            bash(
                'oc set task_1 goal "verified plan" --reason probe --expected-revision 1 --format json'
            ),
            bash("oc get memory_1 --view full --format json"),
            bash(
                "oc archive memory_1 --reason probe --format json"
            ),  # Native reference check rejects this.
            bash(f"oc list link --scope {SCOPE} --limit 1000 --format json"),
            bash("oc get link_1 --view full --format json"),
            bash("oc get memory_1 --view full --format json"),
            bash("oc get task_1 --view full --format json"),
            bash("oc unlink link_1 --reason probe --format json"),
            bash("oc get memory_1 --view full --format json"),
            bash("oc archive memory_1 --reason probe --format json"),
            apply("archive"),
            bash("oc get memory_1 --view full --format json"),
            bash("oc restore memory_1 --reason probe --format json"),
            apply("restore"),
            bash(
                f'oc find "Probe task" --type task --scope {SCOPE} --limit 100 --format json'
            ),
            bash("oc get task_1 --view full --format json"),
            bash(
                f'oc add task "Probe task" --kind chore {provenance} --format json'
            ),  # Exact duplicate rejected.
            bash(
                "oc cancel task_1 --why probe --expected-revision 2 --format json"
            ),  # Lifecycle remains denied.
            bash(f"oc current; echo unsafe > {root / 'unsafe-sentinel'}"),
        ]

    def response(self, payload: dict[str, Any]) -> tuple[str, dict[str, Any]] | str:
        model = payload.get("model", "")
        if model == "research":
            with self.lock:
                index = self.child_index
                self.child_index += 1
            if index == 0:
                return "read", {
                    "filePath": str(self.root / "docs/codememory-workflow.md"),
                    "limit": 80,
                }
            return "Evidence: docs/codememory-workflow.md:15-21 defines repository scope defaults."
        if model != "tasker" or not payload.get("tools"):
            return "Isolated protocol smoke"
        with self.lock:
            index = self.index
            self.index += 1
            if index >= len(self.steps):
                return "TASKER_PROTOCOL_OK. Research synthesis: explicit scope. task_1 memory_1."
            step = self.steps[index]
        result = step(payload) if callable(step) else step
        self.calls.append(result[0])
        return result


class Handler(BaseHTTPRequestHandler):
    probe: Probe

    def log_message(self, *_args: Any) -> None:
        return

    def do_GET(self) -> None:
        data = json.dumps(
            {
                "object": "list",
                "data": [
                    {"id": name, "object": "model", "owned_by": "fixture"}
                    for name in ("tasker", "research", "title")
                ],
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        try:
            payload = json.loads(
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
            )
            result = self.probe.response(payload)
        except (
            ValueError,
            OSError,
            AssertionError,
            RuntimeError,
            subprocess.SubprocessError,
        ) as exc:  # A protocol fixture failure must fail the smoke.
            self.probe.errors.append(str(exc))
            result = "PROBE_FAILED: " + str(exc)
        delta: dict[str, Any] = {"role": "assistant"}
        if isinstance(result, tuple):
            name, arguments = result
            delta["tool_calls"] = [
                {
                    "index": 0,
                    "id": f"call_{time.monotonic_ns()}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }
            ]
            finish = "tool_calls"
        else:
            delta["content"] = result
            finish = "stop"
        chunks = [
            {
                "id": "chatcmpl-tasker-probe",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": payload.get("model", "tasker"),
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            },
            {
                "id": "chatcmpl-tasker-probe",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": payload.get("model", "tasker"),
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
            },
        ]
        data = (
            "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
            + "data: [DONE]\n\n"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run(timeout_ms: int) -> dict[str, Any]:
    real_oc, real_opencode = sandbox.resolve_tasker_launchers()
    before = sandbox.snapshot_tree(sandbox.REPO_ROOT / ".codememory")
    with TemporaryDirectory(prefix="tasker-production-live-") as temporary:
        root = Path(temporary).resolve()
        runtime = sandbox.prepare_tasker_runtime(
            root / "runtime", model="probe/research", scope=SCOPE
        )
        workspace = Path(runtime["TASKER_E2E_WORKSPACE"])
        victim = root / "victim"
        (victim / ".codememory").mkdir(parents=True, mode=0o700)
        victim_config = victim / ".codememory/config.sqlite.yaml"
        victim_config.write_text(
            Path(runtime["TASKER_E2E_CODEMEMORY_CONFIG"])
            .read_text()
            .replace(str(workspace), str(victim)),
            encoding="utf-8",
        )
        victim_config.chmod(0o600)
        # Test native configuration selection, not a wrapper that forces a backend.
        launcher = Path(runtime["TASKER_E2E_OC_WRAPPER"])
        launcher.write_text(
            f"#!{sys.executable}\nimport os, sys\nos.environ['PATH'] = {os.defpath!r}\nos.execv({real_oc!r}, [{real_oc!r}, *sys.argv[1:]])\n",
            encoding="utf-8",
        )
        launcher.chmod(0o700)
        for tool in ("git", "rg"):
            found = shutil.which(tool)
            if found:
                (Path(runtime["TASKER_E2E_OC_WRAPPER"]).parent / tool).symlink_to(
                    Path(found).resolve()
                )
        git = shutil.which("git")
        if git is None:
            raise RuntimeError(
                "native protocol smoke requires Git for repo-local OC config discovery"
            )
        subprocess.run(
            [git, "init", "--quiet", str(workspace)],
            cwd=workspace,
            env=sandbox.direct_oc_environment(runtime),
            check=True,
            capture_output=True,
        )
        probe = Probe(workspace, victim)
        handler = type("ProbeHandler", (Handler,), {"probe": probe})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            config_path = Path(runtime["OPENCODE_CONFIG_PATH"])
            config = json.loads(config_path.read_text())
            config.update(
                {
                    "model": "probe/tasker",
                    "small_model": "probe/title",
                    "provider": {
                        "probe": {
                            "name": "Local protocol probe",
                            "npm": "@ai-sdk/openai-compatible",
                            "options": {
                                "baseURL": f"http://127.0.0.1:{server.server_port}/v1",
                                "apiKey": "fixture-not-a-credential",
                            },
                            "models": {
                                name: {"name": name}
                                for name in ("tasker", "research", "title")
                            },
                        }
                    },
                }
            )
            config_path.write_text(
                json.dumps(config, indent=2) + "\n", encoding="utf-8"
            )
            result = sandbox.run_process(
                [
                    real_opencode,
                    "run",
                    "--model",
                    "probe/tasker",
                    "--agent",
                    "tasker",
                    "--format",
                    "json",
                    "--dir",
                    str(workspace),
                    f"Authorized isolated planning protocol qualification. Use scope '{SCOPE}', worktree '{workspace}', branch 'sandbox/tasker-probe'. Exercise bootstrap, one read-only research call, planning artifacts and explicit planning repairs. Deliberately denied requests must remain denied.",
                ],
                cwd=workspace,
                timeout_ms=timeout_ms,
                env_overrides=runtime,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        events = sandbox.parse_events(result.stdout)
        audit_path = Path(runtime["MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH"])
        audit = (
            [json.loads(line) for line in audit_path.read_text().splitlines()]
            if audit_path.exists()
            else []
        )
        reasons = {
            row.get("reason_code")
            for row in audit
            if row.get("hook") == "tasker-command-gateway"
        }

        def oc(*args: str) -> dict[str, Any]:
            process = sandbox.run_process(
                [
                    real_oc,
                    "--config",
                    runtime["TASKER_E2E_CODEMEMORY_CONFIG"],
                    *args,
                    "--format",
                    "json",
                ],
                cwd=workspace,
                timeout_ms=30000,
                env_overrides=sandbox.direct_oc_environment(runtime),
            )
            if process.returncode:
                raise AssertionError(process.stderr or process.stdout)
            return json.loads(process.stdout)

        required = {
            "tasker_production_guard_active",
            "tasker_workdir_mismatch",
            "tasker_exact_record_exists",
            "tasker_command_boundary_blocked",
        }
        failures = list(probe.errors)
        if result.returncode != 0 or "TASKER_PROTOCOL_OK" not in sandbox.extract_text(
            events
        ):
            failures.append(
                f"runtime did not complete: {result.stderr[-2000:]} {result.stdout[-4000:]}"
            )
        if not required <= reasons:
            failures.append(
                f"missing native guard audit markers: {sorted(required - reasons)}"
            )
        try:
            tasks = oc("list", "task", "--scope", SCOPE, "--limit", "100")
            memories = oc("list", "memory", "--scope", SCOPE, "--limit", "100")
            record = oc("get", "task_1", "--view", "full")
            history = oc("history", "memory_1")
            commands = {
                item.get("command_type") for item in history.get("operations", [])
            }
            if (
                tasks.get("count") != 1
                or memories.get("count") != 1
                or record.get("goal") != "verified plan"
                or record.get("status") != "not-started"
                or not {"archive", "restore"} <= commands
            ):
                failures.append(
                    "native artifact, repair, recovery or duplicate/lifecycle invariants failed"
                )
        except (AssertionError, ValueError) as exc:
            failures.append(str(exc))
        if (workspace / "unsafe-sentinel").exists() or (
            victim / ".codememory/codememory.sqlite3"
        ).exists():
            failures.append("denied operation changed isolated victim state")
        if probe.child_index < 2 or probe.index < len(probe.steps):
            failures.append(
                f"research/workflow incomplete: child={probe.child_index}, parent={probe.index}/{len(probe.steps)}"
            )
        outcomes = [
            {
                "tool": e.get("part", {}).get("tool"),
                "command": e.get("part", {})
                .get("state", {})
                .get("input", {})
                .get("command"),
                "status": e.get("part", {}).get("state", {}).get("status"),
                "error": e.get("part", {}).get("state", {}).get("error"),
                "output": str(e.get("part", {}).get("state", {}).get("output", ""))[
                    :700
                ],
            }
            for e in events
            if e.get("type") == "tool_use"
        ]
        detail = {
            "audit_exists": audit_path.exists(),
            "audit_fields": list(audit[0]) if audit else [],
            "tool_outcomes": outcomes if failures else [],
            "result": "FAIL" if failures else "PASS",
            "controlled_provider": True,
            "actual_opencode_and_codememory": True,
            "parent_steps": probe.index,
            "research_steps": probe.child_index,
            "guard_reasons": sorted(reasons),
            "failures": failures,
        }
    detail["temporary_root_removed"] = not root.exists()
    detail["host_codememory_unchanged"] = before == sandbox.snapshot_tree(
        sandbox.REPO_ROOT / ".codememory"
    )
    if not detail["temporary_root_removed"] or not detail["host_codememory_unchanged"]:
        detail["result"] = "FAIL"
    return detail


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-ms", type=int, default=180000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        payload = run(args.timeout_ms)
    except (
        ValueError,
        OSError,
        AssertionError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as exc:
        payload = {"result": "FAIL", "failures": [str(exc)]}
    print(json.dumps(payload, indent=2))
    return 0 if payload["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
