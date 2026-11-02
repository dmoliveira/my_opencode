// Resolver-only test doubles; real guard, ledgers, continuity, sockets and dispatcher.
import assert from "node:assert/strict"
import test from "node:test"
import { registerHooks } from "node:module"
import { mkdtempSync, realpathSync, mkdirSync, writeFileSync, readFileSync, rmSync, lstatSync, existsSync } from "node:fs"
import { tmpdir } from "node:os"
import { join, dirname } from "node:path"

const fixtures = new Map()
globalThis.__rawDispatchResolver = fixtures
const loader = registerHooks({ load(url, context, next) {
  const result = next(url, context)
  if (url.endsWith("/dist/hooks/dependency-risk-guard/safety.js")) {
    let source = String(result.source)
    for (const name of ["capture", "captureMetadataContext", "captureAuditor"]) {
      source = source.replace(`export function ${name}(`, `function unused_${name}(`)
    }
    source += `\nexport const capture = root => globalThis.__rawDispatchResolver.get(root).snapshot;
export const captureMetadataContext = root => globalThis.__rawDispatchResolver.get(root).context;
export const captureAuditor = root => ({ fingerprint: "a".repeat(64) });\n`
    return { ...result, source }
  }
  return result
} })
const { default: GatewayCorePlugin } = await import("../dist/index.js")
const { dispatchToolAfterHooks } = await import("../dist/hooks/shared/tool-after-dispatch.js")
const { createDependencyRiskGuardHook } = await import("../dist/hooks/dependency-risk-guard/index.js")
const { RUNNER, digest, directoryIdentity, snapshotFingerprint, metadataFile, metadataFingerprint, METADATA_POLICY } = await import("../dist/hooks/dependency-risk-guard/safety.js")
const { metadataFrame, decodeMetadataInvocation } = await import("../dist/hooks/dependency-risk-guard/protocol.js")
loader.deregister()

