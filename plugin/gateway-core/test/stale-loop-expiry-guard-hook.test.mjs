import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { loadGatewayState, saveGatewayState } from "../dist/state/storage.js"

test("stale-loop-expiry-guard deactivates stale active loop", async () => {
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
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
