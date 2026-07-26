import assert from "node:assert/strict"
import { mkdtempSync, readFileSync, rmSync } from "node:fs"
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

test("minimal order skips unrelated runtimes and keeps provider redaction", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-minimal-order-"))
  try {
    let runtimeFactoryCalls = 0
    const plugin = await GatewayCorePlugin(
      {
        directory,
        createLlmDecisionRuntime({ config }) {
          runtimeFactoryCalls += 1
          return {
            config,
            async decide() {
              throw new Error("minimal order runtime should not execute")
            },
          }
        },
      },
      {
        hooks: { enabled: true, order: ["think-mode"], disabled: [] },
        thinkMode: { enabled: true },
        secretLeakGuard: {
          enabled: true,
          providerBoundaryEnabled: true,
          patterns: ["WAVE4_SECRET_[A-Z]+"],
          redactionToken: "[WAVE4_REDACTED]",
        },
      },
    )

    assert.equal(runtimeFactoryCalls, 0)
    const chatOutput = { parts: [{ type: "text", text: "analyze this" }] }
    await plugin["chat.message"]({ sessionID: "minimal-order" }, chatOutput)
    assert.match(chatOutput.parts[0].text, /\[think mode\]/)

    const transformOutput = {
      messages: [
        {
          info: { role: "user" },
          parts: [{ type: "text", text: "WAVE4_SECRET_VALUE" }],
        },
      ],
    }
    await plugin["experimental.chat.messages.transform"]({}, transformOutput)
    assert.equal(transformOutput.messages[0].parts[0].text, "[WAVE4_REDACTED]")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("selected LLM-backed hook creates only its own runtime", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-selected-runtime-"))
  try {
    let runtimeFactoryCalls = 0
    await GatewayCorePlugin(
      {
        directory,
        createLlmDecisionRuntime({ config }) {
          runtimeFactoryCalls += 1
          return {
            config,
            async decide() {
              throw new Error("selected runtime should not execute during init")
            },
          }
        },
      },
      {
        hooks: {
          enabled: true,
          order: ["auto-slash-command"],
          disabled: [],
        },
      },
    )
    assert.equal(runtimeFactoryCalls, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("disabled required dependency excludes consumer with sanitized audit", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-disabled-dependency-"))
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  try {
    await GatewayCorePlugin(
      { directory },
      {
        hooks: {
          enabled: true,
          order: ["global-process-pressure"],
          disabled: ["stop-continuation-guard"],
        },
      },
    )
    const audit = readFileSync(join(directory, ".opencode", "gateway-events.jsonl"), "utf8")
    assert.match(audit, /"reason_code":"hook_dependency_disabled"/)
    assert.match(audit, /"hook":"global-process-pressure"/)
    assert.match(audit, /"dependency_hook":"stop-continuation-guard"/)
    assert.doesNotMatch(audit, /secret|token|option/i)
  } finally {
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

test("host plugin loader fails closed on a misspelled hook identity", () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-invalid-hook-id-"))
  try {
    assert.throws(
      () =>
        GatewayCorePlugin(
          { directory },
          {
            hooks: {
              enabled: true,
              order: ["dangerous-command-gaurd"],
              disabled: [],
            },
          },
        ),
      /hooks\.order contains unknown gateway hook id: dangerous-command-gaurd/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
