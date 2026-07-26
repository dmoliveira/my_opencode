import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("official options override legacy config and skip hook factories", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-plugin-options-"))
  try {
    let runtimeFactoryCalls = 0
    const plugin = await GatewayCorePlugin(
      {
        directory,
        config: {
          hooks: { enabled: true, order: ["think-mode"] },
          thinkMode: { enabled: true },
          secretLeakGuard: { enabled: true, providerBoundaryEnabled: true },
        },
        createLlmDecisionRuntime() {
          runtimeFactoryCalls += 1
          throw new Error("hook factory should not run")
        },
      },
      {
        hooks: { enabled: false },
        secretLeakGuard: {
          enabled: true,
          providerBoundaryEnabled: true,
          patterns: ["WAVE3_CANARY_[A-Z]+"],
          redactionToken: "[WAVE3_REDACTED]",
        },
      },
    )

    const chatOutput = { parts: [{ type: "text", text: "analyze this" }] }
    await plugin["chat.message"]({ sessionID: "options-disabled" }, chatOutput)
    assert.doesNotMatch(chatOutput.parts[0].text, /\[think mode\]/)
    assert.equal(runtimeFactoryCalls, 0)

    const transformOutput = {
      messages: [
        {
          info: { role: "user" },
          parts: [{ type: "text", text: "WAVE3_CANARY_SECRET" }],
        },
      ],
    }
    await plugin["experimental.chat.messages.transform"]({}, transformOutput)
    assert.equal(transformOutput.messages[0].parts[0].text, "[WAVE3_REDACTED]")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("canonical chat parts drive hooks without replacing host objects", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-chat-contract-"))
  try {
    const plugin = GatewayCorePlugin(
      { directory },
      {
        hooks: {
          enabled: true,
          order: ["think-mode", "agent-user-reminder"],
          disabled: [],
        },
        thinkMode: { enabled: true },
        agentUserReminder: { enabled: true },
      },
    )
    const message = { id: "message-identity" }
    const part = { type: "text", text: "analyze and optimize this architecture" }
    const parts = [part]
    const output = { message, parts }

    await plugin["chat.message"](
      { sessionID: "canonical-chat", prompt: "legacy text must lose" },
      output,
    )

    assert.equal(output.message, message)
    assert.equal(output.parts, parts)
    assert.equal(output.parts[0], part)
    assert.match(part.text, /\[think mode\]/)
    assert.match(part.text, /\[session guidance\]/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("canonical non-text parts suppress legacy prompt fallback", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-chat-no-text-"))
  try {
    const plugin = GatewayCorePlugin(
      { directory },
      {
        hooks: { enabled: true, order: ["think-mode"], disabled: [] },
        thinkMode: { enabled: true },
      },
    )
    const output = { parts: [{ type: "file", filename: "analysis.txt" }] }
    await plugin["chat.message"](
      { sessionID: "canonical-no-text", prompt: "analyze this legacy prompt" },
      output,
    )
    assert.equal(output.parts.length, 1)
    assert.equal(output.parts[0].type, "file")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
