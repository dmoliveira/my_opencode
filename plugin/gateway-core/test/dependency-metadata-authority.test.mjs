// Synthetic filesystem and SDK boundaries only; no resolver/network/installer.
import assert from "node:assert/strict"
import test from "node:test"
import { mkdtempSync, realpathSync, mkdirSync, writeFileSync, rmSync, lstatSync, renameSync, copyFileSync, chmodSync, linkSync, symlinkSync, readFileSync, existsSync } from "node:fs"
import { tmpdir } from "node:os"
import { join, dirname } from "node:path"
import { RUNNER, METADATA_POLICY, digest, safeRead, directoryIdentity, snapshotFingerprint, metadataFile,
  metadataFingerprint, encodeMetadataContext, decodeMetadataContext, recaptureMetadataContext, verifyMetadataTransition,
  metadataCandidate, metadataPaths, prepareMetadata, inspectMetadataPreparation, verifyMetadataPreparation, closeMetadataPreparation } from "../dist/hooks/dependency-risk-guard/safety.js"
import { MetadataLedger, metadataFrame, parseMetadataFrame, parseFrame, encodeMetadataInvocation, decodeMetadataInvocation, PENDING_MS, PERMIT_MS, MAX_STATE } from "../dist/hooks/dependency-risk-guard/protocol.js"
import { executeMetadata } from "../dist/hooks/dependency-risk-guard/runner.js"
import { metadataCapability, metadataCapabilityBinding, capability } from "../dist/hooks/dependency-risk-guard/capability.js"
import { connect } from "node:net"

function fixture(linked = false, pointerValue = "../common\n") {
  const base = realpathSync(mkdtempSync(join(tmpdir(), "synthetic-metadata-authority-")))
  const root = join(base, "source"), cache = join(base, "cache"), git = linked ? join(base, "git-dir") : join(root, ".git")
  const common = linked ? join(base, "common") : git
  for (const path of new Set([root, cache, git, common])) mkdirSync(path, { recursive: true })
  if (linked) { writeFileSync(join(root, ".git"), `gitdir: ${git}\n`); writeFileSync(join(git, "commondir"), pointerValue) }
  const inputs = { "pyproject.toml": "synthetic", "uv.lock": 'source = { editable = "." }\n', ".python-version": "3.12.16\n" }
  for (const [name, data] of Object.entries(inputs)) writeFileSync(join(root, name), data, { mode: 0o644 })
  const paths = Object.fromEntries(["node", "git", "uv", "python"].map((name) => {
    const path = join(base, name); writeFileSync(path, "must never execute", { mode: 0o700 }); return [name, path]
  }))
  const st = lstatSync(join(root, ".git"), { bigint: true })
  const s = { v: 1, policy: METADATA_POLICY, root, ...paths, cache, version: "3.12.16",
    inputs: Object.fromEntries(Object.entries(inputs).map(([k, v]) => [k, digest(v)])),
    executables: Object.fromEntries(Object.entries(paths).map(([k, path]) => [k, { path, sha256: digest(safeRead(path)) }])),
    helpers: ["index.js", "protocol.js", "capability.js", "runner.js", "safety.js"].map((name) => {
      const path = join(dirname(RUNNER), name); return { path, sha256: digest(safeRead(path)) }
    }), directories: { root: directoryIdentity(root), cache: directoryIdentity(cache), git: directoryIdentity(git) },
    marker: { path: join(root, ".git"), dev: st.dev.toString(), ino: st.ino.toString(), kind: linked ? "file" : "directory", sha256: linked ? digest(safeRead(join(root, ".git"))) : "" }, absent: ["uv.toml"] }
  s.fingerprint = snapshotFingerprint(s)
  const c = { v: 1, policy: "one-key-metadata-promotion-v1", snapshot: s, original: metadataFile(join(root, "uv.lock")), common: directoryIdentity(common),
    pointer: linked ? { kind: "file", file: metadataFile(join(git, "commondir")), target: common } : { kind: "absent" } }
  c.fingerprint = metadataFingerprint(c)
  return { base, root, git, common, c, close: () => rmSync(base, { recursive: true, force: true }) }
}

