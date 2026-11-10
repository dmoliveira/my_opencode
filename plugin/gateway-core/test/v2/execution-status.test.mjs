import assert from "node:assert/strict"
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import { loadGatewayState } from "../../dist/state/storage.js"
import { registerV2ExecutionStatus } from "../../dist/v2/execution-status.js"

const options = { enabled: true, maxSessions: 8, maxLabelChars: 80 }

function stream() {
  const queue = []
  let waiting
  let closed = false
  return {
    subscribe({ signal }) {
      signal.addEventListener("abort", () => {
        closed = true
        if (waiting) { waiting({ done: true }); waiting = undefined }
      }, { once: true })
      return { [Symbol.asyncIterator]() { return {
        next() {
          if (queue.length) return Promise.resolve({ value: queue.shift(), done: false })
          if (closed) return Promise.resolve({ done: true })
          return new Promise((resolve) => { waiting = resolve })
        },
      } } }
    },
    emit(value) {
      if (closed) return
      if (waiting) { waiting({ value, done: false }); waiting = undefined }
      else queue.push(value)
    },
    get closed() { return closed },
  }
}

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "v2-execution-status-"))
  const directory = join(root, "project")
  const other = join(root, "other")
  mkdirSync(directory)
  mkdirSync(other)
  const sessions = new Map()
  const hooks = new Map()
  const disposed = []
  const events = stream()
  const context = {
    app: { version: "2.2.6" },
    location: { directory },
    session: { async get({ sessionID }) {
      if (!sessions.has(sessionID)) throw new Error("missing session")
      return { location: { directory: sessions.get(sessionID) } }
    } },
    tool: { async hook(name, callback) {
      hooks.set(name, callback)
      return { async dispose() { disposed.push(name) } }
    } },
    event: events,
  }
  return { root, directory, other, sessions, hooks, disposed, events, context,
    state: (id) => loadGatewayState(directory)?.executionStatus?.sessions[id],
    close: () => rmSync(root, { recursive: true, force: true }),
  }
}

async function until(predicate) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (predicate()) return
    await new Promise((resolve) => setTimeout(resolve, 10))
  }
  throw new Error("status event did not settle")
}

test("V2 tool events produce bounded milestones without recording command output", async () => {
  const f = fixture()
  try {
    f.sessions.set("ses-one", f.directory)
    const dispose = await registerV2ExecutionStatus(f.context, options)
    const event = { tool: "shell", sessionID: "ses-one", input: { command: "make validate SYNTHETIC_SECRET", secret: "SYNTHETIC_SECRET" } }
    await f.hooks.get("execute.before")(event)
    assert.equal(f.state("ses-one").next, "Run validation")
    await f.hooks.get("execute.after")({ ...event, status: "completed", result: { metadata: { exit: 0, secret: "SYNTHETIC_SECRET" } } })
    assert.equal(f.state("ses-one").last, "Validation passed")
    assert.equal(f.state("ses-one").next, "Review changes")
    assert.doesNotMatch(readFileSync(join(f.directory, ".opencode", "gateway-core.state.json"), "utf8"), /SYNTHETIC_SECRET/)
    await f.hooks.get("execute.after")({ ...event, status: "completed", result: { metadata: { exit: 1 } } })
    assert.equal(f.state("ses-one").last, "Validation failed")
    await f.hooks.get("execute.after")({ ...event, status: "completed", result: {} })
    assert.equal(f.state("ses-one").last, "Validation completed")
    await f.hooks.get("execute.after")({ ...event, status: "error" })
    assert.equal(f.state("ses-one").next, "Fix validation")
    await dispose()
    assert.deepEqual(f.disposed.sort(), ["execute.after", "execute.before"])
    assert.equal(f.events.closed, true)
  } finally { f.close() }
})

