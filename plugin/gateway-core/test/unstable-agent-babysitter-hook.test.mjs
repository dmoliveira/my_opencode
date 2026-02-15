import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("unstable-agent-babysitter appends warning for risky model profile", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-unstable-babysitter-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["unstable-agent-babysitter"], disabled: [] },
        unstableAgentBabysitter: { enabled: true, riskyPatterns: ["experimental"] },
      },
    })
    const output = { parts: [{ type: "text", text: "prompt" }] }
    await plugin["chat.message"]({ sessionID: "session-unstable", model: "claude-experimental" }, output)
    assert.ok(output.parts[0].text.includes("Risky model profile detected"))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
