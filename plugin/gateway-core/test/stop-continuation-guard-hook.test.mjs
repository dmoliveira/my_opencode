import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { saveGatewayState } from "../dist/state/storage.js"

test("stop-continuation-guard blocks idle continuation after stop command", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-stop-guard-"))
  try {
    saveGatewayState(directory, {
      activeLoop: {
        active: true,
        sessionId: "session-stop-1",
        objective: "do work",
        completionMode: "promise",
        completionPromise: "DONE",
        iteration: 1,
        maxIterations: 0,
        startedAt: new Date().toISOString(),
      },
      lastUpdatedAt: new Date().toISOString(),
      source: "test",
    })

    let promptCalls = 0
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["stop-continuation-guard", "continuation"],
          disabled: ["autopilot-loop"],
        },
        stopContinuationGuard: { enabled: true },
      },
      client: {
        session: {
          async messages() {
            return {
              data: [
                {
                  info: { role: "assistant" },
                  parts: [{ type: "text", text: "still running" }],
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

    await plugin["tool.execute.before"](
      { tool: "slashcommand", sessionID: "session-stop-1" },
      { args: { command: "/autopilot stop" } },
    )

    await plugin.event({
      event: {
        type: "session.idle",
        properties: { sessionID: "session-stop-1" },
      },
    })

    assert.equal(promptCalls, 0)

    await plugin["chat.message"]({ sessionID: "session-stop-1" })
    await plugin.event({
      event: {
        type: "session.idle",
        properties: { sessionID: "session-stop-1" },
      },
    })
    assert.equal(promptCalls, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
