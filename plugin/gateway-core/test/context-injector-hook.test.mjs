import assert from "node:assert/strict"
import { mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import { ContextCollector } from "../dist/hooks/context-injector/collector.js"
import { createContextInjectorHook } from "../dist/hooks/context-injector/index.js"

test("context-injector appends pending context in chat.message", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-context-injector-"))
  try {
    const collector = new ContextCollector()
    collector.register("session-context-1", {
      source: "test",
      content: "Injected context block",
      priority: "high",
    })
    const hook = createContextInjectorHook({
      directory,
      enabled: true,
      collector,
    })
    const output = {
      parts: [{ type: "text", text: "Original prompt" }],
    }
    await hook.event("chat.message", {
      properties: { sessionID: "session-context-1" },
      output,
      directory,
    })

    assert.match(String(output.parts[0].text), /Injected context block/)
    assert.match(String(output.parts[0].text), /Original prompt/)
    assert.equal(collector.hasPending("session-context-1"), false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("context-injector resolves session id from properties.info.id", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-context-injector-"))
  try {
    const collector = new ContextCollector()
    collector.register("session-context-info", {
      source: "test",
      content: "Info-id context block",
      priority: "high",
    })
    const hook = createContextInjectorHook({
      directory,
      enabled: true,
      collector,
    })
    const output = {
      parts: [{ type: "text", text: "Original prompt" }],
    }
    await hook.event("chat.message", {
      properties: { info: { id: "session-context-info" } },
      output,
      directory,
    })

    assert.match(String(output.parts[0].text), /Info-id context block/)
    assert.equal(collector.hasPending("session-context-info"), false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("context-injector inserts synthetic part in message transform", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-context-injector-"))
  try {
    const collector = new ContextCollector()
    collector.register("session-context-2", {
      source: "test",
      content: "Transform context block",
      priority: "high",
    })
    const hook = createContextInjectorHook({
      directory,
      enabled: true,
      collector,
    })
    const output = {
      messages: [
        { info: { role: "assistant" }, parts: [{ type: "text", text: "A" }] },
        { info: { role: "user", id: "m1", sessionID: "session-context-2" }, parts: [{ type: "text", text: "B" }] },
      ],
    }
    await hook.event("experimental.chat.messages.transform", {
      input: { sessionID: "session-context-2" },
      output,
      directory,
    })

    const userParts = output.messages[1].parts
    assert.equal(userParts?.[0]?.type, "text")
    assert.equal(userParts?.[0]?.synthetic, true)
    assert.match(String(userParts?.[0]?.text), /Transform context block/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("context-injector resolves transform session from message info.sessionId", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-context-injector-"))
  try {
    const collector = new ContextCollector()
    collector.register("session-context-2b", {
      source: "test",
      content: "Transform sessionId context block",
      priority: "high",
    })
    const hook = createContextInjectorHook({
      directory,
      enabled: true,
      collector,
    })
    const output = {
      messages: [
        { info: { role: "assistant" }, parts: [{ type: "text", text: "A" }] },
        { info: { role: "user", id: "m1", sessionId: "session-context-2b" }, parts: [{ type: "text", text: "B" }] },
      ],
    }
    await hook.event("experimental.chat.messages.transform", {
      input: {},
      output,
      directory,
    })

    const userParts = output.messages[1].parts
    assert.equal(userParts?.[0]?.type, "text")
    assert.equal(userParts?.[0]?.synthetic, true)
    assert.match(String(userParts?.[0]?.text), /Transform sessionId context block/)
    assert.equal(collector.hasPending("session-context-2b"), false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("context-injector resolves transform session from message info.sessionID", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-context-injector-"))
  try {
    const collector = new ContextCollector()
    collector.register("session-context-2c", {
      source: "test",
      content: "Transform sessionID context block",
      priority: "high",
    })
    const hook = createContextInjectorHook({
      directory,
      enabled: true,
      collector,
    })
    const output = {
      messages: [
        { info: { role: "assistant" }, parts: [{ type: "text", text: "A" }] },
        { info: { role: "user", id: "m1", sessionID: "session-context-2c" }, parts: [{ type: "text", text: "B" }] },
      ],
    }
    await hook.event("experimental.chat.messages.transform", {
      input: {},
      output,
      directory,
    })

    const userParts = output.messages[1].parts
    assert.equal(userParts?.[0]?.type, "text")
    assert.equal(userParts?.[0]?.synthetic, true)
    assert.match(String(userParts?.[0]?.text), /Transform sessionID context block/)
    assert.equal(collector.hasPending("session-context-2c"), false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("context-injector requeue uses stable fallback context id", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-context-injector-"))
  try {
    const calls = []
    const hook = createContextInjectorHook({
      directory,
      enabled: true,
      collector: {
        hasPending() {
          return true
        },
        consume() {
          return { hasContent: true, merged: "Fallback context" }
        },
        register(sessionId, options) {
          calls.push({ sessionId, options })
        },
        clear() {},
      },
    })

    await hook.event("chat.message", {
      properties: { sessionID: "session-fallback" },
      output: { parts: [{ type: "tool-call" }] },
      directory,
    })

    assert.equal(calls.length, 1)
    assert.equal(calls[0]?.sessionId, "session-fallback")
    assert.equal(calls[0]?.options?.source, "context-injector-requeue")
    assert.equal(calls[0]?.options?.id, "chat-message-fallback")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("context-injector falls back to last known session id in transform", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-context-injector-"))
  try {
    const collector = new ContextCollector()
    const hook = createContextInjectorHook({
      directory,
      enabled: true,
      collector,
    })

    await hook.event("chat.message", {
      properties: { sessionID: "session-context-fallback" },
      output: { parts: [{ type: "text", text: "seed" }] },
      directory,
    })

    collector.register("session-context-fallback", {
      source: "test",
      id: "fallback-transform",
      content: "Fallback transform context",
      priority: "high",
    })

    const output = {
      messages: [{ info: { role: "user", id: "m2" }, parts: [{ type: "text", text: "B" }] }],
    }
    await hook.event("experimental.chat.messages.transform", {
      input: {},
      output,
      directory,
    })

    const userParts = output.messages[0].parts
    assert.equal(userParts?.[0]?.type, "text")
    assert.equal(userParts?.[0]?.synthetic, true)
    assert.match(String(userParts?.[0]?.text), /Fallback transform context/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("context-injector truncates oversized chat pending context", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-context-injector-"))
  try {
    const collector = new ContextCollector()
    collector.register("session-context-truncate-chat", {
      source: "test",
      id: "large-chat-context",
      content: "X".repeat(220),
      priority: "high",
    })
    const hook = createContextInjectorHook({
      directory,
      enabled: true,
      collector,
      maxChars: 120,
    })
    const output = {
      parts: [{ type: "text", text: "Original prompt" }],
    }
    await hook.event("chat.message", {
      properties: { sessionID: "session-context-truncate-chat" },
      output,
      directory,
    })

    const text = String(output.parts[0]?.text)
    assert.match(text, /Content truncated due to context window limit/)
    assert.match(text, /Original prompt/)
    assert.equal(collector.hasPending("session-context-truncate-chat"), false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("context-injector truncates oversized transform pending context", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-context-injector-"))
  try {
    const collector = new ContextCollector()
    collector.register("session-context-truncate-transform", {
      source: "test",
      id: "large-transform-context",
      content: "Y".repeat(220),
      priority: "high",
    })
    const hook = createContextInjectorHook({
      directory,
      enabled: true,
      collector,
      maxChars: 120,
    })
    const output = {
      messages: [
        {
          info: { role: "user", id: "m1", sessionID: "session-context-truncate-transform" },
          parts: [{ type: "text", text: "Original transform prompt" }],
        },
      ],
    }
    await hook.event("experimental.chat.messages.transform", {
      input: { sessionID: "session-context-truncate-transform" },
      output,
      directory,
    })

    const synthetic = output.messages[0]?.parts?.[0]
    assert.equal(synthetic?.synthetic, true)
    assert.match(String(synthetic?.text), /Content truncated due to context window limit/)
    assert.equal(collector.hasPending("session-context-truncate-transform"), false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("context-injector respects tiny maxChars limits", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-context-injector-"))
  try {
    const collector = new ContextCollector()
    collector.register("session-context-truncate-tiny", {
      source: "test",
      id: "tiny-context",
      content: "Q".repeat(120),
      priority: "high",
    })
    const hook = createContextInjectorHook({
      directory,
      enabled: true,
      collector,
      maxChars: 10,
    })
    const output = {
      parts: [{ type: "text", text: "Original prompt" }],
    }
    await hook.event("chat.message", {
      properties: { sessionID: "session-context-truncate-tiny" },
      output,
      directory,
    })

    const text = String(output.parts[0]?.text)
    const [injected] = text.split("\n\n---\n\n")
    assert.equal(injected.length, 10)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("context-injector records granular reason when transform has no user message", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-context-injector-"))
  const previous = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  try {
    const collector = new ContextCollector()
    collector.register("session-context-no-user", {
      source: "test",
      id: "no-user",
      content: "Pending context with no user message",
      priority: "high",
    })
    const hook = createContextInjectorHook({
      directory,
      enabled: true,
      collector,
    })

    await hook.event("experimental.chat.messages.transform", {
      input: { sessionID: "session-context-no-user" },
      output: {
        messages: [{ info: { role: "assistant", id: "m1" }, parts: [{ type: "text", text: "A" }] }],
      },
      directory,
    })

    const lines = readFileSync(join(directory, ".opencode", "gateway-events.jsonl"), "utf-8")
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => JSON.parse(line))
    assert.ok(lines.some((entry) => entry.reason_code === "pending_context_transform_no_user_message"))
  } finally {
    if (previous === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previous
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

test("context-injector records granular reason when transform user message has no parts", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-context-injector-"))
  const previous = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  try {
    const collector = new ContextCollector()
    collector.register("session-context-no-parts", {
      source: "test",
      id: "no-parts",
      content: "Pending context with missing parts",
      priority: "high",
    })
    const hook = createContextInjectorHook({
      directory,
      enabled: true,
      collector,
    })

    await hook.event("experimental.chat.messages.transform", {
      input: { sessionID: "session-context-no-parts" },
      output: {
        messages: [{ info: { role: "user", id: "m1" } }],
      },
      directory,
    })

    const lines = readFileSync(join(directory, ".opencode", "gateway-events.jsonl"), "utf-8")
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => JSON.parse(line))
    assert.ok(lines.some((entry) => entry.reason_code === "pending_context_transform_missing_parts"))
  } finally {
    if (previous === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previous
    }
    rmSync(directory, { recursive: true, force: true })
  }
})