for (const linked of [false, true]) test(`strict metadata context roundtrip and pure continuity linked=${linked}`, () => {
  const f = fixture(linked)
  try { assert.deepEqual(decodeMetadataContext(encodeMetadataContext(f.c)), f.c); recaptureMetadataContext(f.c) } finally { f.close() }
})
for (const mode of [0o444, 0o744, 0o664, 0o646, 0o4644, 0o2644, 0o1644]) test(`unsupported original mode ${mode.toString(8)} is rejected without repair`, () => {
  const f = fixture()
  try {
    chmodSync(f.c.original.path, mode)
    assert.throws(() => metadataFile(f.c.original.path))
    assert.equal(lstatSync(f.c.original.path).mode & 0o7777, mode)
  } finally { f.close() }
})
test("context rejects unknown fields, duplicate/noncanonical/oversized/wrong-policy payloads", () => {
  const f = fixture()
  try {
    const text = Buffer.from(encodeMetadataContext(f.c), "base64url").toString()
    for (const raw of [text.replace('"v":1', '"v":2,"v":1'), text + " ", "x".repeat(32769), JSON.stringify(f.c)]) {
      assert.throws(() => decodeMetadataContext(Buffer.from(raw).toString("base64url")))
    }
    for (const change of [(c) => { c.extra = 1 }, (c) => { c.snapshot.policy = "virtual-wheel-only-v3"; c.snapshot.fingerprint = snapshotFingerprint(c.snapshot) }, (c) => { c.original.size++ }]) {
      const c = structuredClone(f.c); change(c); assert.throws(() => encodeMetadataContext(c))
    }
  } finally { f.close() }
})
for (const mutation of ["pointer-added", "source-inode", "source-mode", "source-link", "source-owner-proof", "common-inode", "tool", "manifest"]) test(`pure context rejects ${mutation}`, () => {
  const f = fixture()
  try {
    const source = f.c.original.path
    if (mutation === "pointer-added") writeFileSync(join(f.git, "commondir"), ".\n")
    if (mutation === "source-inode") { renameSync(source, source + ".old"); copyFileSync(source + ".old", source) }
    if (mutation === "source-mode") chmodSync(source, 0o600)
    if (mutation === "source-link") linkSync(source, source + ".link")
    if (mutation === "source-owner-proof") { f.c.original.uid = "999999"; f.c.fingerprint = metadataFingerprint(f.c) }
    if (mutation === "common-inode") { renameSync(f.common, f.common + ".old"); mkdirSync(f.common) }
    if (mutation === "tool") writeFileSync(f.c.snapshot.uv, "changed")
    if (mutation === "manifest") writeFileSync(join(f.root, "pyproject.toml"), "changed")
    assert.throws(() => recaptureMetadataContext(f.c))
  } finally { f.close() }
})
for (const mutation of ["contents", "inode", "link", "symlink", "double-lf", "carriage-return", "space"]) test(`linked pointer rejects ${mutation}`, () => {
  const f = fixture(true), path = join(f.git, "commondir")
  try {
    if (["inode", "symlink"].includes(mutation)) { renameSync(path, path + ".old"); if (mutation === "inode") copyFileSync(path + ".old", path); else symlinkSync(path + ".old", path) }
    else if (mutation === "link") linkSync(path, path + ".link")
    else writeFileSync(path, mutation === "double-lf" ? "../common\n\n" : mutation === "carriage-return" ? "../common\r\n" : mutation === "space" ? "../common \n" : ".\n")
    assert.throws(() => recaptureMetadataContext(f.c))
  } finally { f.close() }
})
test("pointer trailing space is a Git path byte, not trimmed", () => {
  const f = fixture(true, "../common \n")
  try {
    renameSync(f.common, f.common + " "); f.c.common = directoryIdentity(f.common + " "); f.c.pointer.target = f.common + " "; f.c.fingerprint = metadataFingerprint(f.c)
    recaptureMetadataContext(f.c)
  } finally { f.close() }
})
for (const mutation of ["none", "identical-replacement", "mode", "owner-proof", "link", "size", "manifest"]) test(`post-state requires exact prepared identity: ${mutation}`, () => {
  const f = fixture()
  try {
    const path = join(f.root, ".synthetic-candidate"), data = Buffer.from('source = { virtual = "." }\n')
    writeFileSync(path, data, { mode: f.c.original.mode, flag: "wx" })
    const prepared = metadataFile(path); renameSync(path, f.c.original.path)
    if (mutation === "identical-replacement") { renameSync(f.c.original.path, path); copyFileSync(path, f.c.original.path) }
    if (mutation === "mode") chmodSync(f.c.original.path, 0o600)
    if (mutation === "owner-proof") prepared.uid = "999999"
    if (mutation === "link") linkSync(f.c.original.path, path)
    if (mutation === "size") writeFileSync(f.c.original.path, Buffer.concat([data, Buffer.from(" ")]))
    if (mutation === "manifest") writeFileSync(join(f.root, "pyproject.toml"), "changed")
    if (mutation === "none") verifyMetadataTransition(f.c, prepared, digest(data))
    else assert.throws(() => verifyMetadataTransition(f.c, prepared, digest(data)))
  } finally { f.close() }
})

