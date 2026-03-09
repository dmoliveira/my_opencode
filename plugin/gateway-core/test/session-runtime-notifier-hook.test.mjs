import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { createSessionRuntimeNotifierHook } from "../dist/hooks/session-runtime-notifier/index.js"

test("session-runtime-notifier shows one toast per session on first chat message", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-notifier-"))
  try {
    const toasts = []
    const hook = createSessionRuntimeNotifierHook({
      directory,
      enabled: true,
      durationMs: 6000,
      client: {
        tui: {
          async showToast(args) {
            toasts.push(args)
          },
        },
      },
    })

    await hook.event("chat.message", { properties: { sessionID: "toast-session-1" }, directory })
    await hook.event("chat.message", { properties: { sessionID: "toast-session-1" }, directory })

    assert.equal(toasts.length, 1)
    assert.equal(toasts[0]?.title, "Runtime session")
    assert.equal(toasts[0]?.message, "toast-session-1")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-runtime-notifier shows compaction toast and resets session announcement", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-notifier-"))
  try {
    const toasts = []
    const hook = createSessionRuntimeNotifierHook({
      directory,
      enabled: true,
      durationMs: 4000,
      client: {
        tui: {
          async showToast(args) {
            toasts.push(args)
          },
        },
      },
    })

    await hook.event("chat.message", { properties: { sessionID: "toast-session-2" }, directory })
    await hook.event("session.compacted", { properties: { info: { id: "toast-session-2" } }, directory })
    await hook.event("chat.message", { properties: { sessionID: "toast-session-2" }, directory })

    assert.equal(toasts.length, 3)
    assert.equal(toasts[1]?.title, "Session compacted")
    assert.equal(toasts[1]?.message, "Runtime session: toast-session-2")
    assert.equal(toasts[2]?.title, "Runtime session")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-runtime-notifier integrates through default plugin hook order", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-notifier-"))
  try {
    const toasts = []
    const plugin = GatewayCorePlugin({
      directory,
      client: {
        tui: {
          async showToast(args) {
            toasts.push(args)
          },
        },
      },
    })

    await plugin["chat.message"]({ sessionID: "toast-session-plugin" }, {
      parts: [{ type: "text", text: "hello" }],
    })

    assert.equal(toasts.length, 1)
    assert.equal(toasts[0]?.message, "toast-session-plugin")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("session-runtime-notifier shows compaction toast from command.execute.after", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-notifier-"))
  try {
    const toasts = []
    const hook = createSessionRuntimeNotifierHook({
      directory,
      enabled: true,
      durationMs: 4000,
      client: {
        tui: {
          async showToast(args) {
            toasts.push(args)
          },
        },
      },
    })

    await hook.event("chat.message", { properties: { sessionID: "toast-session-3" }, directory })
    await hook.event("command.execute.after", { input: { command: "compact", sessionID: "toast-session-3" }, directory })

    assert.equal(toasts.length, 2)
    assert.equal(toasts[1]?.title, "Session compacted")
    assert.equal(toasts[1]?.message, "Runtime session: toast-session-3")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("session-runtime-notifier shows toast on session.updated before any chat message", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-notifier-"))
  try {
    const toasts = []
    const hook = createSessionRuntimeNotifierHook({
      directory,
      enabled: true,
      durationMs: 6000,
      client: {
        tui: {
          async showToast(args) {
            toasts.push(args)
          },
        },
      },
    })

    await hook.event("session.updated", { properties: { info: { id: "toast-session-update" } }, directory })
    await hook.event("chat.message", { properties: { sessionID: "toast-session-update" }, directory })

    assert.equal(toasts.length, 1)
    assert.equal(toasts[0]?.message, "toast-session-update")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-runtime-notifier integrates on session.updated through plugin event dispatch", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-notifier-"))
  try {
    const toasts = []
    const plugin = GatewayCorePlugin({
      directory,
      client: {
        tui: {
          async showToast(args) {
            toasts.push(args)
          },
        },
      },
    })

    await plugin.event({
      event: {
        type: "session.updated",
        properties: { info: { id: "toast-session-event" } },
      },
    })

    assert.equal(toasts.length, 1)
    assert.equal(toasts[0]?.message, "toast-session-event")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("session-runtime-notifier dedupes duplicate compaction signals", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-notifier-"))
  try {
    const toasts = []
    const hook = createSessionRuntimeNotifierHook({
      directory,
      enabled: true,
      durationMs: 4000,
      client: {
        tui: {
          async showToast(args) {
            toasts.push(args)
          },
        },
      },
    })

    await hook.event("chat.message", { properties: { sessionID: "toast-session-4" }, directory })
    await hook.event("session.compacted", { properties: { info: { id: "toast-session-4" } }, directory })
    await hook.event("command.execute.after", { input: { command: "compact", sessionID: "toast-session-4" }, directory })

    assert.equal(toasts.length, 2)
    assert.equal(toasts[1]?.title, "Session compacted")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
