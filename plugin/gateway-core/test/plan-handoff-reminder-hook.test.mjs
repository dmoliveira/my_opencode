import assert from "node:assert/strict"
import test from "node:test"

import { createPlanHandoffReminderHook } from "../dist/hooks/plan-handoff-reminder/index.js"

test("plan-handoff-reminder appends plan-enter reminder", async () => {
  const hook = createPlanHandoffReminderHook({ enabled: true })
  const payload = {
    input: { sessionID: "s1" },
    output: {
      output: "Use this tool to suggest switching to plan agent when the user's request would benefit from planning first.",
    },
  }

  await hook.event("tool.execute.after", payload)

  assert.match(String(payload.output.output), /\[plan HANDOFF REMINDER\]/)
  assert.match(String(payload.output.output), /Plan-enter handoff reminder detected/)
})

test("plan-handoff-reminder appends plan-exit reminder", async () => {
  const hook = createPlanHandoffReminderHook({ enabled: true })
  const payload = {
    input: { sessionID: "s2" },
    output: {
      output: "Use this tool when you have completed the planning phase and are ready to exit plan agent and switch to build agent.",
    },
  }

  await hook.event("tool.execute.after", payload)

  assert.match(String(payload.output.output), /Plan-exit handoff reminder detected/)
})

test("plan-handoff-reminder suppresses duplicates and resets on session.deleted", async () => {
  const hook = createPlanHandoffReminderHook({ enabled: true })
  const first = {
    input: { sessionID: "s3" },
    output: {
      output: "Use this tool to suggest switching to plan agent when the user's request would benefit from planning first.",
    },
  }
  const second = {
    input: { sessionID: "s3" },
    output: {
      output: "Use this tool to suggest switching to plan agent when the user's request would benefit from planning first.",
    },
  }

  await hook.event("tool.execute.after", first)
  await hook.event("tool.execute.after", second)
  assert.equal(second.output.output.includes("[plan HANDOFF REMINDER]"), false)

  await hook.event("session.deleted", { properties: { sessionID: "s3" } })
  await hook.event("tool.execute.after", second)
  assert.match(String(second.output.output), /\[plan HANDOFF REMINDER\]/)
})
