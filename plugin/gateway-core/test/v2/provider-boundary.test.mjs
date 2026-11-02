import assert from "node:assert/strict"
import test from "node:test"
import { registerV2ContextRedaction } from "../../dist/v2/provider-boundary.js"
import { createSecretRedactor } from "../../dist/hooks/shared/secret-redaction.js"

test("V2 redacts system and messages for each model request kind", async () => {
  const hooks = new Map()
  const disposed = []
  const session = { async hook(kind, callback) {
    hooks.set(kind, callback)
    return { async dispose() { disposed.push(kind) } }
  } }
  const redactor = createSecretRedactor({
    patterns: ["secret-sentinel"], redactionToken: "[REDACTED]",
    limits: { maxDepth: 32, maxNodes: 1000, maxChars: 10000 },
  })
  const dispose = await registerV2ContextRedaction(session, redactor)
  assert.deepEqual([...hooks.keys()], ["context", "compaction", "generate", "title"])
  for (const hook of hooks.values()) {
    const event = { system: [{ type: "text", text: "secret-sentinel" }], messages: [{ role: "user", content: "secret-sentinel" }] }
    await hook(event)
    assert.equal(event.system[0].text, "[REDACTED]")
    assert.equal(event.messages[0].content, "[REDACTED]")
    await assert.rejects(hook({ system: null, messages: [] }), /refusing unscanned request/)
  }
  await dispose()
  assert.equal(disposed.length, 4)
})

test("V2 registration failure removes previously registered hooks", async () => {
  const disposed = []
  const session = { async hook(kind) {
    if (kind === "generate") throw new Error("failed")
    return { async dispose() { disposed.push(kind) } }
  } }
  await assert.rejects(registerV2ContextRedaction(session, { async redactMutableValueAsync() {} }), /failed/)
  assert.deepEqual(disposed, ["context", "compaction"])
})
