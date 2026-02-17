import assert from "node:assert/strict"
import test from "node:test"

import { createCodexHeaderInjectorHook } from "../dist/hooks/codex-header-injector/index.js"

test("codex-header-injector adds header to codex chat payload", async () => {
  const hook = createCodexHeaderInjectorHook({ enabled: true, directory: process.cwd() })
  const payload = {
    properties: { sessionID: "s1", model: "openai/gpt-5-codex" },
    output: { parts: [{ type: "text", text: "User prompt body" }] },
  }

  await hook.event("chat.message", payload)

  assert.match(String(payload.output.parts[0].text), /\[codex HEADER\]/)
})

test("codex-header-injector skips non-codex payload", async () => {
  const hook = createCodexHeaderInjectorHook({ enabled: true, directory: process.cwd() })
  const payload = {
    properties: { sessionID: "s2", model: "anthropic/claude" },
    output: { parts: [{ type: "text", text: "User prompt body" }] },
  }

  await hook.event("chat.message", payload)

  assert.equal(payload.output.parts[0].text, "User prompt body")
})

test("codex-header-injector suppresses duplicate injection and resets on session.deleted", async () => {
  const hook = createCodexHeaderInjectorHook({ enabled: true, directory: process.cwd() })
  const first = {
    properties: { sessionID: "s3", model: "openai/gpt-5-codex" },
    output: { parts: [{ type: "text", text: "First" }] },
  }
  const second = {
    properties: { sessionID: "s3", model: "openai/gpt-5-codex" },
    output: { parts: [{ type: "text", text: "Second" }] },
  }

  await hook.event("chat.message", first)
  await hook.event("chat.message", second)
  assert.equal(second.output.parts[0].text, "Second")

  await hook.event("session.deleted", { properties: { info: { id: "s3" } } })
  await hook.event("chat.message", second)
  assert.match(String(second.output.parts[0].text), /\[codex HEADER\]/)
})

test("codex-header-injector injects into transform user message", async () => {
  const hook = createCodexHeaderInjectorHook({ enabled: true, directory: process.cwd() })
  const payload = {
    input: { sessionID: "s4", modelID: "gpt-5-codex" },
    output: {
      messages: [
        { info: { role: "assistant" }, parts: [{ type: "text", text: "a" }] },
        { info: { role: "user" }, parts: [{ type: "text", text: "u" }] },
      ],
    },
  }

  await hook.event("experimental.chat.messages.transform", payload)

  assert.match(String(payload.output.messages[1].parts[0].text), /\[codex HEADER\]/)
})
