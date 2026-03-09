import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { createSessionRuntimeVisibleNoteHook } from "../dist/hooks/session-runtime-visible-note/index.js"

test("session-runtime-visible-note injects one visible note on session.updated", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-visible-note-"))
  try {
    const prompts = []
    const hook = createSessionRuntimeVisibleNoteHook({
      directory,
      enabled: true,
      client: {
        session: {
          async promptAsync(args) {
            prompts.push(args)
          },
          async messages() {
            return { data: [] }
          },
        },
      },
    })

    await hook.event("session.updated", { properties: { info: { id: "visible-session-1" } }, directory })
    await hook.event("session.updated", { properties: { info: { id: "visible-session-1" } }, directory })

    assert.equal(prompts.length, 1)
    assert.equal(prompts[0]?.body?.parts?.[0]?.text, "[Runtime session]\nvisible-session-1")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-runtime-visible-note reinjects after compaction", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-visible-note-"))
  try {
    const prompts = []
    const hook = createSessionRuntimeVisibleNoteHook({
      directory,
      enabled: true,
      client: {
        session: {
          async promptAsync(args) {
            prompts.push(args)
          },
          async messages() {
            return { data: [] }
          },
        },
      },
    })

    await hook.event("session.updated", { properties: { info: { id: "visible-session-2" } }, directory })
    await hook.event("session.compacted", { properties: { info: { id: "visible-session-2" } }, directory })

    assert.equal(prompts.length, 2)
    assert.equal(prompts[1]?.body?.parts?.[0]?.text, "[Runtime session]\nvisible-session-2")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-runtime-visible-note integrates through plugin event dispatch", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-visible-note-"))
  try {
    const prompts = []
    const plugin = GatewayCorePlugin({
      directory,
      client: {
        session: {
          async promptAsync(args) {
            prompts.push(args)
          },
          async messages() {
            return { data: [] }
          },
        },
      },
      config: {
        hooks: {
          enabled: true,
          order: ["session-runtime-visible-note"],
          disabled: [],
        },
      },
    })

    await plugin.event({
      event: {
        type: "session.updated",
        properties: { info: { id: "visible-session-event" } },
      },
    })

    assert.equal(prompts.length, 1)
    assert.equal(prompts[0]?.body?.parts?.[0]?.text, "[Runtime session]\nvisible-session-event")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("session-runtime-visible-note dedupes duplicate compaction signals", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-visible-note-"))
  try {
    const prompts = []
    const hook = createSessionRuntimeVisibleNoteHook({
      directory,
      enabled: true,
      client: {
        session: {
          async promptAsync(args) {
            prompts.push(args)
          },
          async messages() {
            return { data: [] }
          },
        },
      },
    })

    await hook.event("session.updated", { properties: { info: { id: "visible-session-3" } }, directory })
    await hook.event("session.compacted", { properties: { info: { id: "visible-session-3" } }, directory })
    await hook.event("command.execute.after", { input: { command: "compact", sessionID: "visible-session-3" }, directory })

    assert.equal(prompts.length, 2)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-runtime-visible-note skips recent duplicate visible note on restart", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-visible-note-"))
  try {
    const prompts = []
    const hook = createSessionRuntimeVisibleNoteHook({
      directory,
      enabled: true,
      client: {
        session: {
          async promptAsync(args) {
            prompts.push(args)
          },
          async messages() {
            return {
              data: [
                {
                  parts: [{ type: "text", text: "[Runtime session]\nvisible-session-4" }],
                },
              ],
            }
          },
        },
      },
    })

    await hook.event("session.updated", { properties: { info: { id: "visible-session-4" } }, directory })

    assert.equal(prompts.length, 0)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
