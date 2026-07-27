import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import { createSafetyHook } from "../dist/hooks/safety/index.js"
import { loadGatewayState, saveGatewayState } from "../dist/state/storage.js"

test("safety hook deactivates only the matching deleted session", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-safety-"))
  try {
    saveGatewayState(directory, {
      activeLoop: {
        active: true,
        sessionId: "session-owner",
        objective: "owner work",
        completionMode: "promise",
        completionPromise: "DONE",
        iteration: 1,
        maxIterations: 0,
        startedAt: new Date().toISOString(),
      },
      lastUpdatedAt: new Date().toISOString(),
      source: "test",
    })
    const hook = createSafetyHook({ directory, orphanMaxAgeHours: 12 })

    await hook.event("session.deleted", {
      directory,
      properties: { sessionID: "session-other" },
    })
    assert.equal(loadGatewayState(directory)?.activeLoop?.active, true)

    await hook.event("session.deleted", {
      directory,
      properties: { sessionID: "session-owner" },
    })
    assert.equal(loadGatewayState(directory)?.activeLoop?.active, false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
