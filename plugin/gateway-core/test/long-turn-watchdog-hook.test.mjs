import assert from "node:assert/strict"
import { mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import { resetGatewayEventAuditStateForTest } from "../dist/audit/event-audit.js"
import GatewayCorePlugin from "../dist/index.js"
import { createLongTurnWatchdogHook } from "../dist/hooks/long-turn-watchdog/index.js"

const LEGACY_TIME_ONLY_SUFFIX_CHARS = 161
const LEGACY_PULSE_SUFFIX_CHARS = 302
const TIME_ONLY_SUFFIX =
  "\n\n[Turn Watchdog]: Long turn (1.2s since user, 1 tool call); still working toward the final reply."
const PULSE_SUFFIX =
  "\n\n[Turn Watchdog]: Long turn (1.5s since user, 1 tool call); still working; final reply follows when this step clears."
const REALISTIC_PULSE_SUFFIX =
  "\n\n[Turn Watchdog]: Long turn (90.0s since user, 20 tool calls); still working; final reply follows when this step clears."

function assertAtLeast35PercentReduction(legacyChars, currentChars) {
  assert.ok((legacyChars - currentChars) * 100 >= legacyChars * 35)
}

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

  assert.equal(output.output, `tool result${TIME_ONLY_SUFFIX}`)
  assert.equal(TIME_ONLY_SUFFIX.length, 98)
  assert.equal(Buffer.byteLength(TIME_ONLY_SUFFIX), 98)
  assert.ok(TIME_ONLY_SUFFIX.length <= 100)
  assertAtLeast35PercentReduction(LEGACY_TIME_ONLY_SUFFIX_CHARS, TIME_ONLY_SUFFIX.length)

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
  assert.match(first.output, /Long turn/)

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
  assert.match(afterCooldown.output, /Long turn/)
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
  const output = {
    output: {
      stdout: "tool stdout",
      output: "preserve output",
      message: "preserve message",
      stderr: "preserve stderr",
    },
  }
  await hook.event("tool.execute.after", {
    input: { sessionID: "turn-watchdog-session-3" },
    output,
    directory: process.cwd(),
  })

  assert.deepEqual(output.output, {
    stdout:
      "tool stdout\n\n[Turn Watchdog]: Long turn (1.5s since user, 1 tool call); still working toward the final reply.",
    output: "preserve output",
    message: "preserve message",
    stderr: "preserve stderr",
  })
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
  assert.match(second.output, /Long turn/)
  assert.match(second.output, /still working/)
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

  assert.equal(output.output, `tool result${PULSE_SUFFIX}`)
  assert.equal(PULSE_SUFFIX.length, 118)
  assert.equal(Buffer.byteLength(PULSE_SUFFIX), 118)
  assert.ok(PULSE_SUFFIX.length <= 120)
  assertAtLeast35PercentReduction(LEGACY_PULSE_SUFFIX_CHARS, PULSE_SUFFIX.length)
})

test("long-turn-watchdog preserves custom and fallback prefixes", async () => {
  for (const { prefix, expectedPrefix, sessionID } of [
    { prefix: "  [Watch]:  ", expectedPrefix: "[Watch]:", sessionID: "custom" },
    { prefix: "   ", expectedPrefix: "[Turn Watchdog]:", sessionID: "fallback" },
  ]) {
    let currentMs = 0
    const hook = createLongTurnWatchdogHook({
      directory: process.cwd(),
      enabled: true,
      warningThresholdMs: 1000,
      toolCallWarningThreshold: 3,
      reminderCooldownMs: 5000,
      maxSessionStateEntries: 16,
      prefix,
      now() {
        return currentMs
      },
    })
    await hook.event("chat.message", { properties: { sessionID } })
    currentMs = 1200
    const output = { output: "tool result" }
    await hook.event("tool.execute.after", {
      input: { sessionID },
      output,
      directory: process.cwd(),
    })
    assert.equal(
      output.output,
      `tool result\n\n${expectedPrefix} Long turn (1.2s since user, 1 tool call); still working toward the final reply.`
    )
  }
})

