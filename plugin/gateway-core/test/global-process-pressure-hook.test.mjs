import assert from "node:assert/strict"
import test from "node:test"

import { createGlobalProcessPressureHook } from "../dist/hooks/global-process-pressure/index.js"

test("global-process-pressure appends warning when thresholds are exceeded", async () => {
  const hook = createGlobalProcessPressureHook({
    directory: process.cwd(),
    enabled: true,
    checkCooldownToolCalls: 1,
    reminderCooldownToolCalls: 1,
    warningContinueSessions: 5,
    warningOpencodeProcesses: 10,
    warningMaxRssMb: 1400,
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
    warningContinueSessions: 2,
    warningOpencodeProcesses: 3,
    warningMaxRssMb: 200,
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
