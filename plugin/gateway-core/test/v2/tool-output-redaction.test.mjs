import assert from "node:assert/strict"
import test from "node:test"

import { createSecretRedactor } from "../../dist/hooks/shared/secret-redaction.js"
import { registerV2ToolOutputRedaction } from "../../dist/v2/tool-output-redaction.js"

function createToolError(message, cause) {
  const error = new Error(message)
  if (cause !== undefined) error.error = cause
  return error
}
const VERSION = "2.2.5"

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
  } }, redactor, createToolError, VERSION)
  const event = { status: "completed", result: { content: [{ type: "text", text: "secret-sentinel" }], output: { value: "secret-sentinel" }, metadata: { detail: "safe" } } }
  await callback(event)
  assert.equal(event.result.content[0].text, "[REDACTED]")
  assert.equal(event.result.output.value, "[REDACTED]")
  assert.equal(event.result.metadata.detail, "safe")
  await assert.rejects(callback({ status: "completed", result: { metadata: { detail: "secret-sentinel" } } }), /Tool output withheld because redaction failed/)
  await assert.rejects(callback({ status: "completed", result: Object.freeze({ content: "secret-sentinel" }) }), /Tool output withheld because redaction failed/)
  await dispose()
  assert.equal(disposed, true)
})

test("V2 tool errors are replaced with sanitized messages and no original cause or metadata", async () => {
  let callback
  const redactor = createSecretRedactor({
    patterns: ["secret-sentinel"], redactionToken: "[REDACTED]",
    limits: { maxDepth: 32, maxNodes: 1000, maxChars: 10000 },
  })
  await registerV2ToolOutputRedaction({ async hook(_name, handler) {
    callback = handler
    return { async dispose() {} }
  } }, redactor, createToolError, VERSION)
  const original = new Error("safe prefix secret-sentinel", { cause: new Error("secret-sentinel") })
  original.metadata = { secret: "secret-sentinel" }
  const event = { status: "error", error: original }
  await callback(event)
  assert.notEqual(event.error, original)
  assert.equal(event.error.message, "safe prefix [REDACTED]")
  assert.equal(event.error.cause, undefined)
  assert.equal(event.error.metadata, undefined)
  assert.doesNotMatch(event.error.stack, /secret-sentinel/)
  const safe = { status: "error", error: new Error("ordinary failure") }
  await callback(safe)
  assert.equal(safe.error.message, "ordinary failure")
})

test("V2 permission rejection retains its host type without copying its data", async () => {
  let callback
  const effectBase = Object.create(Error.prototype)
  for (const key of [
    "constructor", "~effect/Effect", "pipe", "toJSON", "~effect/Effect/identifier",
    "~effect/Effect/evaluate", "~effect/Effect/successCont", "~effect/Effect/failureCont",
    "~effect/Effect/ensureCont", Symbol.for("nodejs.util.inspect.custom"), Symbol.iterator,
  ]) Object.defineProperty(effectBase, key, { value() {} })
  const schemaBase = Object.create(effectBase, { constructor: { value() {} }, toJSON: { value() {} } })
  const schema = Object.create(schemaBase, {
    constructor: { value() {} },
    name: { value: "Permission.DeclinedError" },
    "~effect/Schema/Class/Permission.DeclinedError": { get() { return true } },
  })
  const prototype = Object.create(schema, { constructor: { value() {} } })
  const cause = Object.create(prototype, {
    _tag: { value: "Permission.DeclinedError" },
    privateDetail: { value: "secret-sentinel" },
    stack: { value: "secret-sentinel" },
  })
  await registerV2ToolOutputRedaction({ async hook(_name, handler) {
    callback = handler
    return { async dispose() {} }
  } }, createSecretRedactor({
    patterns: ["secret-sentinel"], redactionToken: "[REDACTED]",
    limits: { maxDepth: 32, maxNodes: 1000, maxChars: 10000 },
  }), createToolError, VERSION)
  const original = new Error("secret-sentinel")
  original.error = cause
  const event = { status: "error", error: original }
  await callback(event)
  assert.equal(event.error.message, "[REDACTED]")
  assert.equal(Object.getPrototypeOf(event.error.error), prototype)
  assert.notEqual(event.error.error, original.error)
  assert.deepEqual(Object.getOwnPropertyNames(event.error.error), ["_tag", "name", "message", "stack", "toString", "toJSON"])
  assert.equal(event.error.error._tag, "Permission.DeclinedError")
  assert.equal(event.error.error.message, "")
  assert.equal(event.error.error.stack, "")
  assert.equal(JSON.stringify(event.error.error), '{"_tag":"Permission.DeclinedError"}')

  class PoisonedDeclined extends Error {
    get message() { return "secret-sentinel" }
  }
  const poisoned = new Error("safe")
  poisoned.error = new PoisonedDeclined()
  poisoned.error._tag = "Permission.DeclinedError"
  const unsafe = { status: "error", error: poisoned }
  await callback(unsafe)
  assert.equal(unsafe.error.message, "safe")
  assert.equal(unsafe.error.error, undefined)

  class PoisonBase extends Error { get message() { return "secret-sentinel" } }
  class ForgedSchema extends PoisonBase {}
  Object.defineProperty(ForgedSchema.prototype, "name", { value: "Permission.DeclinedError" })
  Object.defineProperty(ForgedSchema.prototype, "~effect/Schema/Class/Permission.DeclinedError", { get() { return true } })
  class ForgedDecline extends ForgedSchema {}
  const forged = new Error("safe")
  forged.error = new ForgedDecline()
  forged.error._tag = "Permission.DeclinedError"
  const inherited = { status: "error", error: forged }
  await callback(inherited)
  assert.equal(inherited.error.error, undefined)
})