test("long-turn-watchdog keeps a realistic pulse within its byte budget", async () => {
  let currentMs = 0
  const hook = createLongTurnWatchdogHook({
    directory: process.cwd(),
    enabled: true,
    warningThresholdMs: 1_000_000,
    toolCallWarningThreshold: 20,
    reminderCooldownMs: 5000,
    maxSessionStateEntries: 16,
    prefix: "[Turn Watchdog]:",
    now() {
      return currentMs
    },
  })
  await hook.event("chat.message", {
    properties: { sessionID: "turn-watchdog-realistic-pulse" },
  })
  currentMs = 90_000
  for (let call = 1; call < 20; call += 1) {
    const output = { output: `tool ${call}` }
    await hook.event("tool.execute.after", {
      input: { sessionID: "turn-watchdog-realistic-pulse" },
      output,
      directory: process.cwd(),
    })
    assert.equal(output.output, `tool ${call}`)
  }
  const output = { output: "tool 20" }
  await hook.event("tool.execute.after", {
    input: { sessionID: "turn-watchdog-realistic-pulse" },
    output,
    directory: process.cwd(),
  })
  assert.equal(output.output, `tool 20${REALISTIC_PULSE_SUFFIX}`)
  assert.equal(REALISTIC_PULSE_SUFFIX.length, 121)
  assert.equal(Buffer.byteLength(REALISTIC_PULSE_SUFFIX), 121)
  assert.ok(REALISTIC_PULSE_SUFFIX.length <= 125)
})

test("long-turn-watchdog preserves time and pulse audit telemetry", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-long-turn-watchdog-audit-"))
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  const previousAuditPath = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH
  resetGatewayEventAuditStateForTest()
  try {
    for (const fixture of [
      {
        sessionID: "turn-watchdog-audit-time",
        currentMs: 1200,
        warningThresholdMs: 1000,
        toolCallWarningThreshold: 3,
        visibleProgressPulse: false,
      },
      {
        sessionID: "turn-watchdog-audit-pulse",
        currentMs: 1500,
        warningThresholdMs: 1000,
        toolCallWarningThreshold: 1,
        visibleProgressPulse: true,
      },
    ]) {
      let currentMs = 0
      const hook = createLongTurnWatchdogHook({
        directory,
        enabled: true,
        warningThresholdMs: fixture.warningThresholdMs,
        toolCallWarningThreshold: fixture.toolCallWarningThreshold,
        reminderCooldownMs: 5000,
        maxSessionStateEntries: 16,
        prefix: "[Turn Watchdog]:",
        now() {
          return currentMs
        },
      })
      await hook.event("chat.message", {
        properties: { sessionID: fixture.sessionID },
      })
      currentMs = fixture.currentMs
      await hook.event("tool.execute.after", {
        input: { sessionID: fixture.sessionID },
        output: { output: "tool result" },
        directory,
      })
    }

    const events = readFileSync(join(directory, ".opencode", "gateway-events.jsonl"), "utf8")
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => JSON.parse(line))
      .filter((entry) => entry.reason_code === "long_turn_warning")
    assert.equal(events.length, 2)
    assert.deepEqual(
      events.map((entry) => ({
        elapsed_ms: entry.elapsed_ms,
        tool_calls_this_turn: entry.tool_calls_this_turn,
        visible_progress_pulse: entry.visible_progress_pulse,
        tool_call_warning_threshold: entry.tool_call_warning_threshold,
        warning_threshold_ms: entry.warning_threshold_ms,
        turn_started_at: entry.turn_started_at,
      })),
      [
        {
          elapsed_ms: 1200,
          tool_calls_this_turn: 1,
          visible_progress_pulse: false,
          tool_call_warning_threshold: 3,
          warning_threshold_ms: 1000,
          turn_started_at: "1970-01-01T00:00:00.000Z",
        },
        {
          elapsed_ms: 1500,
          tool_calls_this_turn: 1,
          visible_progress_pulse: true,
          tool_call_warning_threshold: 1,
          warning_threshold_ms: 1000,
          turn_started_at: "1970-01-01T00:00:00.000Z",
        },
      ]
    )
  } finally {
    resetGatewayEventAuditStateForTest()
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    }
    if (previousAuditPath === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH = previousAuditPath
    }
    rmSync(directory, { recursive: true, force: true })
  }
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
    assert.match(second.output, /Long turn/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
