import assert from "node:assert/strict"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
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

test("continuation hook bootstraps loop from runtime when state is missing", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-continuation-"))
  const runtimePath = join(directory, "autopilot_runtime.json")
  const previousRuntimePath = process.env.MY_OPENCODE_AUTOPILOT_RUNTIME_PATH
  process.env.MY_OPENCODE_AUTOPILOT_RUNTIME_PATH = runtimePath
  try {
    writeFileSync(
      runtimePath,
      `${JSON.stringify(
        {
          status: "running",
          objective: {
            goal: "bootstrap from runtime",
            completion_mode: "promise",
            completion_promise: "DONE",
          },
          progress: {
            completed_cycles: 2,
          },
        },
        null,
        2,
      )}\n`,
      "utf-8",
    )

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
      properties: { sessionID: "session-bootstrap" },
    })

    const state = loadGatewayState(directory)
    assert.equal(state?.activeLoop?.active, true)
    assert.equal(state?.activeLoop?.sessionId, "session-bootstrap")
    assert.equal(state?.activeLoop?.objective, "bootstrap from runtime")
    assert.equal(state?.activeLoop?.iteration, 4)
    assert.equal(promptCalls, 1)
  } finally {
    if (previousRuntimePath === undefined) {
      delete process.env.MY_OPENCODE_AUTOPILOT_RUNTIME_PATH
    } else {
      process.env.MY_OPENCODE_AUTOPILOT_RUNTIME_PATH = previousRuntimePath
    }
    rmSync(directory, { recursive: true, force: true })
  }
})
