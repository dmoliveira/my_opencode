import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import { createCompactionTodoPreserverHook } from "../dist/hooks/compaction-todo-preserver/index.js"

test("compaction-todo-preserver restores snapshot on session.compacted", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-compaction-todo-"))
  try {
    let promptCalls = 0
    const hook = createCompactionTodoPreserverHook({
      directory,
      enabled: true,
      maxChars: 4000,
      client: {
        session: {
          async promptAsync() {
            promptCalls += 1
          },
          async messages() {
            return { data: [] }
          },
        },
      },
    })

    await hook.event("tool.execute.after", {
      directory,
      input: { tool: "task", sessionID: "session-compact-1" },
      output: { output: "pending tasks remain\n<CONTINUE-LOOP>" },
    })
    await hook.event("session.compacted", {
      directory,
      properties: { info: { id: "session-compact-1" } },
    })

    assert.equal(promptCalls, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("compaction-todo-preserver does not restore when no snapshot exists", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-compaction-todo-"))
  try {
    let promptCalls = 0
    const hook = createCompactionTodoPreserverHook({
      directory,
      enabled: true,
      maxChars: 4000,
      client: {
        session: {
          async promptAsync() {
            promptCalls += 1
          },
          async messages() {
            return { data: [] }
          },
        },
      },
    })

    await hook.event("session.compacted", {
      directory,
      properties: { info: { id: "session-compact-2" } },
    })

    assert.equal(promptCalls, 0)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("compaction-todo-preserver clears snapshot on session.deleted", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-compaction-todo-"))
  try {
    let promptCalls = 0
    const hook = createCompactionTodoPreserverHook({
      directory,
      enabled: true,
      maxChars: 4000,
      client: {
        session: {
          async promptAsync() {
            promptCalls += 1
          },
          async messages() {
            return { data: [] }
          },
        },
      },
    })

    await hook.event("tool.execute.after", {
      directory,
      input: { tool: "task", sessionID: "session-compact-3" },
      output: { output: "pending tasks remain\n<CONTINUE-LOOP>" },
    })
    await hook.event("session.deleted", {
      directory,
      properties: { info: { id: "session-compact-3" } },
    })
    await hook.event("session.compacted", {
      directory,
      properties: { info: { id: "session-compact-3" } },
    })

    assert.equal(promptCalls, 0)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("compaction-todo-preserver clears stale snapshot when marker disappears", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-compaction-todo-"))
  try {
    let promptCalls = 0
    const hook = createCompactionTodoPreserverHook({
      directory,
      enabled: true,
      maxChars: 4000,
      client: {
        session: {
          async promptAsync() {
            promptCalls += 1
          },
          async messages() {
            return { data: [] }
          },
        },
      },
    })

    await hook.event("tool.execute.after", {
      directory,
      input: { tool: "task", sessionID: "session-compact-4" },
      output: { output: "pending tasks remain\n<CONTINUE-LOOP>" },
    })
    await hook.event("tool.execute.after", {
      directory,
      input: { tool: "task", sessionID: "session-compact-4" },
      output: { output: "all tasks complete" },
    })
    await hook.event("session.compacted", {
      directory,
      properties: { info: { id: "session-compact-4" } },
    })

    assert.equal(promptCalls, 0)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
