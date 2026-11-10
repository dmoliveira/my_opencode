import assert from "node:assert/strict"
import test from "node:test"

import { registerV2InterruptingToolOutputRedaction } from "../../dist/v2/tool-output-redaction.js"

function deferred() {
  let resolve
  let reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

function fixture() {
  const hooks = new Map()
  const disposed = []
  const waits = []
  const interrupts = []
  const session = {
    async hook(name, callback) {
      hooks.set(name, callback)
      return { async dispose() { disposed.push(name) } }
    },
    async interrupt(input) { interrupts.push(input); return { interrupted: true } },
    wait(input) { const pending = deferred(); waits.push({ ...pending, input }); return pending.promise },
  }
  const tool = { async hook(name, callback) {
    hooks.set(name, callback)
    return { async dispose() { disposed.push(name) } }
  } }
  const redactor = { async redactMutableValueAsync(value) {
    if (typeof value.message === "string") value.message = value.message.replaceAll("secret-sentinel", "[REDACTED]")
    if (typeof value.result?.content === "string") value.result.content = value.result.content.replaceAll("secret-sentinel", "[REDACTED]")
  } }
  const createError = (message) => new Error(message)
  return { hooks, disposed, waits, interrupts, session, tool, redactor, createError,
    register: () => registerV2InterruptingToolOutputRedaction(session, tool, redactor, createError, "2.2.6"),
  }
}

function rejected(sessionID, tag = "Permission.DeclinedError") {
  const untrusted = Object.create({ toString() { return "secret-sentinel" } })
  Object.defineProperty(untrusted, "_tag", { value: tag, enumerable: true })
  Object.defineProperty(untrusted, "private", { value: "secret-sentinel" })
  return { sessionID, status: "error", error: Object.assign(new Error("secret-sentinel"), { error: untrusted }) }
}

async function tick() { await new Promise((resolve) => setImmediate(resolve)) }

test("plain V2 rejection is sanitized and quarantined until the interrupted session settles", async () => {
  const f = fixture()
  const dispose = await f.register()
  const event = rejected("ses-one")
  await f.hooks.get("execute.after")(event)
  assert.equal(event.error.message, "Tool step stopped")
  assert.equal(event.error.error, undefined)
  assert.deepEqual(f.interrupts, [{ sessionID: "ses-one", resume: false }])
  await tick()
  for (const name of ["context", "compaction", "generate", "title", "http.request", "experimental.ws.send"]) {
    await assert.rejects(f.hooks.get(name)({ sessionID: "ses-one" }), /interruption is unresolved/)
    await f.hooks.get(name)({ sessionID: "ses-other" })
  }
  assert.equal(f.waits.length, 1)
  f.waits[0].resolve()
  await tick()
  await f.hooks.get("context")({ sessionID: "ses-one" })
  await dispose()
  assert.equal(f.disposed.length, 7)
})

test("ordinary tool output and feedback are redacted without interrupting", async () => {
  const f = fixture()
  await f.register()
  const completed = { sessionID: "ses-one", status: "completed", result: { content: "secret-sentinel" } }
  await f.hooks.get("execute.after")(completed)
  assert.equal(completed.result.content, "[REDACTED]")
  const feedback = rejected("ses-one", "Permission.CorrectedError")
  await f.hooks.get("execute.after")(feedback)
  assert.equal(feedback.error.message, "[REDACTED]")
  assert.equal(feedback.error.error, undefined)
  assert.equal(f.interrupts.length, 0)
})

test("failed interruption keeps only that session quarantined and does not expose the failure", async () => {
  const f = fixture()
  f.session.interrupt = async () => { throw new Error("secret-sentinel") }
  await f.register()
  const event = rejected("ses-one")
  await assert.rejects(f.hooks.get("execute.after")(event), /^Error: Tool step withheld because session interruption is unresolved$/)
  assert.equal(event.error.message, "Tool step stopped")
  await assert.rejects(f.hooks.get("context")({ sessionID: "ses-one" }), /interruption is unresolved/)
  await f.hooks.get("context")({ sessionID: "ses-other" })
  assert.equal(f.waits.length, 0)
})

test("a refused interruption or failed settlement leaves the affected session blocked", async () => {
  const f = fixture()
  f.session.interrupt = async () => ({ interrupted: false })
  await f.register()
  await assert.rejects(f.hooks.get("execute.after")(rejected("ses-refused")), /interruption is unresolved/)
  await assert.rejects(f.hooks.get("context")({ sessionID: "ses-refused" }), /interruption is unresolved/)
  await f.hooks.get("context")({ sessionID: "ses-other" })

  const g = fixture()
  g.session.wait = async () => { throw new Error("secret-sentinel") }
  await g.register()
  await g.hooks.get("execute.after")(rejected("ses-wait-failed"))
  await tick()
  await assert.rejects(g.hooks.get("context")({ sessionID: "ses-wait-failed" }), /interruption is unresolved/)
  await g.hooks.get("context")({ sessionID: "ses-other" })
})

test("an unresponsive interruption times out without releasing the quarantine when it later returns", { timeout: 15000 }, async () => {
  const f = fixture()
  const pending = deferred()
  f.session.interrupt = () => pending.promise
  await f.register()
  const started = Date.now()
  await assert.rejects(f.hooks.get("execute.after")(rejected("ses-hung")), /interruption is unresolved/)
  assert.ok(Date.now() - started < 10000)
  pending.resolve({ interrupted: true })
  await tick()
  await assert.rejects(f.hooks.get("context")({ sessionID: "ses-hung" }), /interruption is unresolved/)
  await f.hooks.get("context")({ sessionID: "ses-other" })
})

test("a second interruption cannot release an earlier session quarantine", async () => {
  const f = fixture()
  const first = deferred()
  const second = deferred()
  let calls = 0
  f.session.interrupt = () => (++calls === 1 ? first.promise : second.promise)
  await f.register()
  const a = f.hooks.get("execute.after")(rejected("ses-one"))
  const b = f.hooks.get("execute.after")(rejected("ses-one"))
  first.resolve({ interrupted: true })
  await a
  await tick()
  f.waits[0].resolve()
  await tick()
  await assert.rejects(f.hooks.get("context")({ sessionID: "ses-one" }), /interruption is unresolved/)
  second.resolve({ interrupted: true })
  await b
  await tick()
  assert.equal(f.waits.length, 2)
  f.waits[1].resolve()
  await tick()
  await f.hooks.get("context")({ sessionID: "ses-one" })
})

test("opaque cancellation, missing identity, and partial registration fail safely", async () => {
  const f = fixture()
  await f.register()
  const opaque = { sessionID: "ses-one", status: "error", error: new Proxy({}, { getOwnPropertyDescriptor() { throw new Error("secret-sentinel") } }) }
  await f.hooks.get("execute.after")(opaque)
  assert.deepEqual(f.interrupts, [{ sessionID: "ses-one", resume: false }])
  await assert.rejects(f.hooks.get("execute.after")(rejected("")), /interruption is unresolved/)
  await assert.rejects(f.hooks.get("context")({ sessionID: "ses-other" }), /interruption is unresolved/)

  const g = fixture()
  g.session.hook = async (name, callback) => {
    if (name === "generate") throw new Error("secret-sentinel")
    g.hooks.set(name, callback)
    return { async dispose() { g.disposed.push(name) } }
  }
  await assert.rejects(g.register(), /^Error: Unable to register V2 tool-output redaction$/)
  assert.deepEqual(g.disposed.sort(), ["compaction", "context"])
})

test("a failing error factory still requests interruption and keeps the session blocked", async () => {
  const f = fixture()
  await registerV2InterruptingToolOutputRedaction(f.session, f.tool, f.redactor, () => { throw new Error("secret-sentinel") }, "2.2.6")
  await assert.rejects(f.hooks.get("execute.after")(rejected("ses-one")), /^Error: Tool step withheld because session interruption is unresolved$/)
  assert.deepEqual(f.interrupts, [{ sessionID: "ses-one", resume: false }])
  await assert.rejects(f.hooks.get("context")({ sessionID: "ses-one" }), /interruption is unresolved/)
  await f.hooks.get("context")({ sessionID: "ses-other" })
})

test("exhausting the quarantine limit closes the remaining sessions", async () => {
  const f = fixture()
  f.session.interrupt = async () => ({ interrupted: false })
  await f.register()
  for (let index = 0; index < 65; index += 1) {
    await assert.rejects(f.hooks.get("execute.after")(rejected(`ses-${index}`)), /interruption is unresolved/)
  }
  await assert.rejects(f.hooks.get("context")({ sessionID: "ses-other" }), /interruption is unresolved/)
})

test("a dismissed V2 question also stops the affected session", async () => {
  const f = fixture()
  await f.register()
  await f.hooks.get("execute.after")(rejected("ses-question", "QuestionTool.CancelledError"))
  assert.deepEqual(f.interrupts, [{ sessionID: "ses-question", resume: false }])
})
