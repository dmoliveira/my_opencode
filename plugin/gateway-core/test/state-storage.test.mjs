import test from "node:test"
import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

import {
  cleanupOrphanGatewayLoop,
  loadGatewayState,
  nowIso,
  saveGatewayState,
} from "../dist/state/storage.js"

function withTempDir(run) {
  const directory = mkdtempSync(join(tmpdir(), "gateway-core-test-"))
  try {
    run(directory)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
}

test("cleanupOrphanGatewayLoop deactivates stale active loop", () => {
  withTempDir((directory) => {
    saveGatewayState(directory, {
      activeLoop: {
        active: true,
        sessionId: "s-1",
        objective: "continue",
        completionMode: "promise",
        completionPromise: "DONE",
        iteration: 1,
        maxIterations: 100,
        startedAt: "2025-01-01T00:00:00Z",
      },
      lastUpdatedAt: nowIso(),
    })

    const result = cleanupOrphanGatewayLoop(directory, 1)
    assert.equal(result.changed, true)
    assert.equal(result.reason, "stale_loop_deactivated")
    assert.equal(loadGatewayState(directory)?.activeLoop?.active, false)
  })
})

test("cleanupOrphanGatewayLoop keeps fresh loop active", () => {
  withTempDir((directory) => {
    saveGatewayState(directory, {
      activeLoop: {
        active: true,
        sessionId: "s-2",
        objective: "continue",
        completionMode: "promise",
        completionPromise: "DONE",
        iteration: 1,
        maxIterations: 100,
        startedAt: nowIso(),
      },
      lastUpdatedAt: nowIso(),
    })

    const result = cleanupOrphanGatewayLoop(directory, 12)
    assert.equal(result.changed, false)
    assert.equal(result.reason, "within_age_limit")
    assert.equal(loadGatewayState(directory)?.activeLoop?.active, true)
  })
})
