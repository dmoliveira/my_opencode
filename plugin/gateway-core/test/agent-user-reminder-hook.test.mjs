import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("agent-user-reminder appends specialist reminder on complex prompt", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-agent-reminder-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["agent-user-reminder"], disabled: [] },
        agentUserReminder: { enabled: true },
      },
    })
    const output = { parts: [{ type: "text", text: "user prompt" }] }
    await plugin["chat.message"]({ sessionID: "session-agent", prompt: "please investigate this architecture issue" }, output)
    assert.ok(output.parts[0].text.includes("specialist subagents"))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
