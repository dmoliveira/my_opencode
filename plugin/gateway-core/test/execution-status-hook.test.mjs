import assert from "node:assert/strict"
import { mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { createExecutionStatusHook } from "../dist/hooks/execution-status/index.js"
import {
  loadGatewayState,
  resolveGatewayStatePath,
  updateGatewayStateDomain,
} from "../dist/state/storage.js"

async function withTempDir(run) {
  const directory = mkdtempSync(join(tmpdir(), "execution-status-hook-"))
  try {
    return await run(directory)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
}

function entry(directory, sessionId) {
  return loadGatewayState(directory)?.executionStatus?.sessions[sessionId]
}

test("execution-status records deterministic validation milestones", async () => {
  await withTempDir(async (directory) => {
    const hook = createExecutionStatusHook({
      directory,
      enabled: true,
      maxSessions: 8,
      maxLabelChars: 80,
    })
    const sessionID = "ses-parent"

    await hook.event("session.updated", { properties: { info: { id: sessionID } } })
    assert.deepEqual(entry(directory, sessionID) && {
      last: entry(directory, sessionID).last,
      next: entry(directory, sessionID).next,
    }, { last: "Session ready", next: "Begin execution" })

    await hook.event("tool.execute.before", {
      input: { tool: "bash", sessionID, args: { command: "make validate" } },
    })
    assert.equal(entry(directory, sessionID)?.next, "Run validation")

    await hook.event("tool.execute.after", {
      input: { tool: "bash", sessionID, args: { command: "make validate" } },
      output: { metadata: { exit: 0 } },
    })
    assert.deepEqual(entry(directory, sessionID) && {
      last: entry(directory, sessionID).last,
      next: entry(directory, sessionID).next,
    }, { last: "Validation passed", next: "Review changes" })
  })
})

test("execution-status isolates child sessions and records failures without output text", async () => {
  await withTempDir(async (directory) => {
    const hook = createExecutionStatusHook({
      directory,
      enabled: true,
      maxSessions: 8,
      maxLabelChars: 80,
    })
    const parent = "ses-parent"
    const child = "ses-child"

    await hook.event("tool.execute.before", {
      input: { tool: "edit", sessionID: parent },
    })
    await hook.event("tool.execute.after", {
      input: { tool: "edit", sessionID: parent },
      output: {},
    })
    await hook.event("tool.execute.before", {
      input: { tool: "bash", sessionID: child, args: { command: "make selftest" } },
    })
    await hook.event("tool.execute.after", {
      input: { tool: "bash", sessionID: child, args: { command: "make selftest" } },
      output: { metadata: { exit: 1 }, output: "sensitive failure output must not persist" },
    })

    assert.deepEqual(entry(directory, parent) && {
      last: entry(directory, parent).last,
      next: entry(directory, parent).next,
    }, { last: "Files updated", next: "Run validation" })
    assert.deepEqual(entry(directory, child) && {
      last: entry(directory, child).last,
      next: entry(directory, child).next,
    }, { last: "Validation failed", next: "Fix validation" })
    const raw = JSON.stringify(loadGatewayState(directory)?.executionStatus)
    assert.equal(raw.includes("sensitive failure output"), false)
  })
})

test("execution-status marks an OpenCode bash event complete when exit metadata is absent", async () => {
  await withTempDir(async (directory) => {
    const hook = createExecutionStatusHook({
      directory,
      enabled: true,
      maxSessions: 8,
      maxLabelChars: 80,
    })
    const sessionID = "ses-metadata"

    await hook.event("tool.execute.before", {
      input: { tool: "bash", sessionID, args: { command: "make validate" } },
    })
    await hook.event("tool.execute.after", {
      input: { tool: "bash", sessionID, args: { command: "make validate" } },
      output: {},
    })

    assert.deepEqual(entry(directory, sessionID) && {
      last: entry(directory, sessionID).last,
      next: entry(directory, sessionID).next,
    }, { last: "Validation completed", next: "Review changes" })
  })
})

test("gateway plugin dispatch writes a status from OpenCode tool payloads", async () => {
  await withTempDir(async (directory) => {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, disabled: [], order: ["execution-status"] },
        executionStatus: { enabled: true, maxSessions: 8, maxLabelChars: 80 },
      },
    })
    const sessionID = "ses-plugin-dispatch"

    await plugin.event({ event: { type: "session.created", properties: { info: { id: sessionID } } } })
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID },
      { args: { command: "make validate" } },
    )
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID, args: { command: "make validate" } },
      { metadata: { exit: 0 } },
    )

    assert.deepEqual(entry(directory, sessionID) && {
      last: entry(directory, sessionID).last,
      next: entry(directory, sessionID).next,
    }, { last: "Validation passed", next: "Review changes" })
  })
})

test("execution-status evicts old sessions while retaining the current session", async () => {
  await withTempDir(async (directory) => {
    const hook = createExecutionStatusHook({
      directory,
      enabled: true,
      maxSessions: 2,
      maxLabelChars: 80,
    })
    for (const sessionID of ["ses-one", "ses-two", "ses-three"]) {
      await hook.event("tool.execute.before", {
        input: { tool: "task", sessionID },
      })
      await new Promise((resolve) => setTimeout(resolve, 2))
    }
    const sessions = loadGatewayState(directory)?.executionStatus?.sessions ?? {}
    assert.equal(Object.keys(sessions).length, 2)
    assert.ok(sessions["ses-three"])
  })
})

