import assert from "node:assert/strict"
import test from "node:test"

import { createTodoreadCadenceReminderHook } from "../dist/hooks/todoread-cadence-reminder/index.js"

test("todoread-cadence-reminder appends start reminder on session-start checkpoint output", async () => {
  const hook = createTodoreadCadenceReminderHook({ enabled: true, cooldownEvents: 2 })
  const payload = {
    input: { sessionID: "s1" },
    output: { output: "At the beginning of conversations, verify todo state." },
  }

  await hook.event("tool.execute.after", payload)

  assert.match(String(payload.output.output), /\[todoread CADENCE REMINDER\]/)
})

test("todoread-cadence-reminder appends checkpoint reminder after cooldown", async () => {
  const hook = createTodoreadCadenceReminderHook({ enabled: true, cooldownEvents: 2 })
  const first = { input: { sessionID: "s2" }, output: { output: "checkpoint not met" } }
  const second = { input: { sessionID: "s2" }, output: { output: "Completed work. Next step is implementing item 2." } }

  await hook.event("tool.execute.after", first)
  await hook.event("tool.execute.after", second)

  assert.match(String(second.output.output), /\[todoread CADENCE REMINDER\]/)
})

test("todoread-cadence-reminder resets state after session deletion", async () => {
  const hook = createTodoreadCadenceReminderHook({ enabled: true, cooldownEvents: 1 })
  const first = {
    input: { sessionID: "s3" },
    output: { output: "At the beginning of conversations, verify todo state." },
  }
  const second = {
    input: { sessionID: "s3" },
    output: { output: "At the beginning of conversations, verify todo state." },
  }

  await hook.event("tool.execute.after", first)
  await hook.event("session.deleted", { properties: { sessionID: "s3" } })
  await hook.event("tool.execute.after", second)

  assert.match(String(second.output.output), /\[todoread CADENCE REMINDER\]/)
})
