import assert from "node:assert/strict"
import test from "node:test"
import { registerV2ContextRedaction, registerV2TransportRedaction } from "../../dist/v2/provider-boundary.js"
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

test("V2 transport redacts JSON HTTP and websocket frames and fails closed", async () => {
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
  const dispose = await registerV2TransportRedaction(session, redactor)
  const request = new Request("http://127.0.0.1/test", {
    method: "POST", headers: { "content-type": "application/json", "content-length": "38" },
    body: JSON.stringify({ value: "secret-sentinel", control: "ok" }),
  })
  const event = { request }
  await hooks.get("http.request")(event)
  assert.deepEqual(await event.request.json(), { value: "[REDACTED]", control: "ok" })
  assert.equal(event.request.headers.get("content-length"), null)
  assert.equal((await request.json()).value, "secret-sentinel")
  const frame = { frame: JSON.stringify({ value: "secret-sentinel" }) }
  await hooks.get("experimental.ws.send")(frame)
  assert.deepEqual(JSON.parse(frame.frame), { value: "[REDACTED]" })
  for (const bad of ["bad", "null", '"string"']) {
    await assert.rejects(hooks.get("experimental.ws.send")({ frame: bad }), /refusing unscanned request/)
  }
  const unsupported = new Request("http://127.0.0.1/test", { method: "POST", headers: { "content-type": "text/plain" }, body: "secret-sentinel" })
  await assert.rejects(hooks.get("http.request")({ request: unsupported }), /refusing unscanned request/)
  const compressed = new Request("http://127.0.0.1/test", { method: "POST", headers: { "content-type": "application/json", "content-encoding": "gzip" }, body: "{}" })
  await assert.rejects(hooks.get("http.request")({ request: compressed }), /refusing unscanned request/)
  await dispose()
  assert.deepEqual(disposed, ["http.request", "experimental.ws.send"])
})

test("V2 transport registration rolls back on failure", async () => {
  const disposed = []
  const session = { async hook(kind) {
    if (kind === "experimental.ws.send") throw new Error("failed")
    return { async dispose() { disposed.push(kind) } }
  } }
  await assert.rejects(registerV2TransportRedaction(session, { async redactMutableValueAsync() {} }), /failed/)
  assert.deepEqual(disposed, ["http.request"])
})
