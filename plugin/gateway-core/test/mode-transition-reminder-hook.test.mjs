import assert from "node:assert/strict"
import test from "node:test"

import { createModeTransitionReminderHook } from "../dist/hooks/mode-transition-reminder/index.js"

test("mode-transition-reminder appends plan-mode guidance", async () => {
  const hook = createModeTransitionReminderHook({ enabled: true })
  const payload = {
    input: { sessionID: "s-plan" },
    output: {
      output: "Plan mode is active. You must not execute mutating commands.",
    },
  }

  await hook.event("tool.execute.after", payload)

  assert.match(String(payload.output.output), /\[mode-transition REMINDER\]/)
  assert.match(String(payload.output.output), /Plan mode reminder detected/)
})

test("mode-transition-reminder appends build transition guidance", async () => {
  const hook = createModeTransitionReminderHook({ enabled: true })
  const payload = {
    input: { sessionID: "s-build" },
    output: {
      output: [
        "Your operational mode has changed from plan to build.",
        "You are no longer in read-only mode.",
      ].join("\n"),
    },
  }

  await hook.event("tool.execute.after", payload)

  assert.match(String(payload.output.output), /Plan-to-build transition detected/)
})

test("mode-transition-reminder suppresses duplicate reminders per session mode", async () => {
  const hook = createModeTransitionReminderHook({ enabled: true })
  const first = {
    input: { sessionID: "s-dup" },
    output: { output: "Plan mode is active." },
  }
  const second = {
    input: { sessionID: "s-dup" },
    output: { output: "Plan mode is active." },
  }

  await hook.event("tool.execute.after", first)
  await hook.event("tool.execute.after", second)

  assert.match(String(first.output.output), /\[mode-transition REMINDER\]/)
  assert.equal(second.output.output, "Plan mode is active.")
})

test("mode-transition-reminder resets session state on session.deleted", async () => {
  const hook = createModeTransitionReminderHook({ enabled: true })
  const first = {
    input: { sessionID: "s-reset" },
    output: { output: "Plan mode is active." },
  }
  const second = {
    input: { sessionID: "s-reset" },
    output: { output: "Plan mode is active." },
  }

  await hook.event("tool.execute.after", first)
  await hook.event("session.deleted", { properties: { sessionID: "s-reset" } })
  await hook.event("tool.execute.after", second)

  assert.match(String(second.output.output), /\[mode-transition REMINDER\]/)
})
