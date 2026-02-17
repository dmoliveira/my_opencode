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
      hooks: { enabled: true, order: ["think-mode"], disabled: ["agent-user-reminder"] },
      thinkMode: { enabled: true },
    },
  })
}

test("think-mode appends structured reasoning hint for think-oriented prompts", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-think-mode-"))
  try {
    const plugin = createPlugin(directory)
    const output = { parts: [{ type: "text", text: "assistant draft" }] }
    await plugin["chat.message"]({ sessionID: "session-think-1", prompt: "think step by step" }, output)
    assert.match(String(output.parts[0]?.text), /\[think mode\]/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("think-mode does not repeat hint for same session until reset", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-think-mode-"))
  try {
    const plugin = createPlugin(directory)
    const first = { parts: [{ type: "text", text: "first" }] }
    await plugin["chat.message"]({ sessionID: "session-think-2", prompt: "reason about this" }, first)
    const second = { parts: [{ type: "text", text: "second" }] }
    await plugin["chat.message"]({ sessionID: "session-think-2", prompt: "analyze this too" }, second)

    assert.match(String(first.parts[0]?.text), /\[think mode\]/)
    assert.doesNotMatch(String(second.parts[0]?.text), /\[think mode\]/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("think-mode resets dedupe after session.compacted", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-think-mode-"))
  try {
    const plugin = createPlugin(directory)
    const first = { parts: [{ type: "text", text: "first" }] }
    await plugin["chat.message"]({ sessionID: "session-think-3", prompt: "think through this" }, first)
    await plugin.event({ event: { type: "session.compacted", properties: { info: { id: "session-think-3" } } } })

    const second = { parts: [{ type: "text", text: "second" }] }
    await plugin["chat.message"]({ sessionID: "session-think-3", prompt: "think through this again" }, second)
    assert.match(String(second.parts[0]?.text), /\[think mode\]/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
