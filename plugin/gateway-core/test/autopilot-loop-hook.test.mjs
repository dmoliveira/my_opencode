import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import { createAutopilotLoopHook } from "../dist/hooks/autopilot-loop/index.js"
import { loadGatewayState } from "../dist/state/storage.js"

test("autopilot-loop hook accepts command from input args shape", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-loop-hook-"))
  try {
    const hook = createAutopilotLoopHook({
      directory,
      defaults: {
        enabled: true,
        maxIterations: 7,
        completionMode: "promise",
        completionPromise: "DONE",
      },
    })

    await hook.event("tool.execute.before", {
      input: {
        tool: "slashcommand",
        sessionId: "session-123",
        args: { command: "/autopilot go --goal \"ship\"" },
      },
      output: {},
      directory,
    })

    const state = loadGatewayState(directory)
    assert.ok(state?.activeLoop)
    assert.equal(state?.activeLoop?.active, true)
    assert.equal(state?.activeLoop?.sessionId, "session-123")
    assert.equal(state?.activeLoop?.objective, "ship")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("autopilot-loop hook starts loop even when tool label differs", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-loop-hook-"))
  try {
    const hook = createAutopilotLoopHook({
      directory,
      defaults: {
        enabled: true,
        maxIterations: 0,
        completionMode: "promise",
        completionPromise: "DONE",
      },
    })

    await hook.event("tool.execute.before", {
      input: {
        tool: "command",
        sessionID: "session-variant",
      },
      properties: {
        command: "/ralph-loop",
        sessionID: "session-variant",
      },
      directory,
    })

    const state = loadGatewayState(directory)
    assert.ok(state?.activeLoop)
    assert.equal(state?.activeLoop?.active, true)
    assert.equal(state?.activeLoop?.sessionId, "session-variant")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
