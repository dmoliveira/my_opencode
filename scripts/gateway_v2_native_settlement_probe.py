"""Measure native V2 interruption/wait ordering, without enabling authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import gateway_v2_auxiliary_redaction_probe as auxiliary
from gateway_v2_dependency_contract_probe import (
    ProbeFailure,
    child_env,
    preflight,
    run_child,
)
from gateway_v2_dependency_profile_probe import (
    Barrier,
    PrivateRuntime,
    activated_inventory,
    native_id,
    owned_fixture,
    wait_until,
)

ROOT = Path(__file__).resolve().parent.parent
GATES = ("pre1", "pre2", "trigger1", "trigger2", "wait1", "wait2", "observe", "finish")
MAX_ADMISSIONS = 64
PEER_MARKER = auxiliary.MESSAGE_MARKER


@dataclass
class NativeState(auxiliary.CaptureState):
    gates: dict[str, Barrier] = field(default_factory=lambda: {name: Barrier() for name in GATES})

    def stop(self) -> None:
        super().stop()
        for gate in self.gates.values():
            gate.release("stop")


class NativeHandler(auxiliary.CaptureHandler):
    def do_GET(self) -> None:
        state: NativeState = self.started()  # type: ignore[assignment]
        try:
            if self.headers.get("Authorization") != f"Bearer {state.control_key}":
                raise ProbeFailure("control_authentication_failed")
            name = self.path.removeprefix("/gate/")
            if self.path != f"/gate/{name}" or name not in state.gates:
                raise ProbeFailure("unexpected_control_path")
            command = state.gates[name].hold(state.deadline, state.stopped)
            self.reply(json.dumps({"command": command}).encode())
        except (ProbeFailure, OSError) as error:
            if not state.stopped.is_set():
                state.failure = str(error) if isinstance(error, ProbeFailure) else "gate_connection_failed"
                try:
                    self.send_error(400)
                except OSError:
                    pass


class NativeProvider(auxiliary.CaptureProvider):
    def __init__(self, state: NativeState):
        super().__init__(state)
        self.RequestHandlerClass = NativeHandler

    def verify_request(self, request: socket.socket, client_address: Any) -> bool:
        del client_address
        if self.state.stopped.is_set():
            return False
        self.admissions += 1
        request.settimeout(12)
        if self.admissions > MAX_ADMISSIONS:
            self.state.failure = "provider_connection_limit"
            return False
        self.admitted.append(request)
        return True


def fixture_plugin(port: int, key: str) -> str:
    """Inject error events but delegate interruption and waiting to the host."""
    source = r'''
import { Plugin } from "@opencode/plugin"
import { Error as ToolError } from "@opencode/plugin/promise/tool"
import { registerV2InterruptingToolOutputRedaction } from __ADAPTER__
const base = __BASE__, key = __KEY__
const auth = {Authorization:`Bearer ${key}`}
const record = async row => {
  const response = await fetch(base + "/trace", {method:"POST", headers:{...auth,"Content-Type":"application/json"}, body:JSON.stringify(row)})
  if (!response.ok) throw new Error("TRACE_FAILED")
}
const gate = async name => {
  const response = await fetch(base + "/gate/" + name, {headers:auth})
  if (!response.ok) throw new Error("GATE_FAILED")
  const body = await response.json()
  if (body.command !== "continue") throw new Error("GATE_STOPPED")
}
const tick = () => new Promise(done => setTimeout(done, 0))
export default Plugin.define({id:"profile-owned", async setup(ctx) {
  let target, contexts = 0, after, interrupts = 0, waits = 0
  const guards = {}
  const pre = await ctx.session.hook("context", async event => {
    if (!target) target = event.sessionID
    if (event.sessionID !== target) { await record({phase:"peer_context"}); return }
    const n = ++contexts
    await record({phase:"target_context", n})
    if (n <= 2) await gate("pre" + n)
  })
  const session = {
    async hook(name, callback) { guards[name] = callback; return ctx.session.hook(name, callback) },
    async interrupt(input) {
      const n = ++interrupts
      const result = await ctx.session.interrupt(input)
      await record({phase:"native_interrupt", n, accepted:result?.interrupted === true, target:input.sessionID === target})
      return result
    },
    async wait(input) {
      const n = ++waits
      await record({phase:"wait_start", n, target:input.sessionID === target})
      await ctx.session.wait(input)
      await record({phase:"wait_native_return", n})
      await gate("wait" + n)
      await record({phase:"wait_delivered", n})
    },
  }
  const tool = { async hook(name, callback) { after = callback; return ctx.tool.hook(name, callback) } }
  const dispose = await registerV2InterruptingToolOutputRedaction(session, tool, {async redactMutableValueAsync() {}}, message => new ToolError({message}), ctx.app.version)
  const blocked = async (kind, id) => { try { await guards[kind]({sessionID:id}); return false } catch { return true } }
  const event = () => ({sessionID:target, status:"error", error:{error:{_tag:"Permission.DeclinedError"}}})
  void (async () => {
    await gate("trigger1"); await after(event()); await record({phase:"after_return", n:1})
    await gate("trigger2"); await after(event()); await record({phase:"after_return", n:2})
    await gate("observe"); await tick(); await tick()
    let allBlocked = true, peerUnaffected = true
    for (const name of ["context", "compaction", "generate", "title", "http.request", "experimental.ws.send"]) {
      allBlocked = (await blocked(name, target)) && allBlocked
      peerUnaffected = !(await blocked(name, "synthetic-peer")) && peerUnaffected
    }
    await record({phase:"guards", allBlocked, peerUnaffected, waits})
    await gate("finish")
    let released = false
    for (let attempt = 0; attempt < 100; attempt++) {
      if (!(await blocked("context", target))) { released = true; break }
      await new Promise(done => setTimeout(done, 10))
    }
    await record({phase:"released", target:released})
  })().catch(() => { void record({phase:"fixture_fault"}).catch(() => {}) })
  await record({phase:"ready", version:ctx.app.version})
  return async () => { await pre.dispose(); await dispose() }
} })
'''
    replacements = {
        "__ADAPTER__": (ROOT / "plugin/gateway-core/dist/v2/tool-output-redaction.js").as_uri(),
        "__BASE__": f"http://127.0.0.1:{port}",
        "__KEY__": key,
    }
    for name, value in replacements.items():
        source = source.replace(name, json.dumps(value))
    return source


def prepare_fixture(
    root: Path, port: int, key: str, provider_key: str, *, protected: bool,
) -> dict[str, Any]:
    return auxiliary.prepare_fixture(
        root, port, key, provider_key, protected=protected,
        plugin_source=fixture_plugin(port, key),
    )


def exercise(runtime: PrivateRuntime, root: Path, config: dict[str, Any], state: NativeState) -> None:
    def seen(phase: str, n: int | None = None) -> bool:
        with state.lock:
            if any(row.get("phase") == "fixture_fault" for row in state.trace_rows):
                state.failure = state.failure or "fixture_fault"
            if any(row.get("phase") == "native_interrupt" and row.get("accepted") is not True for row in state.trace_rows):
                state.failure = state.failure or "native_interrupt_not_accepted"
            return any(row.get("phase") == phase and (n is None or row.get("n") == n) for row in state.trace_rows)

    def until(phase: str, n: int | None = None) -> None:
        wait_until(lambda: seen(phase, n), state, f"missing_{phase}_{n}")

    def gate_arrived(name: str) -> None:
        wait_until(state.gates[name].arrived.is_set, state, f"missing_gate_{name}")

    runtime.ready()
    inventory = activated_inventory(runtime, root)
    owned = [item for item in inventory if item.get("source") == "owned"]
    if len(owned) != 1 or owned[0].get("status") != "active" or config.get("plugins") != [str(root / "project/owned")]:
        raise ProbeFailure("fixture_plugin_not_active")
    if any(item.get("source") not in ("builtin", "owned") for item in inventory):
        raise ProbeFailure("unexpected_plugin_topology")

    def create() -> str:
        result = runtime.mutate("POST", "/api/session", {
            "location": {"directory": str(root / "project")},
            "model": {"providerID": "probe", "id": "mock"}, "agent": "build",
        })
        return native_id(result["data"]["id"])

    target, peer = create(), create()
    if target == peer:
        raise ProbeFailure("session_identity_collision")
    runtime.mutate("POST", f"/api/session/{target}/prompt", {"text": "SYNTHETIC_NATIVE_FIRST"})
    gate_arrived("pre1")
    gate_arrived("trigger1")
    state.gates["trigger1"].release()
    until("native_interrupt", 1)
    until("after_return", 1)
    state.gates["pre1"].release()
    until("wait_native_return", 1)
    gate_arrived("wait1")
    runtime.mutate("POST", f"/api/session/{peer}/prompt", {"text": f"{PEER_MARKER} SYNTHETIC_NATIVE_PEER"})
    runtime.mutate("POST", f"/api/experimental/session/{peer}/wait")
    until("peer_context")

    def peer_observed() -> bool:
        with state.lock:
            return any(item.get("message_marker") is True for item in state.observations) and state.responses == state.requests

    wait_until(peer_observed, state, "peer_provider_missing")
    runtime.mutate("POST", f"/api/session/{target}/prompt", {"text": "SYNTHETIC_NATIVE_SECOND"})
    gate_arrived("pre2")
    gate_arrived("trigger2")
    state.gates["trigger2"].release()
    until("native_interrupt", 2)
    until("after_return", 2)
    state.gates["pre2"].release()
    state.gates["wait1"].release()
    until("wait_delivered", 1)
    until("wait_native_return", 2)
    gate_arrived("wait2")
    gate_arrived("observe")
    state.gates["observe"].release()
    until("guards")
    state.gates["wait2"].release()
    until("wait_delivered", 2)
    gate_arrived("finish")
    state.gates["finish"].release()
    until("released")


def assess(mode: str, rows: list[dict[str, Any]], requests: list[dict[str, Any]]) -> dict[str, int]:
    if mode != "native" or not isinstance(rows, list) or not isinstance(requests, list):
        raise ProbeFailure("observation_schema_invalid")
    shapes = {
        "ready": {"phase", "version"},
        "target_context": {"phase", "n"},
        "peer_context": {"phase"},
        "native_interrupt": {"phase", "n", "accepted", "target"},
        "after_return": {"phase", "n"},
        "wait_start": {"phase", "n", "target"},
        "wait_native_return": {"phase", "n"},
        "wait_delivered": {"phase", "n"},
        "guards": {"phase", "allBlocked", "peerUnaffected", "waits"},
        "released": {"phase", "target"},
    }
    if not rows or len(rows) > auxiliary.MAX_TRACE_ROWS:
        raise ProbeFailure("trace_size_invalid")
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("phase"), str) or row["phase"] not in shapes or set(row) != shapes[row["phase"]]:
            raise ProbeFailure("trace_schema_invalid")
        if "n" in row and (type(row["n"]) is not int or row["n"] not in (1, 2)):
            raise ProbeFailure("trace_sequence_invalid")
        for key in ("accepted", "target", "allBlocked", "peerUnaffected"):
            if key in row and type(row[key]) is not bool:
                raise ProbeFailure("trace_boolean_invalid")
        if "waits" in row and type(row["waits"]) is not int:
            raise ProbeFailure("trace_sequence_invalid")

    def one(phase: str, n: int | None = None) -> dict[str, Any]:
        matches = [row for row in rows if row["phase"] == phase and (n is None or row.get("n") == n)]
        if len(matches) != 1:
            raise ProbeFailure("trace_count_invalid")
        return matches[0]

    ready = one("ready")
    if ready != {"phase": "ready", "version": "2.2.5"}:
        raise ProbeFailure("plugin_ready_invalid")
    for n in (1, 2):
        if one("native_interrupt", n) != {"phase": "native_interrupt", "n": n, "accepted": True, "target": True}:
            raise ProbeFailure("native_interrupt_not_accepted")
        if one("wait_start", n) != {"phase": "wait_start", "n": n, "target": True}:
            raise ProbeFailure("wait_identity_mismatch")
        one("target_context", n)
        one("after_return", n)
        one("wait_native_return", n)
        one("wait_delivered", n)
    if one("guards") != {"phase": "guards", "allBlocked": True, "peerUnaffected": True, "waits": 2}:
        raise ProbeFailure("guard_state_mismatch")
    if one("released") != {"phase": "released", "target": True}:
        raise ProbeFailure("guard_release_missing")
    peers = [row for row in rows if row["phase"] == "peer_context"]
    if not peers:
        raise ProbeFailure("peer_context_missing")
    ordered = [
        ready, one("target_context", 1), one("native_interrupt", 1), one("wait_start", 1),
        one("wait_native_return", 1), peers[0], one("target_context", 2),
        one("native_interrupt", 2), one("after_return", 2), one("wait_delivered", 1),
        one("wait_start", 2), one("wait_native_return", 2), one("guards"),
        one("wait_delivered", 2), one("released"),
    ]
    indexes = [rows.index(row) for row in ordered]
    if indexes != sorted(indexes) or not (
        rows.index(one("native_interrupt", 1)) < rows.index(one("after_return", 1)) < rows.index(one("target_context", 2))
    ):
        raise ProbeFailure("native_order_mismatch")
    expected_request = {"markers", "system_canary", "message_canary", "message_marker", "redacted"}
    if not requests or len(requests) > 16:
        raise ProbeFailure("provider_observation_invalid")
    for request in requests:
        if not isinstance(request, dict) or set(request) != expected_request or not isinstance(request["markers"], list):
            raise ProbeFailure("provider_observation_invalid")
        if any(not isinstance(item, str) or item not in auxiliary.KINDS for item in request["markers"]) or len(set(request["markers"])) != len(request["markers"]):
            raise ProbeFailure("provider_observation_invalid")
        if any(type(request[key]) is not bool for key in expected_request - {"markers"}):
            raise ProbeFailure("provider_observation_invalid")
    peer_requests = sum(item["message_marker"] is True for item in requests)
    if peer_requests < 1:
        raise ProbeFailure("peer_provider_missing")
    return {"peer_provider": peer_requests}


def _file_digest(path: Path) -> tuple[tuple[int, int, int], str]:
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 1024 * 1024 * 1024:
        raise ProbeFailure("file_identity_invalid")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return (metadata.st_dev, metadata.st_ino, metadata.st_size), digest


def probe(binary: str, parent: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "measurement": "FAIL", "authority": "disabled-unqualified",
        "scope": "native-interrupt-and-wait-with-injected-events-and-delayed-delivery",
        "version_teardown_complete": False,
    }
    try:
        preflight(parent)
        path = Path(binary)
        initial, digest = _file_digest(path)
        adapter = ROOT / "plugin/gateway-core/dist/v2/tool-output-redaction.js"
        adapter_initial, adapter_digest = _file_digest(adapter)
        report.update({"binary_sha256": digest, "adapter_sha256": adapter_digest})
        version_root = Path(tempfile.mkdtemp(prefix="v2-native-settlement-version-", dir=parent))
        report["version_fixture"] = version_root.name
        identity = version_root.lstat()
        try:
            code, output, _ = run_child([binary, "--version"], version_root, child_env(version_root), timeout=10)
            report["version_teardown_complete"] = True
        finally:
            if not owned_fixture(version_root, identity):
                raise ProbeFailure("version_fixture_identity_changed")
        if code != 0 or output.decode().strip() != "opencode v2.2.5":
            raise ProbeFailure("unsupported_host_version")
        hooks = auxiliary.CaseHooks(
            NativeState, NativeProvider, prepare_fixture, exercise, assess,
            prefix="v2-native-settlement-",
        )
        result = auxiliary.run_case(binary, parent, "native", hooks=hooks)
        report["case"] = result
        counts = result.get("provider_requests_by_kind")
        if (
            result.get("measurement") != "PASS" or result.get("teardown_complete") is not True
            or not isinstance(counts, dict) or set(counts) != {"peer_provider"}
            or type(counts["peer_provider"]) is not int or counts["peer_provider"] < 1
        ):
            raise ProbeFailure("case_failed")
        if _file_digest(path) != (initial, digest) or _file_digest(adapter) != (adapter_initial, adapter_digest):
            raise ProbeFailure("executable_or_adapter_changed")
        report["measurement"] = "PASS"
    except (ProbeFailure, OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        report["reason"] = str(error) if isinstance(error, ProbeFailure) else "probe_internal_error"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opencode-bin", default="opencode")
    parser.add_argument("--temp-parent", type=Path, default=Path(tempfile.gettempdir()))
    args = parser.parse_args()
    binary = shutil.which(args.opencode_bin)
    if binary is None:
        print(json.dumps({"measurement": "FAIL", "authority": "disabled-unqualified", "reason": "executable_unavailable"}))
        return 1
    report = probe(str(Path(binary).resolve()), args.temp_parent.absolute())
    print(json.dumps(report, sort_keys=True))
    return 0 if report["measurement"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
