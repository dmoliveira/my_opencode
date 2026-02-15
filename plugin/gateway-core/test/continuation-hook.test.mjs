import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import { createContinuationHook } from "../dist/hooks/continuation/index.js"
import { loadGatewayState, saveGatewayState } from "../dist/state/storage.js"

test("continuation hook keeps looping when maxIterations is zero", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-continuation-"))
  try {
    saveGatewayState(directory, {
      activeLoop: {
        active: true,
        sessionId: "session-keep-going",
        objective: "keep iterating",
        completionMode: "promise",
        completionPromise: "DONE",
        iteration: 1,
        maxIterations: 0,
        startedAt: new Date().toISOString(),
      },
      lastUpdatedAt: new Date().toISOString(),
      source: "test-fixture",
    })

    let promptCalls = 0
    const hook = createContinuationHook({
      directory,
      client: {
        session: {
          async messages() {
            return {
              data: [
                {
                  info: { role: "assistant" },
                  parts: [{ type: "text", text: "still working" }],
                },
              ],
            }
          },
          async promptAsync() {
            promptCalls += 1
          },
        },
      },
    })

    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-keep-going" },
    })

    const state = loadGatewayState(directory)
    assert.equal(state?.activeLoop?.active, true)
    assert.equal(state?.activeLoop?.iteration, 2)
    assert.equal(promptCalls, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
