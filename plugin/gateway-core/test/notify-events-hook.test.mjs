import assert from "node:assert/strict"
import test from "node:test"

import {
  createNotifyEventsHook,
  terminalNotifierAttempts,
} from "../dist/hooks/notify-events/index.js"

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
  assert.equal(sent[0].eventName, "complete")
  assert.equal(sent[0].visual, true)
  assert.equal(sent[0].sound, true)
  assert.equal(sent[0].content.title, "OpenCode Complete")
  assert.ok(sent[0].content.message.startsWith("Done."))
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
  assert.ok(sent[1].content.message.startsWith("Input needed: Choose merge strategy"))
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
  assert.ok(sent[0].content.message.startsWith("Input needed:"))
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
      sessionTitle: "Refine notification context rendering now",
      tmux_session: "dev.1",
      question: "Approve deploy?",
    },
  })

  assert.equal(sent.length, 1)
  assert.equal(sent[0].eventName, "question")
  assert.equal(sent[0].content.title, "OpenCode • Refine notification context rendering")
  assert.ok(sent[0].content.message.includes("tmux dev.1"))
  assert.ok(sent[0].content.message.includes("s:sess-42"))
  assert.ok(sent[0].content.message.includes("w:w-9"))
  assert.ok(sent[0].content.message.includes("notify-context"))
})

test("notify-events prefers activate before sender for Ghostty", () => {
  const attempts = terminalNotifierAttempts({
    title: "OpenCode",
    message: "Ghostty sender fallback",
    imagePath: "/tmp/icon.png",
    soundName: "Glass",
    sender: "com.mitchellh.ghostty",
  })

  assert.equal(attempts.length, 6)
  assert.equal(attempts[0].args.includes("-activate"), true)
  assert.equal(attempts[0].args.includes("-sender"), false)
  assert.equal(attempts[2].args.includes("-sender"), true)
})

test("notify-events keeps sender-first attempts for non-Ghostty", () => {
  const attempts = terminalNotifierAttempts({
    title: "OpenCode",
    message: "Generic sender fallback",
    imagePath: "",
    soundName: "Glass",
    sender: "com.apple.Terminal",
  })

  assert.equal(attempts[0].args.includes("-sender"), true)
  assert.equal(attempts[0].args.includes("-activate"), false)
  assert.equal(attempts[1].args.includes("-activate"), true)
})
