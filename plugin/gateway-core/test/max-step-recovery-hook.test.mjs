import assert from "node:assert/strict"
import test from "node:test"

import { createMaxStepRecoveryHook } from "../dist/hooks/max-step-recovery/index.js"

test("max-step-recovery appends guidance for maximum-step exhaustion output", async () => {
  const hook = createMaxStepRecoveryHook({ enabled: true })
  const payload = {
    output: {
      output: [
        "CRITICAL - MAXIMUM STEPS REACHED",
        "Tools are disabled until next user input.",
      ].join("\n"),
    },
  }

  await hook.event("tool.execute.after", payload)

  assert.match(String(payload.output.output), /\[max-step EXHAUSTION RECOVERY\]/)
})

test("max-step-recovery skips non-matching output", async () => {
  const hook = createMaxStepRecoveryHook({ enabled: true })
  const payload = {
    output: { output: "normal tool output" },
  }

  await hook.event("tool.execute.after", payload)

  assert.equal(payload.output.output, "normal tool output")
})

test("max-step-recovery avoids duplicate append", async () => {
  const hook = createMaxStepRecoveryHook({ enabled: true })
  const payload = {
    output: {
      output: [
        "CRITICAL - MAXIMUM STEPS REACHED",
        "Tools are disabled until next user input.",
        "[max-step EXHAUSTION RECOVERY]",
      ].join("\n"),
    },
  }

  await hook.event("tool.execute.after", payload)

  const count = String(payload.output.output).split("[max-step EXHAUSTION RECOVERY]").length - 1
  assert.equal(count, 1)
})
