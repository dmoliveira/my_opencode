import assert from "node:assert/strict"
import { mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { loadGatewayState, saveGatewayState } from "../dist/state/storage.js"

test("stale-loop-expiry-guard deactivates stale active loop", async () => {
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  const directory = mkdtempSync(join(tmpdir(), "gateway-stale-loop-"))
  try {
    saveGatewayState(directory, {
      activeLoop: {
        active: true,
        sessionId: "session-stale",
        objective: "do work",
        completionMode: "promise",
        completionPromise: "DONE",
        iteration: 5,
        maxIterations: 0,
        startedAt: new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString(),
      },
      lastUpdatedAt: new Date().toISOString(),
      source: "test",
    })
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["stale-loop-expiry-guard"],
          disabled: ["continuation"],
        },
        staleLoopExpiryGuard: {
          enabled: true,
          maxAgeMinutes: 60,
        },
      },
    })
    await plugin.event({ event: { type: "session.idle", properties: { sessionID: "session-stale" } } })
    const state = loadGatewayState(directory)
    assert.equal(state?.activeLoop?.active, false)
    const events = readFileSync(join(directory, ".opencode", "gateway-events.jsonl"), "utf-8")
      .split(/\n+/)
      .filter(Boolean)
      .map((line) => JSON.parse(line))
    assert.ok(events.some((entry) => entry.reason_code === "stale_loop_expired"))
  } finally {
    rmSync(directory, { recursive: true, force: true })
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    }
  }
})
