import assert from "node:assert/strict"
import test from "node:test"

import { createGlobalProcessPressureHook } from "../dist/hooks/global-process-pressure/index.js"

test("global-process-pressure appends warning when thresholds are exceeded", async () => {
  const hook = createGlobalProcessPressureHook({
    directory: process.cwd(),
    enabled: true,
    checkCooldownToolCalls: 1,
    reminderCooldownToolCalls: 1,
    criticalReminderCooldownToolCalls: 2,
    warningContinueSessions: 5,
    warningOpencodeProcesses: 10,
    warningMaxRssMb: 1400,
    criticalMaxRssMb: 10240,
    autoPauseOnCritical: true,
    guardMarkerMode: "both",
    guardVerbosity: "normal",
    maxSessionStateEntries: 16,
    sampler() {
      return {
        continueProcessCount: 8,
        opencodeProcessCount: 12,
        maxRssMb: 1800,
      }
    },
  })

  const payload = {
    input: { sessionID: "session-global-pressure-1" },
    output: { output: "tool result" },
    directory: process.cwd(),
  }
  await hook.event("tool.execute.after", payload)
  assert.ok(payload.output.output.includes("Context Guard"))
  assert.ok(payload.output.output.includes("Global process pressure"))
})

test("global-process-pressure respects reminder cooldown per session", async () => {
  const hook = createGlobalProcessPressureHook({
    directory: process.cwd(),
    enabled: true,
    checkCooldownToolCalls: 1,
    reminderCooldownToolCalls: 3,
    criticalReminderCooldownToolCalls: 4,
    warningContinueSessions: 2,
    warningOpencodeProcesses: 3,
    warningMaxRssMb: 200,
    criticalMaxRssMb: 10240,
    autoPauseOnCritical: true,
    guardMarkerMode: "both",
    guardVerbosity: "normal",
    maxSessionStateEntries: 16,
    sampler() {
      return {
        continueProcessCount: 8,
        opencodeProcessCount: 12,
        maxRssMb: 1800,
      }
    },
  })

  const first = {
    input: { sessionID: "session-global-pressure-2" },
    output: { output: "first" },
    directory: process.cwd(),
  }
  await hook.event("tool.execute.after", first)
  assert.ok(first.output.output.includes("Global process pressure"))

  const second = {
    input: { sessionID: "session-global-pressure-2" },
    output: { output: "second" },
    directory: process.cwd(),
  }
  await hook.event("tool.execute.after", second)
  assert.equal(second.output.output, "second")
})

test("global-process-pressure critical tier force-stops current session", async () => {
  const forcedStops = []
  const hook = createGlobalProcessPressureHook({
    directory: process.cwd(),
    stopGuard: {
      isStopped() {
        return false
      },
      forceStop(sessionId, reasonCode) {
        forcedStops.push({ sessionId, reasonCode })
      },
    },
    enabled: true,
    checkCooldownToolCalls: 1,
    reminderCooldownToolCalls: 2,
    criticalReminderCooldownToolCalls: 3,
    warningContinueSessions: 2,
    warningOpencodeProcesses: 3,
    warningMaxRssMb: 1400,
    criticalMaxRssMb: 10240,
    autoPauseOnCritical: true,
    guardMarkerMode: "both",
    guardVerbosity: "normal",
    maxSessionStateEntries: 16,
    sampler() {
      return {
        continueProcessCount: 4,
        opencodeProcessCount: 7,
        maxRssMb: 12000,
      }
    },
  })

  const payload = {
    input: { sessionID: "session-global-pressure-critical" },
    output: { output: "tool result" },
    directory: process.cwd(),
  }
  await hook.event("tool.execute.after", payload)

  assert.ok(payload.output.output.includes("Critical memory pressure"))
  assert.equal(forcedStops.length, 1)
  assert.deepEqual(forcedStops[0], {
    sessionId: "session-global-pressure-critical",
    reasonCode: "continuation_stopped_critical_memory_pressure",
  })
})

test("global-process-pressure still force-stops critical session on error output", async () => {
  const forcedStops = []
  const hook = createGlobalProcessPressureHook({
    directory: process.cwd(),
    stopGuard: {
      isStopped() {
        return false
      },
      forceStop(sessionId, reasonCode) {
        forcedStops.push({ sessionId, reasonCode })
      },
    },
    enabled: true,
    checkCooldownToolCalls: 1,
    reminderCooldownToolCalls: 2,
    criticalReminderCooldownToolCalls: 3,
    warningContinueSessions: 2,
    warningOpencodeProcesses: 3,
    warningMaxRssMb: 1400,
    criticalMaxRssMb: 10240,
    autoPauseOnCritical: true,
    guardMarkerMode: "both",
    guardVerbosity: "normal",
    maxSessionStateEntries: 16,
    sampler() {
      return {
        continueProcessCount: 4,
        opencodeProcessCount: 7,
        maxRssMb: 12000,
      }
    },
  })

  const payload = {
    input: { sessionID: "session-global-pressure-critical-error" },
    output: { output: "[ERROR] tool failed" },
    directory: process.cwd(),
  }
  await hook.event("tool.execute.after", payload)

  assert.equal(payload.output.output, "[ERROR] tool failed")
  assert.equal(forcedStops.length, 1)
  assert.deepEqual(forcedStops[0], {
    sessionId: "session-global-pressure-critical-error",
    reasonCode: "continuation_stopped_critical_memory_pressure",
  })
})
