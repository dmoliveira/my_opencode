import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { saveGatewayState } from "../dist/state/storage.js"

test("keyword-detector injects analyze mode guidance into continuation prompt", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-keyword-detector-"))
  try {
    saveGatewayState(directory, {
      activeLoop: {
        active: true,
        sessionId: "session-keyword-1",
        objective: "diagnose issue",
        completionMode: "promise",
        completionPromise: "DONE",
        iteration: 1,
        maxIterations: 0,
        startedAt: new Date().toISOString(),
      },
      lastUpdatedAt: new Date().toISOString(),
      source: "test",
    })

    const prompts = []
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["keyword-detector", "continuation"],
          disabled: [],
        },
        keywordDetector: { enabled: true },
      },
      client: {
        session: {
          async messages() {
            return {
              data: [
                {
                  info: { role: "assistant" },
                  parts: [{ type: "text", text: "working" }],
                },
              ],
            }
          },
          async promptAsync(args) {
            prompts.push(args.body.parts[0].text)
          },
        },
      },
    })

    await plugin["chat.message"]({
      sessionID: "session-keyword-1",
      prompt: "please analyze this deeply",
    })
    await plugin.event({
      event: {
        type: "session.idle",
        properties: { sessionID: "session-keyword-1" },
      },
    })

    assert.equal(prompts.length, 1)
    assert.ok(prompts[0].includes("Mode: analyze."))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
