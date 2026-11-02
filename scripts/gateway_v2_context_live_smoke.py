"""Exercise the experimental V2 context adapter against a localhost provider.

This does not validate the complete gateway or provider boundary.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from gateway_secret_redaction_live_smoke import (
    CaptureHandler,
    CaptureState,
    isolated_env,
)
from session_command import _repair_runtime_stuck_sessions, _scan_runtime_stuck_sessions

ROOT = Path(__file__).resolve().parent.parent
CANARY = "V2SyntheticSecret_123456789"


def main() -> int:
    dist = ROOT / "plugin/gateway-core/dist"
    if not (dist / "v2/provider-boundary.js").is_file():
        print("FAIL: build gateway-core first")
        return 1
    server = ThreadingHTTPServer(("127.0.0.1", 0), CaptureHandler)
    state = CaptureState()
    server.capture_state = state
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="gateway-v2-context-") as temp:
            root = Path(temp)
            home, project = root / "home", root / "project"
            plugin = project / "v2-probe"
            plugin.mkdir(parents=True)
            (plugin / "index.ts").write_text(
                'import { Plugin } from "@opencode/plugin"\n'
                f"import {{ registerV2ContextRedaction, registerV2TransportRedaction }} from {json.dumps((dist / 'v2/provider-boundary.js').as_uri())}\n"
                f"import {{ createSecretRedactor }} from {json.dumps((dist / 'hooks/shared/secret-redaction.js').as_uri())}\n"
                'export default Plugin.define({ id: "v2-context-probe", async setup(ctx) {\n'
                f'  const redactor = createSecretRedactor({{ patterns: [{json.dumps(CANARY)}], redactionToken: "[REDACTED]", limits: {{ maxDepth: 64, maxNodes: 100000, maxChars: 5000000 }} }})\n'
                "  const disposeContext = await registerV2ContextRedaction(ctx.session, redactor)\n"
                f'  await ctx.session.hook("context", (event) => event.system.push({{ type: "text", text: "late-marker {CANARY}" }}))\n'
                '  if (process.env.V2_TEST_BAD_CONTENT === "1") await ctx.session.hook("http.request", (event) => { const headers = new Headers(event.request.headers); headers.set("content-type", "text/plain"); event.request = new Request(event.request, { headers }) })\n'
                "  const disposeTransport = await registerV2TransportRedaction(ctx.session, redactor)\n"
                "  return async () => { await disposeTransport(); await disposeContext() }\n"
                "} })\n",
                encoding="utf-8",
            )
            config = {
                "model": "capture/mock",
                "plugins": [str(plugin)],
                "providers": {
                    "capture": {
                        "name": "Local capture",
                        "package": "@opencode/ai/providers/openai-compatible",
                        "settings": {
                            "baseURL": f"http://127.0.0.1:{server.server_port}/v1",
                            "apiKey": "local-test-only",
                        },
                        "models": {"mock": {"name": "mock"}},
                    }
                },
            }
            config_path = project / "opencode.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            env = isolated_env(home, root / "audit.jsonl")
            env.pop("OPENCODE_SESSION_ID", None)
            result = subprocess.run(
                [
                    "opencode",
                    "run",
                    "--standalone",
                    "--model",
                    "capture/mock",
                    f"Reply MOCK_OK. {CANARY} control-marker",
                ],
                cwd=project,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            with state.lock:
                captured = json.dumps(state.requests)
                request_count = len(state.requests)
            env["V2_TEST_BAD_CONTENT"] = "1"
            negative = subprocess.run(
                [
                    "opencode",
                    "run",
                    "--standalone",
                    "--model",
                    "capture/mock",
                    f"Reply MOCK_OK. {CANARY} negative-control",
                ],
                cwd=project,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            with state.lock:
                negative_requests = len(state.requests) - request_count
            negative_failed_closed = (
                negative_requests == 0
                and "refusing unscanned request" in (negative.stderr + negative.stdout)
            )
            # The installed configuration still uses legacy AI SDK providers.
            env.pop("V2_TEST_BAD_CONTENT")
            config["providers"]["capture"]["package"] = (
                "aisdk:@ai-sdk/openai-compatible"
            )
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with state.lock:
                before_aisdk = len(state.requests)
            aisdk = subprocess.run(
                [
                    "opencode",
                    "run",
                    "--standalone",
                    "--model",
                    "capture/mock",
                    f"Reply MOCK_OK. {CANARY} aisdk-control-marker",
                ],
                cwd=project,
                env=env,
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            with state.lock:
                aisdk_requests = list(state.requests[before_aisdk:])
            aisdk_captured = json.dumps(aisdk_requests)
            aisdk_protected = (
                aisdk.returncode == 0
                and bool(aisdk_requests)
                and CANARY not in aisdk_captured
                and "late-marker [REDACTED]" in aisdk_captured
                and "aisdk-control-marker" in aisdk_captured
            )
            database_tables = {}
            v2_columns = {}
            for database in home.rglob("*.db"):
                try:
                    connection = sqlite3.connect(
                        f"{database.as_uri()}?mode=ro", uri=True
                    )
                    try:
                        database_tables[str(database.relative_to(home))] = [
                            row[0]
                            for row in connection.execute(
                                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
                            )
                        ]
                        for table in ("session_v2", "session_message", "session_part"):
                            v2_columns[table] = [
                                row[1] for row in connection.execute(f"PRAGMA table_info({table})")
                            ]
                    finally:
                        connection.close()
                except sqlite3.Error:
                    database_tables[str(database.relative_to(home))] = ["unreadable"]
            runtime_db = home / ".local" / "share" / "opencode" / "opencode.db"
            runtime_probe_safe = False
            if runtime_db.is_file():
                before_digest = hashlib.sha256(runtime_db.read_bytes()).hexdigest()
                scan = _scan_runtime_stuck_sessions(runtime_db, 300)
                repair = _repair_runtime_stuck_sessions(
                    runtime_db,
                    300,
                    apply_changes=True,
                    include_generic=True,
                    scope_session_id="synthetic-v2",
                )
                runtime_probe_safe = (
                    scan.get("runtime_db_v2_detected") is True
                    and scan.get("runtime_db_scan_mode") == "incompatible"
                    and bool(repair.get("problems"))
                    and repair.get("repaired_count") == 0
                    and repair.get("backup_path") is None
                    and hashlib.sha256(runtime_db.read_bytes()).hexdigest()
                    == before_digest
                )
            passed = (
                result.returncode == 0
                and request_count > 0
                and CANARY not in captured
                and "[REDACTED]" in captured
                and "control-marker" in captured
                and "late-marker [REDACTED]" in captured
                and negative_failed_closed
                and aisdk_protected
                and runtime_probe_safe
            )
            print(
                json.dumps(
                    {
                        "result": "PASS" if passed else "FAIL",
                        "returncode": result.returncode,
                        "request_count": request_count,
                        "canary_absent": CANARY not in captured,
                        "redaction_present": "[REDACTED]" in captured,
                        "control_present": "control-marker" in captured,
                        "late_injection_redacted": "late-marker [REDACTED]" in captured,
                        "unsupported_content_blocked": negative_failed_closed,
                        "negative_request_count": negative_requests,
                        "aisdk_protected": aisdk_protected,
                        "aisdk_request_count": len(aisdk_requests),
                        "isolated_databases": database_tables,
                        "isolated_v2_columns": v2_columns,
                        "v2_legacy_repair_refused": runtime_probe_safe,
                    }
                )
            )
            if not passed:
                print(
                    (result.stderr + "\n" + result.stdout).replace(CANARY, "[CANARY]")[
                        -4000:
                    ]
                )
                print(
                    (negative.stderr + "\n" + negative.stdout).replace(
                        CANARY, "[CANARY]"
                    )[-4000:]
                )
                print(
                    (aisdk.stderr + "\n" + aisdk.stdout).replace(CANARY, "[CANARY]")[
                        -4000:
                    ]
                )
            return 0 if passed else 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