test("V2 status stays in its own location and removes known moved or deleted sessions", async () => {
  const f = fixture()
  try {
    f.sessions.set("ses-one", f.directory)
    f.sessions.set("ses-other", f.other)
    const dispose = await registerV2ExecutionStatus(f.context, options)
    f.events.emit({ type: "session.created", data: { sessionID: "ses-one" } })
    await until(() => f.state("ses-one")?.last === "Session ready")
    await f.hooks.get("execute.before")({ tool: "write", sessionID: "ses-other", input: {} })
    assert.equal(existsSync(join(f.other, ".opencode")), false)
    assert.equal(f.state("ses-other"), undefined)
    f.sessions.set("ses-one", f.other)
    f.events.emit({ type: "session.moved", data: { sessionID: "ses-one" } })
    await until(() => f.state("ses-one") === undefined)
    f.sessions.set("ses-one", f.directory)
    f.events.emit({ type: "session.created", data: { sessionID: "ses-one" } })
    await until(() => !!f.state("ses-one"))
    f.events.emit({ type: "session.deleted", data: { sessionID: "ses-one" } })
    await until(() => f.state("ses-one") === undefined)
    assert.equal(existsSync(join(f.other, ".opencode")), false)
    await dispose()
  } finally { f.close() }
})

test("V2 status does not write after disposal or for malformed events", async () => {
  const f = fixture()
  try {
    let finishLookup
    f.context.session.get = () => new Promise((resolve) => { finishLookup = resolve })
    const dispose = await registerV2ExecutionStatus(f.context, options)
    const pending = f.hooks.get("execute.before")({ tool: "write", sessionID: "ses-one", input: {} })
    await until(() => !!finishLookup)
    await dispose()
    finishLookup({ location: { directory: f.directory } })
    await pending
    await f.hooks.get("execute.before")({ tool: "write", sessionID: "ses-two", input: {} })
    f.events.emit({ type: "session.created", data: { sessionID: "ses-two" } })
    assert.equal(existsSync(join(f.directory, ".opencode")), false)
  } finally { f.close() }
})

test("V2 status orders concurrent events and survives a malformed session event", async () => {
  const f = fixture()
  try {
    let finishLookup
    f.context.session.get = () => new Promise((resolve) => { finishLookup = resolve })
    const dispose = await registerV2ExecutionStatus(f.context, options)
    f.events.emit(new Proxy({}, { get() { throw new Error("private detail") } }))
    const event = { tool: "shell", sessionID: "ses-one", input: { command: "make validate" } }
    const before = f.hooks.get("execute.before")(event)
    const after = f.hooks.get("execute.after")({ ...event, status: "completed", result: { metadata: { exit: 0 } } })
    await until(() => !!finishLookup)
    f.context.session.get = async () => ({ location: { directory: f.directory } })
    finishLookup({ location: { directory: f.directory } })
    await Promise.all([before, after])
    assert.equal(f.state("ses-one").last, "Validation passed")
    f.sessions.set("ses-two", f.directory)
    f.events.emit({ type: "session.created", data: { sessionID: "ses-two" } })
    await until(() => f.state("ses-two")?.last === "Session ready")
    await dispose()
  } finally { f.close() }
})

test("V2 status cleans up partial registration and validates configuration", async () => {
  const f = fixture()
  try {
    let disposed = false
    f.context.tool.hook = async (name) => {
      if (name === "execute.after") throw new Error("synthetic private detail")
      return { async dispose() { disposed = true } }
    }
    await assert.rejects(registerV2ExecutionStatus(f.context, options), /^Error: Unable to register V2 execution status$/)
    assert.equal(disposed, true)
    await assert.rejects(registerV2ExecutionStatus(f.context, { ...options, maxSessions: 0 }), /Invalid V2 execution-status configuration/)
    f.context.app.version = "2.3.0"
    await assert.rejects(registerV2ExecutionStatus(f.context, options), /Invalid V2 execution-status configuration/)
    const disabled = await registerV2ExecutionStatus(f.context, { ...options, enabled: false })
    await disabled()
  } finally { f.close() }
})

test("V2 status bounds a stalled session lookup and ignores malformed tool events", async () => {
  const f = fixture()
  try {
    f.context.session.get = () => new Promise(() => {})
    const dispose = await registerV2ExecutionStatus(f.context, options)
    const start = Date.now()
    await f.hooks.get("execute.before")({ tool: "write", sessionID: "ses-stalled", input: {} })
    assert.ok(Date.now() - start < 4000)
    await f.hooks.get("execute.before")(new Proxy({}, { get() { throw new Error("private detail") } }))
    await f.hooks.get("execute.before")({ tool: "constructor", sessionID: "ses-unknown", input: {} })
    assert.equal(existsSync(join(f.directory, ".opencode")), false)
    await dispose()
  } finally { f.close() }
})