function fixture() {
  const base = realpathSync(mkdtempSync(join(tmpdir(), "synthetic-raw-dispatch-")))
  const root = join(base, "source"), cache = join(base, "cache"), git = join(root, ".git")
  for (const path of [root, cache, git]) mkdirSync(path, { recursive: true })
  const inputs = { "pyproject.toml": "synthetic", "uv.lock": 'source = { editable = "." }\n', ".python-version": "3.12.16\n" }
  for (const [name, data] of Object.entries(inputs)) writeFileSync(join(root, name), data, { mode: 0o644 })
  const paths = Object.fromEntries(["node", "git", "uv", "python"].map(name => {
    const path = join(base, name); writeFileSync(path, "never execute", { mode: 0o700 }); return [name, path]
  }))
  const stat = lstatSync(git, { bigint: true })
  const snapshot = { v: 1, policy: "virtual-wheel-only-v3", root, ...paths, cache, version: "3.12.16",
    inputs: Object.fromEntries(Object.entries(inputs).map(([k, v]) => [k, digest(v)])),
    executables: Object.fromEntries(Object.entries(paths).map(([k, path]) => [k, { path, sha256: digest(readFileSync(path)) }])),
    helpers: ["index.js", "protocol.js", "capability.js", "runner.js", "safety.js"].map(name => {
      const path = join(dirname(RUNNER), name); return { path, sha256: digest(readFileSync(path)) }
    }), directories: { root: directoryIdentity(root), cache: directoryIdentity(cache), git: directoryIdentity(git) },
    marker: { path: git, dev: stat.dev.toString(), ino: stat.ino.toString(), kind: "directory", sha256: "" }, absent: ["uv.toml"] }
  snapshot.fingerprint = snapshotFingerprint(snapshot)
  const metadataSnapshot = { ...snapshot, policy: METADATA_POLICY }
  metadataSnapshot.fingerprint = snapshotFingerprint(metadataSnapshot)
  const context = { v: 1, policy: "one-key-metadata-promotion-v1", snapshot: metadataSnapshot,
    original: metadataFile(join(root, "uv.lock")), common: directoryIdentity(git), pointer: { kind: "absent" } }
  context.fingerprint = metadataFingerprint(context)
  fixtures.set(root, { snapshot, context })
  const guard = createDependencyRiskGuardHook({ directory: root, enabled: true, lockfilePatterns: [], commandPatterns: [] })
  return { root, guard, snapshot, context, async close() {
    await guard.event("session.deleted", {})
    fixtures.delete(root); rmSync(base, { recursive: true, force: true })
  } }
}
const requests = { audit: "dependency-security authorize-uv-sync-locked", metadata: "dependency-security check-uv-lock-virtual" }
const operations = { audit: "uv sync --locked", metadata: "dependency-security migrate-uv-lock-virtual" }
async function before(f, kind, session, call, command = requests[kind]) {
  const payload = { directory: f.root, input: { tool: "bash", sessionID: session, callID: call },
    output: { args: { command: `OPENCODE_SESSION_ID='${session}' ${command}` } } }
  await f.guard.event("tool.execute.before", payload)
  await f.guard.event("tool.execute.before.final", payload)
  return payload
}
function result(f, kind, q) {
  let frame
  if (kind === "metadata") {
    const invocation = decodeMetadataInvocation(/'([A-Za-z0-9_-]+)'$/.exec(q.output.args.command)[1])
    frame = metadataFrame({ ...invocation, candidate: "b".repeat(64) })
  } else {
    const nonce = /'audit' '[^']+' '([^']+)'/.exec(q.output.args.command)[1]
    frame = { v: 1, nonce, fingerprint: f.snapshot.fingerprint, packages: 1, closure: "a".repeat(64),
      auditor: "pip-audit==2.10.1", operation: "uv-sync-locked", build: "none", auditorRoot: f.root, auditorFingerprint: "a".repeat(64) }
  }
  return { directory: f.root, input: { ...q.input, args: q.output.args }, output: { output: JSON.stringify(frame) + "\n", metadata: { exit: 0 } } }
}

for (const guardPresent of [false, true]) for (const ledgerPresent of [false, true]) {
  test(`AFTER exact order and once, guard=${guardPresent} ledger=${ledgerPresent}`, async () => {
    const seen = [], hook = id => ({ id, priority: 1, async event(type) { seen.push([id, type]) } })
    const hooks = [hook("presentation-a"), ...(ledgerPresent ? [hook("validation-evidence-ledger")] : []),
      hook("presentation-b"), ...(guardPresent ? [hook("dependency-risk-guard")] : [])]
    await dispatchToolAfterHooks(hooks, { directory: tmpdir(), input: {}, output: {} })
    assert.deepEqual(seen.map(([id]) => id), [...(guardPresent ? ["dependency-risk-guard"] : []),
      ...(ledgerPresent ? ["validation-evidence-ledger"] : []), "presentation-a", "presentation-b"])
    assert.ok(seen.every(([, type]) => type === "tool.execute.after"))
  })
}

for (const kind of ["audit", "metadata"]) for (const failingId of ["secret-leak-guard", "presentation-failure", "validation-evidence-ledger", "blocked-presentation"]) {
  test(`${kind} authority revoked before continuation/error for ${failingId}; other session survives`, async () => {
    const f = fixture(), failure = new Error(failingId === "blocked-presentation" ? "[blocked] synthetic-later-failure" : "synthetic-later-failure"), seen = []
    try {
      const a = result(f, kind, await before(f, kind, "A", "check-a"))
      const b = result(f, kind, await before(f, kind, "B", "check-b"))
      await dispatchToolAfterHooks([f.guard], b)
      const original = f.guard.event.bind(f.guard)
      f.guard.event = async (type, payload) => { seen.push(type); await original(type, payload) }
      const probe = async () => {
        assert.ok(seen.includes("tool.execute.after.error"))
        await assert.rejects(before(f, kind, "A", "denied", operations[kind]))
      }
      const hooks = [f.guard, { id: failingId, priority: 1, async event(type, payload) {
        payload.input.sessionID = "B" // Cleanup must use the original native identity, not this mutation.
        throw failure
      } },
        { id: "next", priority: 2, async event() { await probe(); seen.push("next") } }]
      if (failingId === "secret-leak-guard" || failingId === "blocked-presentation") {
        await assert.rejects(dispatchToolAfterHooks(hooks, a), error => error === failure)
        await probe(); assert.ok(!seen.includes("next"))
      } else {
        await dispatchToolAfterHooks(hooks, a); assert.ok(seen.includes("next"))
      }
      assert.equal(seen.filter(type => type === "tool.execute.after").length, 1)
      const allowed = await before(f, kind, "B", "one-use", operations[kind])
      assert.match(allowed.output.args.command, kind === "audit" ? /'setup'/ : /'metadata'/)
      await assert.rejects(before(f, kind, "B", "replay", operations[kind]))
      assert.equal(existsSync(join(f.root, ".venv")), false)
    } finally { await f.close() }
  })
}

for (const kind of ["audit", "metadata"]) for (const critical of [false, true]) test(`${kind} cancellation closes pending capability and preserves session B; critical=${critical}`, async () => {
  const f = fixture()
  try {
    for (const session of ["A", "B"]) {
      await dispatchToolAfterHooks([f.guard], result(f, kind, await before(f, kind, session, "check")))
    }
    const a = await before(f, kind, "A", "pending", operations[kind])
    const b = await before(f, kind, "B", "pending", operations[kind])
    const socket = q => kind === "metadata"
      ? decodeMetadataInvocation(/'([A-Za-z0-9_-]+)'$/.exec(q.output.args.command)[1]).socket
      : /'setup' '[^']+' '[^']+' '[^']+' '([^']+)'/.exec(q.output.args.command)[1]
    assert.ok(existsSync(socket(a))); assert.ok(existsSync(socket(b)))
    // Non-bash AFTER leaves pending state untouched until the later failure cancels it.
    const dispatched = dispatchToolAfterHooks([f.guard, { id: critical ? "secret-leak-guard" : "tolerated", priority: 1, event() { throw new Error("later") } }],
      { directory: f.root, input: { tool: "read", sessionID: "A" }, output: {} })
    if (critical) await assert.rejects(dispatched, /later/)
    else await dispatched
    assert.equal(existsSync(socket(a)), false); assert.equal(existsSync(socket(b)), true)
    await f.guard.event("tool.execute.after.error", { input: {} })
    assert.equal(existsSync(socket(b)), true)
    await assert.rejects(before(f, kind, "A", "retry", operations[kind]))
  } finally { await f.close() }
})

test("cleanup failure never replaces original blocked error and is targeted, awaited", async () => {
  const original = new Error("[blocked] original"), seen = []
  const receiver = { id: "dependency-risk-guard", priority: 415, async event(type, payload) {
    seen.push(type)
    if (type === "tool.execute.after.error") {
      assert.equal(payload.input.sessionID, "actual-session")
      assert.equal(payload.output, undefined)
      await Promise.resolve(); seen.push("cleanup-awaited"); throw new Error("cleanup failure")
    }
  } }
  await assert.rejects(dispatchToolAfterHooks([receiver, { id: "later", priority: 1, event() { throw original } }],
    { directory: tmpdir(), input: { sessionID: "actual-session" }, output: {} }), error => error === original)
  assert.deepEqual(seen, ["tool.execute.after", "tool.execute.after.error", "cleanup-awaited"])
})

for (const kind of ["audit", "metadata"]) test(`full plugin ${kind}: triggered visible watchdog does not corrupt authority`, async () => {
  const f = fixture()
  const plugin = GatewayCorePlugin({ directory: f.root, config: { hooks: { enabled: true, disabled: [] },
    dependencyRiskGuard: { enabled: true }, longTurnWatchdog: { enabled: true, toolCallWarningThreshold: 1, reminderCooldownMs: 0 } } })
  const sessionID = `watchdog-${kind}`
  try {
    await plugin["chat.message"]({ sessionID, message: "Synthetic dispatch proof" })
    const input = { tool: "bash", sessionID, callID: "check" }, output = { args: { command: requests[kind] } }
    await plugin["tool.execute.before"](input, output)
    const r = result(f, kind, { input, output }), raw = r.output.output
    await plugin["tool.execute.after"](r.input, r.output)
    assert.ok(r.output.output.startsWith(raw)); assert.match(r.output.output, /\[Turn Watchdog\]: Long turn/)
    const operation = { args: { command: operations[kind] } }
    await plugin["tool.execute.before"]({ ...input, callID: "one-use" }, operation)
    assert.match(operation.args.command, kind === "audit" ? /'setup'/ : /'metadata'/)
    await assert.rejects(plugin["tool.execute.before"]({ ...input, callID: "replay" }, { args: { command: operations[kind] } }))
    assert.equal(existsSync(join(f.root, ".venv")), false)
  } finally {
    await plugin.event({ event: { type: "session.deleted", properties: { info: { id: sessionID } } } })
    await f.close()
  }
})

for (const kind of ["audit", "metadata"]) for (const mutation of ["footer", "chatter", "duplicate", "trailing", "malformed", "fabricated"]) {
  test(`${kind} strict native output rejects ${mutation} before presentation`, async () => {
    const f = fixture()
    try {
      const r = result(f, kind, await before(f, kind, "A", "check")), valid = r.output.output
      r.output.output = mutation === "footer" ? valid + "[Turn Watchdog]: Long turn\n" : mutation === "chatter" ? "producer chatter\n" + valid
        : mutation === "duplicate" ? valid.replace('"v":1', '"v":1,"v":1') : mutation === "trailing" ? valid + "\n"
          : mutation === "fabricated" ? "PASS\n" : "{malformed"
      await dispatchToolAfterHooks([{ id: "presentation", priority: 1, event() { r.output.output = valid } }, f.guard], r)
      await assert.rejects(before(f, kind, "A", "denied", operations[kind]))
    } finally { await f.close() }
  })
}