const sha = "a".repeat(64), next = "b".repeat(64)
const scope = { session: "synthetic-session", call: "check-call", root: "/synthetic", fingerprint: sha }
const frame = (p) => JSON.stringify(metadataFrame({ ...p, candidate: p.candidate || next })) + "\n"
function permitted(now) {
  const ledger = new MetadataLedger(now), pending = ledger.begin(scope, sha, (n) => `trusted ${n}`)
  assert.ok(ledger.finish(scope, pending.command, 0, frame(pending)))
  return { ledger, pending }
}
test("metadata check grants only one migrate with issuer/new-call binding and consume before replay", () => {
  const { ledger } = permitted()
  const p = ledger.consume({ ...scope, call: "migrate-call" }); p.command = "trusted migrate"
  assert.equal(p.issuer, scope.call); assert.equal(p.candidate, next)
  assert.ok(ledger.finish({ ...scope, call: p.call }, p.command, 0, frame(p)))
  assert.throws(() => ledger.consume({ ...scope, call: "retry" }))
  assert.throws(() => parseFrame(frame(p), p))
})
for (const field of ["session", "call", "root", "fingerprint"]) test(`metadata native ${field} mismatch cannot grant authority`, () => {
  const ledger = new MetadataLedger(), p = ledger.begin(scope, sha, () => "trusted")
  assert.equal(ledger.finish({ ...scope, [field]: "wrong" }, p.command, 0, frame(p)), undefined)
  assert.throws(() => ledger.consume({ ...scope, call: "migrate" }))
})
for (const field of ["phase", "session", "call", "issuer", "root", "fingerprint", "nonce", "original", "candidate", "v"]) test(`strict phase frame rejects wrong ${field}`, () => {
  const ledger = new MetadataLedger(), p = ledger.begin(scope, sha, () => "trusted")
  const f = JSON.parse(frame(p)); f[field] = field === "v" ? 2 : "wrong"
  assert.throws(() => parseMetadataFrame(JSON.stringify(f) + "\n", p))
  assert.equal(ledger.finish(scope, p.command, 0, JSON.stringify(f) + "\n"), undefined)
  assert.throws(() => ledger.consume({ ...scope, call: "migrate" }))
})
for (const output of [(p) => frame(p).replace('"v":1', '"v":2,"v":1'), (p) => frame(p) + "\n", () => "PASS\n", () => "x".repeat(8193),
  (p) => JSON.stringify({ ...JSON.parse(frame(p)), extra: 1 }) + "\n", (p) => frame(p).slice(0, -5)]) test("malformed metadata frame clears pending", () => {
  const ledger = new MetadataLedger(), p = ledger.begin(scope, sha, () => "trusted")
  assert.equal(ledger.finish(scope, p.command, 0, output(p)), undefined)
  assert.equal(ledger.finish(scope, p.command, 0, frame(p)), undefined)
})
for (const exit of [undefined, "0", false, null, 1, NaN, Infinity]) test(`metadata exit ${String(exit)} is not success`, () => {
  const ledger = new MetadataLedger(), p = ledger.begin(scope, sha, () => "trusted")
  assert.equal(ledger.finish(scope, p.command, exit, frame(p)), undefined)
})
test("metadata expiry, cancellation, concurrency, replay and bounded state fail closed", () => {
  let now = 100
  const ledger = new MetadataLedger(() => now), p = ledger.begin(scope, sha, () => "trusted")
  now += PENDING_MS; assert.equal(ledger.finish(scope, p.command, 0, frame(p)), undefined)
  const expired = permitted(() => now).ledger; now += PERMIT_MS
  assert.throws(() => expired.consume({ ...scope, call: "migrate" }))
  const second = permitted().ledger; second.clear(scope.session); assert.throws(() => second.consume({ ...scope, call: "migrate" }))
  const conflict = new MetadataLedger(); conflict.begin(scope, sha, () => "trusted")
  assert.throws(() => conflict.begin({ ...scope, call: "other" }, sha, () => "trusted"))
  assert.throws(() => conflict.consume({ ...scope, call: "migrate" }))
  assert.throws(() => conflict.begin(scope, sha, () => "trusted"))
  const full = new MetadataLedger()
  for (let i = 0; i < MAX_STATE; i++) full.begin({ ...scope, session: `s-${i}` }, sha, () => "trusted")
  assert.throws(() => full.begin({ ...scope, session: "overflow" }, sha, () => "trusted"))
})
test("migrate expiry, wrong command, cross-phase replay and conflicting consume revoke authority", () => {
  for (const kind of ["expiry", "command", "check-replay", "conflict"]) {
    let now = 100
    const { ledger, pending: check } = permitted(() => now)
    const p = ledger.consume({ ...scope, call: "migrate-call" }); p.command = "trusted migrate"
    if (kind === "expiry") now += PENDING_MS
    if (kind === "conflict") assert.throws(() => ledger.consume({ ...scope, call: "concurrent" }))
    assert.equal(ledger.finish({ ...scope, call: p.call }, kind === "command" ? "changed" : p.command, 0,
      kind === "check-replay" ? frame(check) : frame(p)), undefined)
    assert.throws(() => ledger.consume({ ...scope, call: "retry" }))
  }
})

