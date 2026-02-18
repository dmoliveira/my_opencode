import assert from "node:assert/strict"
import test from "node:test"

import { createLongTurnWatchdogHook } from "../dist/hooks/long-turn-watchdog/index.js"

test("long-turn-watchdog appends warning when turn exceeds threshold", async () => {
  let currentMs = 0
  const hook = createLongTurnWatchdogHook({
    directory: process.cwd(),
    enabled: true,
    warningThresholdMs: 1000,
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
