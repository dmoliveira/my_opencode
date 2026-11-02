import assert from "node:assert/strict"
import { mkdtemp, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import { registerV2ShellGuards } from "../../dist/v2/shell-guards.js"

test("V2 shell guards translate input, apply rewrites, and reject unsafe commands", async () => {
  const directory = await mkdtemp(join(tmpdir(), "v2-shell-guard-"))
  let callback
  let disposed = false
  const tool = { async hook(name, handler) {
    assert.equal(name, "execute.before")
    callback = handler
    return { async dispose() { disposed = true } }
  } }
  try {
    const dispose = await registerV2ShellGuards(tool, async () => directory, {
      directory,
      noninteractive: { enabled: true, injectEnvPrefix: true, envPrefixes: ["CI=true"], prefixCommands: ["git"], blockedPatterns: [] },
      dangerous: { enabled: true, blockedPatterns: ["BLOCKED_SYNTHETIC"] },
    })
    const base = { sessionID: "ses_v2test", id: "call_test", agent: "build" }
    const allowed = { ...base, tool: "shell", input: { command: "git status" } }
    await callback(allowed)
    assert.match(allowed.input.command, /CI=true/)
    await assert.rejects(callback({ ...base, tool: "shell", input: { command: "printf BLOCKED_SYNTHETIC" } }), /Blocked dangerous/)
    await assert.rejects(callback({ ...base, tool: "shell", input: {} }), /refusing unguarded execution/)
    const other = { ...base, tool: "read", input: {} }
    await callback(other)
    assert.deepEqual(other.input, {})
    await dispose()
    assert.equal(disposed, true)
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
})

test("V2 shell guards fail closed when authoritative session location is unavailable", async () => {
  let callback
  await registerV2ShellGuards({ async hook(_name, handler) { callback = handler; return { async dispose() {} } } }, async () => "", {
    directory: "/tmp",
    noninteractive: { enabled: true, injectEnvPrefix: false, envPrefixes: [], prefixCommands: [], blockedPatterns: [] },
    dangerous: { enabled: true, blockedPatterns: [] },
  })
  await assert.rejects(callback({ tool: "shell", sessionID: "ses_test", input: { command: "pwd" } }), /session directory unavailable/)
})
