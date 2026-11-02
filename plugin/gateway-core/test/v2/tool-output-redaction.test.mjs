import assert from "node:assert/strict"
import test from "node:test"

import { createSecretRedactor } from "../../dist/hooks/shared/secret-redaction.js"
import { registerV2ToolOutputRedaction } from "../../dist/v2/tool-output-redaction.js"

test("V2 tool results redact content and output and block secrets in metadata", async () => {
  let callback
  let disposed = false
  const redactor = createSecretRedactor({
    patterns: ["secret-sentinel"], redactionToken: "[REDACTED]",
    limits: { maxDepth: 32, maxNodes: 1000, maxChars: 10000 },
  })
  const dispose = await registerV2ToolOutputRedaction({ async hook(name, handler) {
    assert.equal(name, "execute.after")
    callback = handler
    return { async dispose() { disposed = true } }
  } }, redactor)
  const event = { status: "completed", result: { content: [{ type: "text", text: "secret-sentinel" }], output: { value: "secret-sentinel" }, metadata: { detail: "safe" } } }
  await callback(event)
  assert.equal(event.result.content[0].text, "[REDACTED]")
  assert.equal(event.result.output.value, "[REDACTED]")
  assert.equal(event.result.metadata.detail, "safe")
  await assert.rejects(callback({ status: "completed", result: { metadata: { detail: "secret-sentinel" } } }), /immutable_match/)
  await assert.rejects(callback({ status: "completed", result: Object.freeze({ content: "secret-sentinel" }) }))
  await callback({ status: "error", error: new Error("synthetic") })
  await dispose()
  assert.equal(disposed, true)
})