function invocation(f, phase = "migrate") {
  return { v: 1, phase, session: "synthetic-session", call: phase + "-call", issuer: phase === "check" ? "" : "check-call", root: f.root,
    fingerprint: f.c.fingerprint, nonce: "c".repeat(64), original: f.c.original.sha256,
    candidate: phase === "check" ? "" : digest(metadataCandidate(safeRead(f.c.original.path)).candidate),
    context: encodeMetadataContext(f.c), socket: phase === "check" ? "" : "/synthetic/unused.sock", capability: phase === "check" ? "" : sha }
}
test("metadata invocation is bounded, canonical, phase-specific and rejects policy replay", () => {
  const f = fixture()
  try {
    const i = invocation(f); assert.deepEqual(decodeMetadataInvocation(encodeMetadataInvocation(i)), i)
    for (const mutate of [(x) => { x.extra = true }, (x) => { x.phase = "setup" }, (x) => { x.issuer = x.call }, (x) => { x.candidate = x.original }, (x) => { x.phase = "check" }]) {
      const x = structuredClone(i); mutate(x); assert.throws(() => encodeMetadataInvocation(x))
    }
    const raw = Buffer.from(encodeMetadataInvocation(i), "base64url").toString()
    assert.throws(() => decodeMetadataInvocation(Buffer.from(raw.replace('"v":1', '"v":1,"v":1')).toString("base64url")))
  } finally { f.close() }
})
for (const attack of ["job-collision", "namespace-mode", "namespace-link", "candidate-collision", "candidate-link", "backup-link"]) test(`exclusive preparation rejects ${attack}`, () => {
  const f = fixture(), i = invocation(f), paths = metadataPaths(f.c, i.nonce)
  try {
    if (attack === "namespace-link") symlinkSync(f.common, paths.namespace)
    if (["job-collision", "namespace-mode", "backup-link"].includes(attack)) mkdirSync(paths.namespace, { mode: attack === "namespace-mode" ? 0o755 : 0o700 })
    if (["job-collision", "backup-link"].includes(attack)) mkdirSync(paths.job, { mode: 0o700 })
    if (attack === "backup-link") symlinkSync(f.c.original.path, paths.backup)
    if (attack === "candidate-collision") writeFileSync(paths.candidate, "unrelated")
    if (attack === "candidate-link") symlinkSync(f.c.original.path, paths.candidate)
    assert.throws(() => prepareMetadata(f.c, i.nonce, i.candidate))
    assert.equal(metadataFile(f.c.original.path).sha256, i.original)
    if (attack === "candidate-collision") assert.equal(readFileSync(paths.candidate, "utf8"), "unrelated")
  } finally { f.close() }
})
for (const attack of ["candidate-inode", "candidate-mode", "candidate-link", "backup-inode", "backup-bytes", "job-inode", "source", "tool", "pointer"]) test(`preparation continuity rejects ${attack} and retains original backup`, () => {
  const f = fixture(), i = invocation(f), p = prepareMetadata(f.c, i.nonce, i.candidate)
  try {
    const path = attack.startsWith("backup") ? p.backup.path : p.candidate.path
    if (attack.endsWith("inode") && attack !== "job-inode") { renameSync(path, path + ".old"); copyFileSync(path + ".old", path) }
    if (attack === "candidate-mode") chmodSync(path, 0o600)
    if (attack === "candidate-link") linkSync(path, path + ".link")
    if (attack === "backup-bytes") writeFileSync(path, "changed")
    if (attack === "job-inode") { renameSync(p.job.path, p.job.path + ".old"); mkdirSync(p.job.path, { mode: 0o700 }); copyFileSync(p.backup.path.replace(p.job.path, p.job.path + ".old"), p.backup.path) }
    if (attack === "source") writeFileSync(f.c.original.path, "changed")
    if (attack === "tool") writeFileSync(f.c.snapshot.uv, "changed")
    if (attack === "pointer") writeFileSync(join(f.git, "commondir"), ".\n")
    assert.throws(() => verifyMetadataPreparation(f.c, i.nonce, i.candidate, p))
    closeMetadataPreparation(p, true)
    if (attack === "candidate-inode") assert.ok(existsSync(p.candidate.path), "replacement cannot be cleaned")
    assert.ok(existsSync(p.backup.path), "backup history retained")
  } finally { closeMetadataPreparation(p); f.close() }
})

