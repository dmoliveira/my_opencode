import assert from "node:assert/strict"
import { mkdtempSync, readFileSync, rmSync } from "node:fs"
import { join } from "node:path"
import test from "node:test"
import { tmpdir } from "node:os"

import { createGlobalProcessPressureHook } from "../dist/hooks/global-process-pressure/index.js"

test("global-process-pressure appends warning when thresholds are exceeded", async () => {
  const hook = createGlobalProcessPressureHook({
    directory: process.cwd(),
    enabled: true,
    checkCooldownToolCalls: 1,
    reminderCooldownToolCalls: 1,
    criticalReminderCooldownToolCalls: 2,
    criticalEscalationWindowToolCalls: 10,
    criticalPauseAfterEvents: 1,
    criticalEscalationAfterEvents: 3,
    warningContinueSessions: 5,
    warningOpencodeProcesses: 10,
    warningMaxRssMb: 1400,
    criticalMaxRssMb: 10240,
    autoPauseOnCritical: true,
    notifyOnCritical: false,
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
    criticalEscalationWindowToolCalls: 10,
    criticalPauseAfterEvents: 1,
    criticalEscalationAfterEvents: 3,
    warningContinueSessions: 2,
    warningOpencodeProcesses: 3,
    warningMaxRssMb: 200,
    criticalMaxRssMb: 10240,
    autoPauseOnCritical: true,
    notifyOnCritical: false,
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
    criticalEscalationWindowToolCalls: 10,
    criticalPauseAfterEvents: 1,
    criticalEscalationAfterEvents: 3,
    warningContinueSessions: 2,
    warningOpencodeProcesses: 3,
    warningMaxRssMb: 1400,
    criticalMaxRssMb: 10240,
    autoPauseOnCritical: true,
    notifyOnCritical: false,
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
    criticalEscalationWindowToolCalls: 10,
    criticalPauseAfterEvents: 1,
    criticalEscalationAfterEvents: 3,
    warningContinueSessions: 2,
    warningOpencodeProcesses: 3,
    warningMaxRssMb: 1400,
    criticalMaxRssMb: 10240,
    autoPauseOnCritical: true,
    notifyOnCritical: false,
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

test("global-process-pressure supports staged pause ladder", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-global-pressure-"))
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  const forcedStops = []
  const hook = createGlobalProcessPressureHook({
    directory,
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
    reminderCooldownToolCalls: 1,
    criticalReminderCooldownToolCalls: 1,
    criticalEscalationWindowToolCalls: 10,
    criticalPauseAfterEvents: 2,
    criticalEscalationAfterEvents: 2,
    warningContinueSessions: 2,
    warningOpencodeProcesses: 3,
    warningMaxRssMb: 1400,
    criticalMaxRssMb: 10240,
    autoPauseOnCritical: true,
    notifyOnCritical: false,
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

  const first = {
    input: { sessionID: "session-global-pressure-ladder" },
    output: { output: "first" },
    directory,
  }
  await hook.event("tool.execute.after", first)
  assert.equal(forcedStops.length, 0)
  assert.ok(first.output.output.includes("pause is armed"))

  const second = {
    input: { sessionID: "session-global-pressure-ladder" },
    output: { output: "second" },
    directory,
  }
  await hook.event("tool.execute.after", second)
  assert.equal(forcedStops.length, 1)
  assert.ok(second.output.output.includes("repeatedly"))
  assert.deepEqual(forcedStops[0], {
    sessionId: "session-global-pressure-ladder",
    reasonCode: "continuation_stopped_critical_memory_pressure",
  })

  const auditPath = join(directory, ".opencode", "gateway-events.jsonl")
  const rows = readFileSync(auditPath, "utf-8")
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line))
  const criticalRows = rows.filter(
    (row) => row.reason_code === "global_process_pressure_critical_appended",
  )
  assert.ok(criticalRows.length >= 2)
  const lastTwo = criticalRows.slice(-2)
  assert.equal(lastTwo[0].critical_events_in_window, 1)
  assert.equal(lastTwo[1].critical_events_in_window, 2)
  assert.equal(lastTwo[1].critical_escalated, true)

  if (previousAudit === undefined) {
    delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  } else {
    process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
  }
  rmSync(directory, { recursive: true, force: true })
})


test("global-process-pressure appends self-session HIGH marker using any-operator", async () => {
  const hook = createGlobalProcessPressureHook({
    directory: process.cwd(),
    enabled: true,
    checkCooldownToolCalls: 1,
    reminderCooldownToolCalls: 1,
    criticalReminderCooldownToolCalls: 2,
    criticalEscalationWindowToolCalls: 10,
    criticalPauseAfterEvents: 1,
    criticalEscalationAfterEvents: 3,
    warningContinueSessions: 2,
    warningOpencodeProcesses: 3,
    warningMaxRssMb: 1400,
    criticalMaxRssMb: 10240,
    autoPauseOnCritical: true,
    notifyOnCritical: false,
    guardMarkerMode: "both",
    guardVerbosity: "normal",
    maxSessionStateEntries: 16,
    selfSeverityOperator: "any",
    selfHighCpuPct: 100,
    selfHighRssMb: 10240,
    selfHighElapsed: "5h",
    selfHighLabel: "HIGH",
    selfLowLabel: "LOW",
    selfAppendMarker: true,
    sampler() {
      return {
        continueProcessCount: 8,
        opencodeProcessCount: 12,
        maxRssMb: 1800,
        selfSession: {
          pid: 1234,
          cpuPct: 125,
          memPct: 1.1,
          rssMb: 900,
          elapsed: "00:06:00",
          elapsedSeconds: 360,
          cwd: "/tmp/session",
        },
      }
    },
  })

  const payload = {
    input: { sessionID: "session-global-pressure-self-any" },
    output: { output: "tool result" },
    directory: process.cwd(),
  }
  await hook.event("tool.execute.after", payload)

  assert.match(String(payload.output.output), /PRESSURE=HIGH/)
})

test("global-process-pressure appends LOW marker when all-operator is not satisfied", async () => {
  const hook = createGlobalProcessPressureHook({
    directory: process.cwd(),
    enabled: true,
    checkCooldownToolCalls: 1,
    reminderCooldownToolCalls: 1,
    criticalReminderCooldownToolCalls: 2,
    criticalEscalationWindowToolCalls: 10,
    criticalPauseAfterEvents: 1,
    criticalEscalationAfterEvents: 3,
    warningContinueSessions: 2,
    warningOpencodeProcesses: 3,
    warningMaxRssMb: 1400,
    criticalMaxRssMb: 10240,
    autoPauseOnCritical: true,
    notifyOnCritical: false,
    guardMarkerMode: "both",
    guardVerbosity: "normal",
    maxSessionStateEntries: 16,
    selfSeverityOperator: "all",
    selfHighCpuPct: 100,
    selfHighRssMb: 10240,
    selfHighElapsed: "5m",
    selfHighLabel: "HIGH",
    selfLowLabel: "LOW",
    selfAppendMarker: true,
    sampler() {
      return {
        continueProcessCount: 8,
        opencodeProcessCount: 12,
        maxRssMb: 1800,
        selfSession: {
          pid: 4567,
          cpuPct: 120,
          memPct: 1.1,
          rssMb: 700,
          elapsed: "00:04:00",
          elapsedSeconds: 240,
          cwd: "/tmp/session",
        },
      }
    },
  })

  const payload = {
    input: { sessionID: "session-global-pressure-self-all" },
    output: { output: "tool result" },
    directory: process.cwd(),
  }
  await hook.event("tool.execute.after", payload)

  assert.match(String(payload.output.output), /PRESSURE=LOW/)
})