test("execution-status honors its cap when older state has future timestamps", async () => {
  await withTempDir(async (directory) => {
    updateGatewayStateDomain(directory, "executionStatus", {
      version: 1,
      sessions: {
        "ses-future-one": {
          sessionId: "ses-future-one",
          last: "Old status",
          next: "Continue",
          updatedAt: "2099-01-01T00:00:00.000Z",
        },
        "ses-future-two": {
          sessionId: "ses-future-two",
          last: "Old status",
          next: "Continue",
          updatedAt: "2098-01-01T00:00:00.000Z",
        },
        "ses-current": {
          sessionId: "ses-current",
          last: "Session ready",
          next: "Run delegated work",
          updatedAt: "2020-01-01T00:00:00.000Z",
        },
      },
    })
    const hook = createExecutionStatusHook({
      directory,
      enabled: true,
      maxSessions: 2,
      maxLabelChars: 80,
    })

    await hook.event("tool.execute.before", {
      input: { tool: "task", sessionID: "ses-current" },
    })

    const sessions = loadGatewayState(directory)?.executionStatus?.sessions ?? {}
    assert.equal(Object.keys(sessions).length, 2)
    assert.ok(sessions["ses-current"])
    assert.ok(sessions["ses-future-one"])
    assert.equal(sessions["ses-future-two"], undefined)
  })
})

test("execution-status drops malformed legacy entries and cleans up deleted sessions", async () => {
  await withTempDir(async (directory) => {
    updateGatewayStateDomain(directory, "executionStatus", {
      version: 1,
      sessions: {
        "ses-unsafe": {
          sessionId: "ses-unsafe",
          last: "\u001b[31munsafe",
          next: "Continue",
          updatedAt: "not-a-timestamp",
        },
      },
    })
    const hook = createExecutionStatusHook({
      directory,
      enabled: true,
      maxSessions: 2,
      maxLabelChars: 80,
    })
    const sessionId = "ses-cleanup"

    await hook.event("tool.execute.before.error", {
      input: { tool: "bash", sessionId, args: { command: "make validate" } },
    })
    assert.deepEqual(entry(directory, sessionId) && {
      last: entry(directory, sessionId).last,
      next: entry(directory, sessionId).next,
    }, { last: "Validation failed", next: "Fix validation" })
    assert.equal(entry(directory, "ses-unsafe"), undefined)
    const raw = JSON.parse(readFileSync(resolveGatewayStatePath(directory), "utf8"))
    assert.equal(raw.executionStatus.sessions["ses-unsafe"], undefined)

    await hook.event("session.deleted", { properties: { info: { id: sessionId } } })
    assert.equal(entry(directory, sessionId), undefined)
  })
})

test("execution-status normalizes malformed state during a no-op status update", async () => {
  await withTempDir(async (directory) => {
    const sessionId = "ses-current"
    updateGatewayStateDomain(directory, "executionStatus", {
      version: 1,
      sessions: {
        [sessionId]: {
          sessionId,
          last: "Session ready",
          next: "Run delegated work",
          updatedAt: "2026-01-01T00:00:00.000Z",
        },
        "ses-unsafe": {
          sessionId: "ses-unsafe",
          last: "\u001b[31munsafe",
          next: "Continue",
          updatedAt: "not-a-timestamp",
        },
      },
    })
    const hook = createExecutionStatusHook({
      directory,
      enabled: true,
      maxSessions: 2,
      maxLabelChars: 80,
    })

    await hook.event("tool.execute.before", {
      input: { tool: "task", sessionID: sessionId },
    })

    const raw = JSON.parse(readFileSync(resolveGatewayStatePath(directory), "utf8"))
    assert.deepEqual(Object.keys(raw.executionStatus.sessions), [sessionId])
    assert.deepEqual(
      {
        sessionId: raw.executionStatus.sessions[sessionId].sessionId,
        last: raw.executionStatus.sessions[sessionId].last,
        next: raw.executionStatus.sessions[sessionId].next,
      },
      {
        sessionId,
        last: "Session ready",
        next: "Run delegated work",
      },
    )
    assert.ok(Number.isFinite(Date.parse(raw.executionStatus.sessions[sessionId].updatedAt)))
  })
})

test("execution-status deletes malformed state even when the deleted session is absent", async () => {
  await withTempDir(async (directory) => {
    updateGatewayStateDomain(directory, "executionStatus", {
      version: 1,
      sessions: {
        "ses-unsafe": {
          sessionId: "ses-unsafe",
          last: "\u001b[31munsafe",
          next: "Continue",
          updatedAt: "not-a-timestamp",
        },
      },
    })
    const hook = createExecutionStatusHook({
      directory,
      enabled: true,
      maxSessions: 2,
      maxLabelChars: 80,
    })

    await hook.event("session.deleted", { properties: { info: { id: "ses-absent" } } })

    const raw = JSON.parse(readFileSync(resolveGatewayStatePath(directory), "utf8"))
    assert.deepEqual(raw.executionStatus.sessions, {})
  })
})

test("execution-status does not rewrite an unchanged valid status", async () => {
  await withTempDir(async (directory) => {
    const sessionId = "ses-unchanged"
    updateGatewayStateDomain(directory, "executionStatus", {
      version: 1,
      sessions: {
        [sessionId]: {
          sessionId,
          last: "Session ready",
          next: "Run delegated work",
          updatedAt: "2026-01-01T00:00:00.000Z",
        },
      },
    })
    const path = resolveGatewayStatePath(directory)
    const before = readFileSync(path, "utf8")
    const hook = createExecutionStatusHook({
      directory,
      enabled: true,
      maxSessions: 2,
      maxLabelChars: 80,
    })

    await hook.event("tool.execute.before", {
      input: { tool: "task", sessionID: sessionId },
    })

    assert.equal(readFileSync(path, "utf8"), before)
  })
})
