import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
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
