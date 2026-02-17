import assert from "node:assert/strict"
import test from "node:test"

import { createEditErrorRecoveryHook } from "../dist/hooks/edit-error-recovery/index.js"

test("edit-error-recovery appends guidance when edit output reports patch failure", async () => {
  const hook = createEditErrorRecoveryHook({ enabled: true })
  const payload = {
    input: { tool: "edit" },
    output: { output: "failed to apply patch: no matching lines found" },
  }

  await hook.event("tool.execute.after", payload)

  assert.match(String(payload.output.output), /\[edit ERROR RECOVERY\]/)
})

test("edit-error-recovery ignores non-edit tools", async () => {
  const hook = createEditErrorRecoveryHook({ enabled: true })
  const payload = {
    input: { tool: "bash" },
    output: { output: "failed to apply patch" },
  }

  await hook.event("tool.execute.after", payload)

  assert.equal(payload.output.output, "failed to apply patch")
})
