import assert from "node:assert/strict"
import test from "node:test"

import { createNotifyEventsHook } from "../dist/hooks/notify-events/index.js"

test("notify-events maps session.idle to complete notifications", async () => {
  const sent = []
  const hook = createNotifyEventsHook({
    directory: process.cwd(),
    enabled: true,
    cooldownMs: 0,
    style: "brief",
    loadState() {
      return {
        enabled: true,
        sound: {
          enabled: true,
          theme: "classic",
          eventThemes: { complete: "default", error: "default", permission: "default", question: "default" },
          customFiles: { complete: "", error: "", permission: "", question: "" },
        },
        visual: { enabled: true },
        icons: { enabled: true, version: "v1", mode: "nerd+emoji" },
        events: { complete: true, error: true, permission: true, question: true },
        channels: {
          complete: { sound: true, visual: true },
          error: { sound: true, visual: true },
          permission: { sound: true, visual: true },
          question: { sound: true, visual: true },
        },
      }
    },
    notify(eventName, visual, sound, content) {
      sent.push({ eventName, visual, sound, content })
      return { visualSent: visual, soundSent: sound }
    },
  })

  await hook.event("session.idle", { directory: process.cwd() })

  assert.equal(sent.length, 1)
  assert.deepEqual(sent[0], {
    eventName: "complete",
    visual: true,
    sound: true,
    content: {
      title: "OpenCode Complete",
      message: `Task completed. [cwd ${process.cwd()}]`,
    },
  })
})

test("notify-events respects cooldown and disabled event toggles", async () => {
  const sent = []
  let nowMs = 1_000
  const hook = createNotifyEventsHook({
    directory: process.cwd(),
    enabled: true,
    cooldownMs: 5_000,
    style: "brief",
    now() {
      return nowMs
    },
    loadState() {
      return {
        enabled: true,
        sound: {
          enabled: true,
          theme: "classic",
          eventThemes: { complete: "default", error: "default", permission: "default", question: "default" },
          customFiles: { complete: "", error: "", permission: "", question: "" },
        },
        visual: { enabled: true },
        icons: { enabled: true, version: "v1", mode: "nerd+emoji" },
        events: { complete: false, error: true, permission: true, question: true },
        channels: {
          complete: { sound: true, visual: true },
          error: { sound: true, visual: true },
          permission: { sound: true, visual: true },
          question: { sound: true, visual: true },
        },
      }
    },
    notify(eventName, visual, sound, content) {
      sent.push({ eventName, visual, sound, content })
      return { visualSent: visual, soundSent: sound }
    },
  })

  await hook.event("session.idle", { directory: process.cwd() })
  assert.equal(sent.length, 0)

  await hook.event("session.error", { directory: process.cwd() })
  await hook.event("session.error", { directory: process.cwd() })
  assert.equal(sent.length, 1)

  nowMs = 8_000
  await hook.event("tool.execute.before", {
    input: { tool: "question" },
    directory: process.cwd(),
    properties: {
      question: "Choose merge strategy for current PR and continue",
    },
  })
  assert.equal(sent.length, 2)
  assert.equal(sent[1].eventName, "question")
  assert.equal(sent[1].content.title, "OpenCode Input Needed")
  assert.ok(sent[1].content.message.startsWith("Question: Choose merge strategy"))
  assert.ok(sent[1].content.message.includes(`[cwd ${process.cwd()}]`))
})

test("notify-events supports detailed style copy", async () => {
  const sent = []
  const hook = createNotifyEventsHook({
    directory: process.cwd(),
    enabled: true,
    cooldownMs: 0,
    style: "detailed",
    loadState() {
      return {
        enabled: true,
        sound: {
          enabled: true,
          theme: "classic",
          eventThemes: { complete: "default", error: "default", permission: "default", question: "default" },
          customFiles: { complete: "", error: "", permission: "", question: "" },
        },
        visual: { enabled: true },
        icons: { enabled: true, version: "v1", mode: "nerd+emoji" },
        events: { complete: true, error: true, permission: true, question: true },
        channels: {
          complete: { sound: true, visual: true },
          error: { sound: true, visual: true },
          permission: { sound: true, visual: true },
          question: { sound: true, visual: true },
        },
      }
    },
    notify(eventName, visual, sound, content) {
      sent.push({ eventName, visual, sound, content })
      return { visualSent: visual, soundSent: sound }
    },
  })

  await hook.event("tool.execute.before", {
    input: { tool: "question" },
    directory: process.cwd(),
    properties: {
      question: "Choose merge strategy for current PR and continue",
    },
  })

  assert.equal(sent.length, 1)
  assert.equal(sent[0].eventName, "question")
  assert.equal(sent[0].content.title, "OpenCode Input Needed")
  assert.ok(sent[0].content.message.startsWith("Response needed to continue:"))
  assert.ok(sent[0].content.message.includes(`[cwd ${process.cwd()}]`))
})

test("notify-events includes session and window context when available", async () => {
  const sent = []
  const hook = createNotifyEventsHook({
    directory: process.cwd(),
    enabled: true,
    cooldownMs: 0,
    style: "brief",
    loadState() {
      return {
        enabled: true,
        sound: {
          enabled: true,
          theme: "classic",
          eventThemes: { complete: "default", error: "default", permission: "default", question: "default" },
          customFiles: { complete: "", error: "", permission: "", question: "" },
        },
        visual: { enabled: true },
        icons: { enabled: true, version: "v1", mode: "nerd+emoji" },
        events: { complete: true, error: true, permission: true, question: true },
        channels: {
          complete: { sound: true, visual: true },
          error: { sound: true, visual: true },
          permission: { sound: true, visual: true },
          question: { sound: true, visual: true },
        },
      }
    },
    notify(eventName, visual, sound, content) {
      sent.push({ eventName, visual, sound, content })
      return { visualSent: visual, soundSent: sound }
    },
  })

  await hook.event("tool.execute.before", {
    input: { tool: "question", sessionID: "sess-42", windowId: "w-9" },
    directory: "/tmp/notify-context",
    properties: {
      question: "Approve deploy?",
    },
  })

  assert.equal(sent.length, 1)
  assert.equal(sent[0].eventName, "question")
  assert.ok(sent[0].content.message.includes("session sess-42"))
  assert.ok(sent[0].content.message.includes("window w-9"))
  assert.ok(sent[0].content.message.includes("cwd /tmp/notify-context"))
})