function syntheticBoundary(f, changes = {}) {
  return {
    check: (snapshot) => ({ original: snapshot.inputs["uv.lock"], candidate: digest(metadataCandidate(safeRead(f.c.original.path)).candidate) }),
    redeem: async () => {}, rename: renameSync, ...changes,
  }
}
for (const failure of ["none", "repeat-check", "candidate-mismatch", "redeem", "rename-before", "rename-after", "post-result-loss"]) test(`synthetic runner process-failure boundary: ${failure}`, async () => {
  const f = fixture(), i = invocation(f), paths = metadataPaths(f.c, i.nonce), original = safeRead(f.c.original.path)
  const boundary = syntheticBoundary(f)
  let prepared
  try {
    if (failure === "repeat-check") boundary.check = () => { throw new Error("repeat_check_failed") }
    if (failure === "candidate-mismatch") boundary.check = () => ({ original: i.original, candidate: sha })
    boundary.redeem = async () => {
      prepared = inspectMetadataPreparation(f.c, i.nonce, i.candidate)
      if (failure === "redeem") throw new Error("cancelled")
    }
    if (failure === "rename-before") boundary.rename = () => { throw new Error("rename_failed") }
    if (failure === "rename-after") boundary.rename = (...args) => { renameSync(...args); throw new Error("completion_lost") }
    if (["none", "post-result-loss"].includes(failure)) {
      const result = await executeMetadata(i, boundary)
      if (failure === "none") assert.equal(result.phase, "migrate") // Dropping the result creates no authority on its own.
    } else await assert.rejects(executeMetadata(i, boundary), /repeat_check_failed|candidate_mismatch|cancelled|indeterminate/)
    const promoted = ["none", "rename-after", "post-result-loss"].includes(failure)
    assert.equal(digest(safeRead(f.c.original.path)), promoted ? i.candidate : i.original)
    if (promoted) verifyMetadataTransition(f.c, prepared.candidate, i.candidate)
    assert.equal(existsSync(paths.candidate), false)
    if (!["repeat-check", "candidate-mismatch"].includes(failure)) assert.ok(readFileSync(paths.backup).equals(original))
    if (promoted) await assert.rejects(executeMetadata(i, boundary), /input_changed/)
  } finally { if (prepared) closeMetadataPreparation(prepared); f.close() }
})
for (const attack of ["candidate-inode", "candidate-bytes", "candidate-mode", "backup-inode", "backup-mode", "backup-bytes", "common-inode", "pointer", "tool", "source-inode"]) test(`pure final preflight after redemption rejects ${attack}`, async () => {
  const f = fixture(), i = invocation(f), paths = metadataPaths(f.c, i.nonce)
  let renames = 0
  try {
    await assert.rejects(executeMetadata(i, syntheticBoundary(f, {
      redeem: async () => {
        const path = attack.startsWith("backup") ? paths.backup : paths.candidate
        if (["candidate-inode", "backup-inode"].includes(attack)) { renameSync(path, path + ".old"); copyFileSync(path + ".old", path) }
        if (attack.endsWith("bytes")) writeFileSync(path, "changed")
        if (attack.endsWith("mode")) chmodSync(path, attack.startsWith("backup") ? 0o644 : 0o600)
        if (attack === "common-inode") { renameSync(f.common, f.common + ".old"); mkdirSync(f.common) }
        if (attack === "pointer") writeFileSync(join(f.git, "commondir"), ".\n")
        if (attack === "tool") writeFileSync(f.c.snapshot.uv, "changed")
        if (attack === "source-inode") { renameSync(f.c.original.path, f.c.original.path + ".old"); copyFileSync(f.c.original.path + ".old", f.c.original.path) }
      },
      rename: () => { renames++; assert.fail("rename reached after changed final preflight") },
    })), /indeterminate/)
    assert.equal(renames, 0)
    assert.equal(digest(safeRead(f.c.original.path)), i.original)
    if (attack === "candidate-inode") assert.ok(existsSync(paths.candidate), "unrelated replacement survives cleanup")
  } finally { f.close() }
})
test("post-rename verification failure retains promoted source and original backup without rollback", async () => {
  const f = fixture(), i = invocation(f), paths = metadataPaths(f.c, i.nonce)
  try {
    await assert.rejects(executeMetadata(i, syntheticBoundary(f, { rename: (...args) => {
      renameSync(...args); writeFileSync(join(f.root, "pyproject.toml"), "concurrent edit")
    } })), /indeterminate/)
    assert.equal(digest(safeRead(f.c.original.path)), i.candidate)
    assert.equal(digest(safeRead(paths.backup)), i.original)
    assert.equal(readFileSync(join(f.root, "pyproject.toml"), "utf8"), "concurrent edit")
    await assert.rejects(executeMetadata(i, syntheticBoundary(f)))
  } finally { f.close() }
})

