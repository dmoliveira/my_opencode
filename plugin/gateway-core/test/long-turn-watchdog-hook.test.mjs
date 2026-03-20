import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { createLongTurnWatchdogHook } from "../dist/hooks/long-turn-watchdog/index.js"

test("long-turn-watchdog appends warning when turn exceeds threshold", async () => {
  let currentMs = 0
  const hook = createLongTurnWatchdogHook({
    directory: process.cwd(),
    enabled: true,
    warningThresholdMs: 1000,
    toolCallWarningThreshold: 3,
    reminderCooldownMs: 5000,
    maxSessionStateEntries: 16,
    prefix: "[Turn Watchdog]:",
    now() {
      return currentMs
    },
  })

  await hook.event("chat.message", {
    properties: { sessionID: "turn-watchdog-session-1" },
  })

  currentMs = 1200
  const output = { output: "tool result" }
  await hook.event("tool.execute.after", {
    input: { sessionID: "turn-watchdog-session-1" },
    output,
    directory: process.cwd(),
  })

  assert.ok(output.output.includes("Turn Watchdog"))
  assert.ok(output.output.includes("Long turn detected"))
  assert.ok(output.output.includes("Still working"))

  currentMs = 2400
  const second = { output: "next tool result" }
  await hook.event("tool.execute.after", {
    input: { sessionID: "turn-watchdog-session-1" },
    output: second,
    directory: process.cwd(),
  })
  assert.equal(second.output, "next tool result")
})

test("long-turn-watchdog enforces cooldown across turns", async () => {
  let currentMs = 0
  const hook = createLongTurnWatchdogHook({
    directory: process.cwd(),
    enabled: true,
    warningThresholdMs: 1000,
    toolCallWarningThreshold: 3,
    reminderCooldownMs: 5000,
    maxSessionStateEntries: 16,
    prefix: "[Turn Watchdog]:",
    now() {
      return currentMs
    },
  })

  await hook.event("chat.message", {
    properties: { sessionID: "turn-watchdog-session-2" },
  })
  currentMs = 1200
  const first = { output: "first" }
  await hook.event("tool.execute.after", {
    input: { sessionID: "turn-watchdog-session-2" },
    output: first,
    directory: process.cwd(),
  })
  assert.ok(first.output.includes("Long turn detected"))

  currentMs = 2000
  await hook.event("chat.message", {
    properties: { sessionID: "turn-watchdog-session-2" },
  })
  currentMs = 3200
  const cooledDown = { output: "second" }
  await hook.event("tool.execute.after", {
    input: { sessionID: "turn-watchdog-session-2" },
    output: cooledDown,
    directory: process.cwd(),
  })
  assert.equal(cooledDown.output, "second")

  currentMs = 7000
  await hook.event("chat.message", {
    properties: { sessionID: "turn-watchdog-session-2" },
  })
  currentMs = 8500
  const afterCooldown = { output: "third" }
  await hook.event("tool.execute.after", {
    input: { sessionID: "turn-watchdog-session-2" },
    output: afterCooldown,
    directory: process.cwd(),
  })
  assert.ok(afterCooldown.output.includes("Long turn detected"))
})

test("long-turn-watchdog updates structured output channels", async () => {
  let currentMs = 0
  const hook = createLongTurnWatchdogHook({
    directory: process.cwd(),
    enabled: true,
    warningThresholdMs: 1000,
    toolCallWarningThreshold: 3,
    reminderCooldownMs: 5000,
    maxSessionStateEntries: 16,
    prefix: "[Turn Watchdog]:",
    now() {
      return currentMs
    },
  })

  await hook.event("chat.message", {
    properties: { sessionID: "turn-watchdog-session-3" },
  })

  currentMs = 1500
  const output = { output: { stdout: "tool stdout" } }
  await hook.event("tool.execute.after", {
    input: { sessionID: "turn-watchdog-session-3" },
    output,
    directory: process.cwd(),
  })

  assert.ok(output.output.stdout.includes("Long turn detected"))
  assert.ok(output.output.stdout.includes("Still working"))
})

test("long-turn-watchdog warns after repeated tool calls even before time threshold", async () => {
  let currentMs = 0
  const hook = createLongTurnWatchdogHook({
    directory: process.cwd(),
    enabled: true,
    warningThresholdMs: 10_000,
    toolCallWarningThreshold: 2,
    reminderCooldownMs: 5000,
    maxSessionStateEntries: 16,
    prefix: "[Turn Watchdog]:",
    now() {
      return currentMs
    },
  })

  await hook.event("chat.message", {
    properties: { sessionID: "turn-watchdog-session-4" },
  })

  const first = { output: "tool one" }
  await hook.event("tool.execute.after", {
    input: { sessionID: "turn-watchdog-session-4" },
    output: first,
    directory: process.cwd(),
  })
  assert.equal(first.output, "tool one")

  currentMs = 500
  const second = { output: "tool two" }
  await hook.event("tool.execute.after", {
    input: { sessionID: "turn-watchdog-session-4" },
    output: second,
    directory: process.cwd(),
  })
  assert.ok(second.output.includes("Long turn detected"))
  assert.ok(second.output.includes("Still working"))
})

test("long-turn-watchdog injects visible progress pulse when tool-only turn stalls", async () => {
  let currentMs = 0
  const hook = createLongTurnWatchdogHook({
    directory: process.cwd(),
    enabled: true,
    warningThresholdMs: 1000,
    toolCallWarningThreshold: 1,
    reminderCooldownMs: 5000,
    maxSessionStateEntries: 16,
    prefix: "[Turn Watchdog]:",
    now() {
      return currentMs
    },
  })

  await hook.event("chat.message", {
    properties: { sessionID: "turn-watchdog-session-visible-pulse" },
  })

  currentMs = 1500
  const output = { output: "tool result" }
  await hook.event("tool.execute.after", {
    input: { sessionID: "turn-watchdog-session-visible-pulse" },
    output,
    directory: process.cwd(),
  })

  assert.match(output.output, /\[runtime progress pulse\]/)
  assert.match(output.output, /Still working in this turn after 1\.5s and 1 tool call/)
})

test("long-turn-watchdog honors tool-call threshold from plugin config", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-long-turn-watchdog-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["long-turn-watchdog"],
          disabled: [],
        },
        longTurnWatchdog: {
          enabled: true,
          warningThresholdMs: 10_000,
          toolCallWarningThreshold: 2,
          reminderCooldownMs: 5_000,
          maxSessionStateEntries: 16,
          prefix: "[Turn Watchdog]:",
        },
      },
    })

    await plugin.event({
      event: {
        type: "chat.message",
        properties: { sessionID: "turn-watchdog-plugin-session" },
      },
    })

    const first = { output: "tool one" }
    await plugin["tool.execute.after"](
      { sessionID: "turn-watchdog-plugin-session" },
      first
    )
    assert.equal(first.output, "tool one")

    const second = { output: "tool two" }
    await plugin["tool.execute.after"](
      { sessionID: "turn-watchdog-plugin-session" },
      second
    )
    assert.ok(second.output.includes("Long turn detected"))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