test("V2 tool errors fail closed for unsafe shapes, accessors, controls and redactor failures", async () => {
  let callback
  let getterCalled = false
  const redactor = createSecretRedactor({
    patterns: ["secret-sentinel"], redactionToken: "[REDACTED]",
    limits: { maxDepth: 4, maxNodes: 8, maxChars: 50 },
  })
  await registerV2ToolOutputRedaction({ async hook(_name, handler) {
    callback = handler
    return { async dispose() {} }
  } }, redactor, createToolError, VERSION)
  const accessor = Object.defineProperty({}, "message", { get() { getterCalled = true; throw new Error("secret-sentinel") } })
  const proxy = new Proxy({}, { getOwnPropertyDescriptor() { throw new Error("secret-sentinel") } })
  for (const error of [null, "secret-sentinel", accessor, proxy, new Error("x".repeat(100)), new Error("\u001b[31msecret-sentinel")]) {
    const event = { status: "error", error }
    await callback(event)
    assert.equal(event.error.message, "Tool execution failed; details withheld by gateway")
  }
  assert.equal(getterCalled, false)
  let throwingCallback
  await registerV2ToolOutputRedaction({ async hook(_name, handler) {
    throwingCallback = handler
    return { async dispose() {} }
  } }, { async redactMutableValueAsync() { throw new Error("secret-sentinel") } }, createToolError, VERSION)
  const failedRedaction = { status: "error", error: new Error("safe") }
  await throwingCallback(failedRedaction)
  assert.equal(failedRedaction.error.message, "Tool execution failed; details withheld by gateway")
  await assert.rejects(throwingCallback({ status: "completed", result: { content: "secret-sentinel" } }), /^Error: Tool output withheld because redaction failed$/)
  const assignmentFailure = new Proxy({ status: "completed", result: { content: "safe" } }, {
    set() { throw new Error("secret-sentinel") },
  })
  await assert.rejects(callback(assignmentFailure), /^Error: Tool output withheld because redaction failed$/)
  const resultGetter = { status: "completed", get result() { throw new Error("secret-sentinel") } }
  await assert.rejects(callback(resultGetter), /^Error: Tool output withheld because redaction failed$/)
  const errorGetter = { status: "error", get error() { throw new Error("secret-sentinel") } }
  await assert.rejects(callback(errorGetter), /^Error: Tool output withheld because redaction failed$/)
  const statusGetter = { get status() { throw new Error("secret-sentinel") } }
  await assert.rejects(callback(statusGetter), /^Error: Tool output withheld because redaction failed$/)
  await assert.rejects(callback({ status: "unknown", error: "secret-sentinel" }), /^Error: Tool output withheld because redaction failed$/)
  let factoryCallback
  await registerV2ToolOutputRedaction({ async hook(_name, handler) {
    factoryCallback = handler
    return { async dispose() {} }
  } }, redactor, () => { throw new Error("secret-sentinel") }, VERSION)
  await assert.rejects(factoryCallback({ status: "error", error: new Error("safe") }), /^Error: Tool output withheld because redaction failed$/)
  await assert.rejects(registerV2ToolOutputRedaction({}, redactor), /V2 Tool.Error factory required/)
  for (const version of [undefined, "1.18.18", "2.3.0", "2.2.5-preview"]) {
    await assert.rejects(registerV2ToolOutputRedaction({}, redactor, createToolError, version), /requires verified OpenCode 2.2.5/)
  }
})

test("V2 tool errors support isolated custom-pattern redaction", async () => {
  let callback
  const redactor = createSecretRedactor({
    patterns: ["secret-sentinel"], redactionToken: "[REDACTED]", isolateCustomPatterns: true,
    limits: { maxDepth: 32, maxNodes: 1000, maxChars: 10000 },
  })
  await registerV2ToolOutputRedaction({ async hook(_name, handler) {
    callback = handler
    return { async dispose() {} }
  } }, redactor, createToolError, VERSION)
  const event = { status: "error", error: new Error("safe secret-sentinel") }
  await callback(event)
  assert.equal(event.error.message, "safe [REDACTED]")
})
