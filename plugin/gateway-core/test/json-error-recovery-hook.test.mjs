import assert from "node:assert/strict"
import test from "node:test"

import { createJsonErrorRecoveryHook } from "../dist/hooks/json-error-recovery/index.js"

test("json-error-recovery appends guidance on JSON parse failures", async () => {
  const hook = createJsonErrorRecoveryHook({ enabled: true })
  const payload = {
    input: { tool: "bash" },
    output: { output: "JSON parse error: unexpected token at position 1" },
  }

  await hook.event("tool.execute.after", payload)

  assert.match(String(payload.output.output), /\[json ERROR RECOVERY\]/)
})

test("json-error-recovery avoids duplicate guidance", async () => {
  const hook = createJsonErrorRecoveryHook({ enabled: true })
  const payload = {
    input: { tool: "bash" },
    output: { output: `invalid JSON\n\n[json ERROR RECOVERY]` },
  }

  await hook.event("tool.execute.after", payload)

  assert.equal(String(payload.output.output).match(/\[json ERROR RECOVERY\]/g)?.length, 1)
})
