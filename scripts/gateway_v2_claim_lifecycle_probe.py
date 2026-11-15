"""Measure native V2 execution claims in a private synthetic runtime only."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import gateway_v2_auxiliary_redaction_probe as auxiliary
import gateway_v2_native_settlement_probe as native
from gateway_v2_dependency_contract_probe import (
    ProbeFailure,
    child_env,
    preflight,
    run_child,
)
from gateway_v2_dependency_profile_probe import (
    PrivateRuntime,
    activated_inventory,
    native_id,
    owned_fixture,
    wait_until,
)

ROOT = Path(__file__).resolve().parent.parent
READ_SECONDS = 2.0
STAGES = ("initial", "active", "peer_completed", "interrupted")
STATE_KEYS = {"claimed", "busy_recorded", "idle_recorded", "resume_attempts"}


@dataclass
class Evidence:
    target: str | None = None
    peer: str | None = None
    observations: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)


def fixture_plugin(port: int, key: str) -> str:
    source = r'''
import { Plugin } from "@opencode/plugin"
const base = __BASE__, key = __KEY__
const headers = {Authorization:`Bearer ${key}`}
const record = async row => {
  const r = await fetch(base + "/trace", {method:"POST",headers:{...headers,"Content-Type":"application/json"},body:JSON.stringify(row)})
  if (!r.ok) throw new Error("TRACE_FAILED")
}
const gate = async name => {
  const r = await fetch(base + "/gate/" + name,{headers})
  if (!r.ok || (await r.json()).command !== "continue") throw new Error("GATE_FAILED")
}
export default Plugin.define({id:"profile-owned", async setup(ctx) {
  let target
  const pre = await ctx.session.hook("context", async event => {
    if (!target) target = event.sessionID
    if (event.sessionID === target) {
      await record({phase:"target_context",sessionID:event.sessionID})
      await gate("pre1")
      return
    }
    await record({phase:"peer_context",sessionID:event.sessionID})
  })
  void (async () => {
    await gate("trigger1")
    const result = await ctx.session.interrupt({sessionID:target,resume:false})
    await record({phase:"interrupt",sessionID:target,accepted:result?.interrupted === true})
    await ctx.session.wait({sessionID:target})
    await record({phase:"wait_return",sessionID:target})
  })().catch(() => { void record({phase:"fixture_fault"}).catch(() => {}) })
  await record({phase:"ready",version:ctx.app.version})
  return () => pre.dispose()
} })
'''
    return source.replace("__BASE__", json.dumps(f"http://127.0.0.1:{port}")).replace(
        "__KEY__", json.dumps(key)
    )


def prepare_fixture(
    root: Path, port: int, key: str, provider_key: str, *, protected: bool,
) -> dict[str, Any]:
    return auxiliary.prepare_fixture(
        root, port, key, provider_key, protected=protected,
        plugin_source=fixture_plugin(port, key),
    )


def _owned_database(path: Path) -> tuple[int, int]:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise ProbeFailure("synthetic_database_identity_invalid")
    return metadata.st_dev, metadata.st_ino


def _owned_root(root: Path) -> tuple[int, int]:
    metadata = root.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise ProbeFailure("synthetic_root_identity_invalid")
    return metadata.st_dev, metadata.st_ino


def read_claims(root: Path, target: str, peer: str, deadline: float) -> dict[str, dict[str, Any]]:
    """Read only fixture rows; a SQLite WAL reader may update fixture SHM bytes."""
    if target == peer:
        raise ProbeFailure("session_identity_collision")
    native_id(target)
    native_id(peer)
    path = root / "runtime.sqlite"
    connection: sqlite3.Connection | None = None
    try:
        root_identity = _owned_root(root)
        identity = _owned_database(path)
        remaining = min(READ_SECONDS, deadline - time.monotonic())
        if remaining <= 0:
            raise ProbeFailure("claim_read_timeout")
        read_deadline = time.monotonic() + remaining
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=remaining)
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA query_only").fetchone() != (1,):
            raise ProbeFailure("query_only_unavailable")
        connection.set_progress_handler(lambda: int(time.monotonic() >= read_deadline), 1000)
        connection.execute("BEGIN")
        schema = connection.execute(
            "SELECT type, sql FROM main.sqlite_master WHERE name = ? COLLATE NOCASE",
            ("session_v2",),
        ).fetchall()
        if (
            len(schema) != 1 or schema[0][0] != "table" or not isinstance(schema[0][1], str)
            or not schema[0][1].lstrip().upper().startswith("CREATE TABLE")
        ):
            raise ProbeFailure("native_schema_invalid")
        result: dict[str, dict[str, Any]] = {}
        for label, session_id in (("target", target), ("peer", peer)):
            rows = connection.execute(
                "SELECT time_suspended, time_busy, time_idle, resume_attempts "
                "FROM main.session_v2 WHERE id = ? LIMIT 2",
                (session_id,),
            ).fetchall()
            if (
                len(rows) != 1 or len(rows[0]) != 4
                or any(value is not None and (type(value) is not int or value < 0) for value in rows[0])
                or type(rows[0][3]) is not int
            ):
                raise ProbeFailure("native_claim_row_invalid")
            claim, busy, idle, attempts = rows[0]
            result[label] = {
                "claimed": claim is not None, "busy_recorded": busy is not None,
                "idle_recorded": idle is not None, "resume_attempts": attempts,
            }
        if time.monotonic() >= read_deadline:
            raise ProbeFailure("claim_read_timeout")
        connection.rollback()
        if _owned_root(root) != root_identity or _owned_database(path) != identity:
            raise ProbeFailure("synthetic_database_identity_changed")
        return result
    except (OSError, sqlite3.Error, ValueError) as error:
        raise ProbeFailure("claim_read_failed") from error
    finally:
        if connection is not None:
            connection.close()


def exercise(
    runtime: PrivateRuntime, root: Path, config: dict[str, Any], state: native.NativeState,
    evidence: Evidence,
) -> None:
    def seen(phase: str) -> bool:
        with state.lock:
            if any(row.get("phase") == "fixture_fault" for row in state.trace_rows):
                state.failure = state.failure or "fixture_fault"
            return any(row.get("phase") == phase for row in state.trace_rows)

    def until(phase: str) -> None:
        wait_until(lambda: seen(phase), state, f"missing_{phase}")

    def arrived(name: str) -> None:
        wait_until(state.gates[name].arrived.is_set, state, f"missing_gate_{name}")

    def verify_identity(phase: str, session_id: str, *, accepted: bool = False) -> None:
        with state.lock:
            matches = [row for row in state.trace_rows if row.get("phase") == phase]
            if not matches or any(row.get("sessionID") != session_id for row in matches):
                raise ProbeFailure("trace_identity_mismatch")
            if accepted and (len(matches) != 1 or matches[0].get("accepted") is not True):
                raise ProbeFailure("interrupt_not_accepted")

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
    evidence.target, evidence.peer = target, peer

    def observe(stage: str) -> None:
        evidence.observations[stage] = read_claims(root, target, peer, state.deadline)

    observe("initial")
    runtime.mutate("POST", f"/api/session/{target}/prompt", {"text": "SYNTHETIC_CLAIM_TARGET"})
    arrived("pre1")
    until("target_context")
    verify_identity("target_context", target)
    observe("active")
    runtime.mutate("POST", f"/api/session/{peer}/prompt", {"text": f"{auxiliary.MESSAGE_MARKER} SYNTHETIC_CLAIM_PEER"})
    runtime.mutate("POST", f"/api/experimental/session/{peer}/wait")
    until("peer_context")
    verify_identity("peer_context", peer)

    def peer_observed() -> bool:
        with state.lock:
            return any(item.get("message_marker") is True for item in state.observations) and state.responses == state.requests

    wait_until(peer_observed, state, "peer_provider_missing")
    observe("peer_completed")
    arrived("trigger1")
    state.gates["trigger1"].release()
    until("interrupt")
    verify_identity("interrupt", target, accepted=True)
    state.gates["pre1"].release()
    until("wait_return")
    verify_identity("wait_return", target)
    observe("interrupted")


def assess(
    mode: str, rows: list[dict[str, Any]], requests: list[dict[str, Any]], evidence: Evidence,
) -> dict[str, int]:
    if (
        mode != "native" or not isinstance(rows, list) or not isinstance(requests, list)
        or not rows or len(rows) > auxiliary.MAX_TRACE_ROWS
        or not requests or len(requests) > auxiliary.MAX_CONNECTIONS
        or not isinstance(evidence.target, str) or not isinstance(evidence.peer, str)
        or evidence.target == evidence.peer
    ):
        raise ProbeFailure("observation_schema_invalid")
    shapes = {
        "ready": {"phase", "version"},
        "target_context": {"phase", "sessionID"},
        "peer_context": {"phase", "sessionID"},
        "interrupt": {"phase", "sessionID", "accepted"},
        "wait_return": {"phase", "sessionID"},
    }
    for row in rows:
        if (
            not isinstance(row, dict) or not isinstance(row.get("phase"), str)
            or row["phase"] not in shapes or set(row) != shapes[row["phase"]]
        ):
            raise ProbeFailure("trace_schema_invalid")
        if row["phase"] in ("target_context", "interrupt", "wait_return") and row["sessionID"] != evidence.target:
            raise ProbeFailure("target_identity_mismatch")
        if row["phase"] == "peer_context" and row["sessionID"] != evidence.peer:
            raise ProbeFailure("peer_identity_mismatch")
    def one(phase: str) -> dict[str, Any]:
        matches = [row for row in rows if row["phase"] == phase]
        if len(matches) != 1:
            raise ProbeFailure("trace_count_invalid")
        return matches[0]

    ready, target, interrupted, waited = (one(phase) for phase in ("ready", "target_context", "interrupt", "wait_return"))
    if ready != {"phase": "ready", "version": "2.2.5"}:
        raise ProbeFailure("plugin_ready_invalid")
    if interrupted["accepted"] is not True:
        raise ProbeFailure("interrupt_not_accepted")
    peers = [row for row in rows if row["phase"] == "peer_context"]
    if not peers:
        raise ProbeFailure("peer_context_missing")
    indices = [rows.index(row) for row in (ready, target, peers[0], interrupted, waited)]
    if indices != sorted(indices):
        raise ProbeFailure("native_order_mismatch")
    request_keys = {"markers", "system_canary", "message_canary", "message_marker", "redacted"}
    for request in requests:
        if (
            not isinstance(request, dict) or set(request) != request_keys
            or not isinstance(request["markers"], list)
            or any(not isinstance(item, str) or item not in auxiliary.KINDS for item in request["markers"])
            or len(set(request["markers"])) != len(request["markers"])
            or any(type(request[key]) is not bool for key in request_keys - {"markers"})
        ):
            raise ProbeFailure("provider_observation_invalid")
    peer_requests = sum(item["message_marker"] is True for item in requests)
    if peer_requests < 1:
        raise ProbeFailure("peer_provider_missing")
    validate_observations(evidence.observations)
    return {"peer_provider": peer_requests}


def validate_observations(observations: dict[str, dict[str, dict[str, Any]]]) -> None:
    if not isinstance(observations, dict) or set(observations) != set(STAGES):
        raise ProbeFailure("claim_observation_invalid")
    for stage in STAGES:
        data = observations[stage]
        if not isinstance(data, dict) or set(data) != {"target", "peer"}:
            raise ProbeFailure("claim_observation_invalid")
        for value in data.values():
            if (
                not isinstance(value, dict) or set(value) != STATE_KEYS
                or any(type(value[key]) is not bool for key in STATE_KEYS - {"resume_attempts"})
                or type(value["resume_attempts"]) is not int or value["resume_attempts"] != 0
            ):
                raise ProbeFailure("claim_observation_invalid")
    def observed(claimed: bool, busy: bool, idle: bool) -> dict[str, Any]:
        return {"claimed": claimed, "busy_recorded": busy, "idle_recorded": idle, "resume_attempts": 0}

    initial = observed(False, False, False)
    running = observed(True, True, False)
    terminal = observed(False, True, True)
    expected = {
        "initial": {"target": initial, "peer": initial},
        "active": {"target": running, "peer": initial},
        "peer_completed": {"target": running, "peer": terminal},
        "interrupted": {"target": terminal, "peer": terminal},
    }
    if observations != expected:
        raise ProbeFailure("claim_state_mismatch")


def probe(binary: str, parent: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "measurement": "FAIL", "authority": "disabled-unqualified",
        "scope": "synthetic-unregistered-server-only", "version_teardown_complete": False,
    }
    try:
        if os.name != "posix" or not hasattr(os, "getuid"):
            raise ProbeFailure("platform_unsupported")
        preflight(parent)
        path = Path(binary)
        identity, digest = native._file_digest(path)
        report["binary_sha256"] = digest
        version_root = Path(tempfile.mkdtemp(prefix="v2-claim-version-", dir=parent))
        report["version_fixture"] = version_root.name
        version_identity = version_root.lstat()
        try:
            code, output, _ = run_child([binary, "--version"], version_root, child_env(version_root), timeout=10)
            report["version_teardown_complete"] = True
        finally:
            if not owned_fixture(version_root, version_identity):
                raise ProbeFailure("version_fixture_identity_changed")
        if code != 0 or output.decode().strip() != "opencode v2.2.5":
            raise ProbeFailure("unsupported_host_version")
        evidence = Evidence()
        hooks = auxiliary.CaseHooks(
            native.NativeState, native.NativeProvider, prepare_fixture,
            lambda runtime, root, config, state: exercise(runtime, root, config, state, evidence),
            lambda mode, rows, requests: assess(mode, rows, requests, evidence),
            prefix="v2-claim-lifecycle-",
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
        if native._file_digest(path) != (identity, digest):
            raise ProbeFailure("executable_changed")
        validate_observations(evidence.observations)
        report["observations"] = evidence.observations
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
