import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

function createPlugin(directory) {
  return GatewayCorePlugin({
    directory,
    config: {
      hooks: { enabled: true, order: ["agent-user-reminder"], disabled: [] },
      agentUserReminder: { enabled: true },
    },
  })
}

test("agent-user-reminder appends session guidance on complex prompts", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-agent-reminder-"))
  try {
    const plugin = createPlugin(directory)
    const output = { parts: [{ type: "text", text: "user prompt" }] }
    await plugin["chat.message"](
      { sessionID: "session-agent", prompt: "please investigate this architecture issue" },
      output,
    )
    assert.match(String(output.parts[0].text), /session guidance/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("agent-user-reminder does not repeat in same session", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-agent-reminder-"))
  try {
    const plugin = createPlugin(directory)
    const output1 = { parts: [{ type: "text", text: "first" }] }
    await plugin["chat.message"](
      { sessionID: "session-agent-2", prompt: "debug this issue" },
      output1,
    )
    const output2 = { parts: [{ type: "text", text: "second" }] }
    await plugin["chat.message"](
      { sessionID: "session-agent-2", prompt: "investigate this root cause" },
      output2,
    )

    assert.match(String(output1.parts[0].text), /session guidance/)
    assert.doesNotMatch(String(output2.parts[0].text), /session guidance/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("agent-user-reminder resets on session.compacted", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-agent-reminder-"))
  try {
    const plugin = createPlugin(directory)
    const output1 = { parts: [{ type: "text", text: "first" }] }
    await plugin["chat.message"]({ sessionID: "session-agent-3", prompt: "debug this" }, output1)
    await plugin.event({ event: { type: "session.compacted", properties: { info: { id: "session-agent-3" } } } })

    const output2 = { parts: [{ type: "text", text: "second" }] }
    await plugin["chat.message"]({ sessionID: "session-agent-3", prompt: "research this" }, output2)
    assert.match(String(output2.parts[0].text), /session guidance/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
