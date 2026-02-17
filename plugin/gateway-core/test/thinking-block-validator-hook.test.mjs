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
      hooks: { enabled: true, order: ["thinking-block-validator"], disabled: [] },
      thinkingBlockValidator: { enabled: true },
    },
  })
}

test("thinking-block-validator warns on malformed thinking blocks", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-thinking-validator-"))
  try {
    const plugin = createPlugin(directory)
    const output = { parts: [{ type: "text", text: "<thinking>draft chain" }] }
    await plugin["chat.message"]({ sessionID: "session-validator-1", prompt: "hello" }, output)
    assert.match(String(output.parts[0]?.text), /\[thinking validator\]/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("thinking-block-validator ignores balanced thinking blocks", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-thinking-validator-"))
  try {
    const plugin = createPlugin(directory)
    const output = { parts: [{ type: "text", text: "<thinking>ok</thinking>" }] }
    await plugin["chat.message"]({ sessionID: "session-validator-2", prompt: "hello" }, output)
    assert.doesNotMatch(String(output.parts[0]?.text), /\[thinking validator\]/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("thinking-block-validator warns on misordered thinking tags", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-thinking-validator-"))
  try {
    const plugin = createPlugin(directory)
    const output = { parts: [{ type: "text", text: "</thinking><thinking>" }] }
    await plugin["chat.message"]({ sessionID: "session-validator-3", prompt: "hello" }, output)
    assert.match(String(output.parts[0]?.text), /\[thinking validator\]/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("thinking-block-validator scans all text parts", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-thinking-validator-"))
  try {
    const plugin = createPlugin(directory)
    const output = {
      parts: [
        { type: "text", text: "First part" },
        { type: "text", text: "<thinking>broken" },
      ],
    }
    await plugin["chat.message"]({ sessionID: "session-validator-4", prompt: "hello" }, output)
    assert.match(String(output.parts[0]?.text), /\[thinking validator\]/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