function handshake(permit, binding, operation = "metadata-promotion-v1") {
  return new Promise((resolve, reject) => {
    const c = connect(permit.path); let result = ""
    c.on("error", reject); c.setTimeout(2000, () => c.destroy(new Error("timeout")))
    c.on("connect", () => c.end(JSON.stringify(operation === "setup" ? { nonce: permit.nonce, fingerprint: binding } : { operation, nonce: permit.nonce, fingerprint: binding }) + "\n"))
    c.on("data", (data) => { result += data }); c.on("end", () => resolve(result))
  })
}
for (const domain of ["metadata", "setup-cross-domain", "wrong-binding", "setup-route"]) test(`private capability domain ${domain}`, async () => {
  const f = fixture(), i = invocation(f); let count = 0
  const p = domain === "setup-route" ? await capability(metadataCapabilityBinding(i), () => { count++ }) : await metadataCapability(i, () => { count++ })
  try {
    const result = await handshake(p, domain === "wrong-binding" ? sha : metadataCapabilityBinding(i), domain === "setup-cross-domain" ? "setup" : "metadata-promotion-v1")
    assert.equal(result, domain === "metadata" ? "authorized\n" : "")
    assert.equal(count, domain === "metadata" ? 1 : 0)
    await assert.rejects(handshake(p, metadataCapabilityBinding(i)))
  } finally { p.close(); f.close() }
})
