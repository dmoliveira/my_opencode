import assert from "node:assert/strict"
import test from "node:test"

import { createHashlineReadEnhancerHook } from "../dist/hooks/hashline-read-enhancer/index.js"

test("hashline-read-enhancer appends stable hash tags to read lines", async () => {
  const hook = createHashlineReadEnhancerHook({ enabled: true })
  const payload = {
    input: { tool: "read" },
    output: {
      output: `1: first line\n2: second line`,
    },
  }

  await hook.event("tool.execute.after", payload)

  const output = String(payload.output.output)
  assert.match(output, /1: first line \[h:[0-9a-f]{8}\]/)
  assert.match(output, /2: second line \[h:[0-9a-f]{8}\]/)
})

test("hashline-read-enhancer avoids duplicate hash tags", async () => {
  const hook = createHashlineReadEnhancerHook({ enabled: true })
  const payload = {
    input: { tool: "read" },
    output: {
      output: "1: first line [h:1234abcd]",
    },
  }

  await hook.event("tool.execute.after", payload)

  assert.equal(String(payload.output.output), "1: first line [h:1234abcd]")
})
