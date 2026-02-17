import assert from "node:assert/strict"
import test from "node:test"

import { createPressureEscalationGuardHook } from "../dist/hooks/pressure-escalation-guard/index.js"

test("pressure-escalation-guard blocks reviewer task escalation under high pressure", async () => {
  const hook = createPressureEscalationGuardHook({
    directory: process.cwd(),
    enabled: true,
    maxContinueBeforeBlock: 3,
    blockedSubagentTypes: ["reviewer"],
    allowPromptPatterns: ["critical"],
    sampleContinueCount() {
      return 5
    },
  })
  await assert.rejects(
    hook.event("tool.execute.before", {
      input: { tool: "task", sessionID: "session-pressure-1" },
      output: {
        args: {
          subagent_type: "reviewer",
          prompt: "review this change",
        },
      },
      directory: process.cwd(),
    }),
    /Blocked reviewer subagent escalation/,
  )
})

test("pressure-escalation-guard allows escalation with blocker override pattern", async () => {
  const hook = createPressureEscalationGuardHook({
    directory: process.cwd(),
    enabled: true,
    maxContinueBeforeBlock: 3,
    blockedSubagentTypes: ["reviewer"],
    allowPromptPatterns: ["critical", "blocker"],
    sampleContinueCount() {
      return 6
    },
  })
  await hook.event("tool.execute.before", {
    input: { tool: "task", sessionID: "session-pressure-2" },
    output: {
      args: {
        subagent_type: "reviewer",
        prompt: "critical blocker triage needed",
      },
    },
    directory: process.cwd(),
  })
})
