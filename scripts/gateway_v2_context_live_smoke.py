"""Exercise the experimental V2 context adapter against a localhost provider.

This does not validate the complete gateway or provider boundary.
"""

from __future__ import annotations

import json
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
                f"import {{ registerV2ContextRedaction }} from {json.dumps((dist / 'v2/provider-boundary.js').as_uri())}\n"
                f"import {{ createSecretRedactor }} from {json.dumps((dist / 'hooks/shared/secret-redaction.js').as_uri())}\n"
                'export default Plugin.define({ id: "v2-context-probe", async setup(ctx) {\n'
                f'  const redactor = createSecretRedactor({{ patterns: [{json.dumps(CANARY)}], redactionToken: "[REDACTED]", limits: {{ maxDepth: 64, maxNodes: 100000, maxChars: 5000000 }} }})\n'
                "  return await registerV2ContextRedaction(ctx.session, redactor)\n"
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
            (project / "opencode.json").write_text(json.dumps(config), encoding="utf-8")
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
            passed = (
                result.returncode == 0
                and bool(state.requests)
                and CANARY not in captured
                and "[REDACTED]" in captured
                and "control-marker" in captured
            )
            print(
                json.dumps(
                    {
                        "result": "PASS" if passed else "FAIL",
                        "returncode": result.returncode,
                        "request_count": len(state.requests),
                        "canary_absent": CANARY not in captured,
                        "redaction_present": "[REDACTED]" in captured,
                        "control_present": "control-marker" in captured,
                    }
                )
            )
            if not passed:
                print(
                    (result.stderr + "\n" + result.stdout).replace(CANARY, "[CANARY]")[
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
