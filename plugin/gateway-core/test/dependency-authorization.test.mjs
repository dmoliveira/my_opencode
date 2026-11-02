import assert from "node:assert/strict"
import test from "node:test"
import { mkdtempSync, realpathSync, writeFileSync, readFileSync, rmSync, symlinkSync, linkSync, mkdirSync, renameSync, copyFileSync, lstatSync } from "node:fs"
import { tmpdir } from "node:os"
import { join, dirname } from "node:path"
import { pathToFileURL } from "node:url"
import { connect } from "node:net"
import { execFileSync } from "node:child_process"
import { AuthorizationLedger, parseFrame, PENDING_MS, PERMIT_MS, MAX_STATE } from "../dist/hooks/dependency-risk-guard/protocol.js"
import { requirements, hostRequirements, validateAudit, samePackages, execute } from "../dist/hooks/dependency-risk-guard/runner.js"
import { safeRead, validateProject, digest, capture, captureAuditor, recapture, directoryIdentity, snapshotFingerprint, encodeSnapshot, decodeSnapshot, exists, ENV, runnerCommand, RUNNER } from "../dist/hooks/dependency-risk-guard/safety.js"
import { capability } from "../dist/hooks/dependency-risk-guard/capability.js"
import { createDependencyRiskGuardHook, dependencyCommandRisk, nativeDependencyCommand } from "../dist/hooks/dependency-risk-guard/index.js"
import { createNoninteractiveShellGuardHook } from "../dist/hooks/noninteractive-shell-guard/index.js"

const ownedTemp = (prefix) => realpathSync(mkdtempSync(join(tmpdir(), prefix)))
const hash = "a".repeat(64)
const scope = { session: "synthetic-session", call: "audit-call", root: "/synthetic", fingerprint: hash }
const command = (nonce) => `/trusted/node /trusted/runner.js audit ${nonce}`
const frame = (pending) => ({ v: 1, nonce: pending.nonce, fingerprint: pending.fingerprint, packages: 1,
  closure: hash, auditor: "pip-audit==2.10.1", operation: "uv-sync-locked", build: "none", auditorRoot: "/synthetic-auditor", auditorFingerprint: hash })
const encoded = (pending) => JSON.stringify(frame(pending)) + "\n"
const setupScope = { ...scope, call: "setup-call" }
function authorized(now) {
  const ledger = new AuthorizationLedger(now)
  const pending = ledger.begin(scope, command)
  assert.equal(ledger.finish(scope, pending.command, 0, encoded(pending)), true)
  return { ledger, pending }
}

test("correlated audit permits exactly one matching setup, consumed before any attempt", () => {
  const { ledger } = authorized()
  assert.equal(ledger.consume(setupScope).session, scope.session)
  assert.throws(() => ledger.consume({ ...setupScope, call: "retry" }), /authorization_required/)
})

for (const [field, value] of [["session", "other"], ["call", "wrong-call"], ["root", "/other"], ["fingerprint", "b".repeat(64)]]) {
  test(`audit ${field} mismatch cannot issue authority`, () => {
    const ledger = new AuthorizationLedger()
    const pending = ledger.begin(scope, command)
    assert.equal(ledger.finish({ ...scope, [field]: value }, pending.command, 0, encoded(pending)), false)
    // A result from another session cannot revoke or grant authority to this session.
    assert.throws(() => ledger.consume(setupScope))
  })
}

for (const exit of [undefined, null, "0", false, 1, -1, NaN, Infinity]) {
  test(`exit ${String(exit)} is not numeric success`, () => {
    const ledger = new AuthorizationLedger()
    const pending = ledger.begin(scope, command)
    assert.equal(ledger.finish(scope, pending.command, exit, encoded(pending)), false)
    assert.throws(() => ledger.consume(setupScope))
  })
}

const invalidFrames = {
  pass: () => "PASS\n", empty: () => "", object: (p) => frame(p),
  truncated: (p) => encoded(p).slice(0, -4), extra: (p) => encoded(p) + "{}\n",
  chatter: (p) => "PASS\n" + encoded(p), oversized: () => "x".repeat(2049),
  forgedNonce: (p) => JSON.stringify({ ...frame(p), nonce: hash }) + "\n",
  wrongHash: (p) => JSON.stringify({ ...frame(p), fingerprint: "b".repeat(64) }) + "\n",
  extraField: (p) => JSON.stringify({ ...frame(p), ignored: true }) + "\n",
  incomplete: (p) => JSON.stringify({ ...frame(p), packages: 0 }) + "\n",
  wrongScanner: (p) => JSON.stringify({ ...frame(p), auditor: "pip-audit==other" }) + "\n",
  falseBuildClosure: (p) => JSON.stringify({ ...frame(p), build: "audited" }) + "\n",
  duplicate: (p) => encoded(p).replace('"v":1', '"v":2,"v":1'),
  wrongOperation: (p) => JSON.stringify({ ...frame(p), operation: "npm-install" }) + "\n",
}
for (const [name, output] of Object.entries(invalidFrames)) {
  test(`frame rejects ${name} and clears pending authority`, () => {
    const ledger = new AuthorizationLedger()
    const pending = ledger.begin(scope, command)
    assert.throws(() => parseFrame(output(pending), pending))
    assert.equal(ledger.finish(scope, pending.command, 0, output(pending)), false)
    assert.equal(ledger.finish(scope, pending.command, 0, encoded(pending)), false)
  })
}

test("final command mutation, concurrent audits and duplicate calls fail closed", () => {
  const ledger = new AuthorizationLedger()
  const pending = ledger.begin(scope, command)
  assert.equal(ledger.finish(scope, pending.command + "; true", 0, encoded(pending)), false)
  assert.throws(() => ledger.begin(scope, command), /conflict/)
  ledger.begin({ ...scope, call: "other-audit" }, command)
  assert.throws(() => ledger.begin({ ...scope, call: "concurrent-audit" }, command), /conflict/)
  assert.throws(() => ledger.consume(setupScope))
})

for (const field of ["root", "fingerprint", "call"]) {
  test(`setup ${field} mismatch consumes even a failed attempt`, () => {
    const { ledger } = authorized()
    const value = field === "call" ? scope.call : "different"
    assert.throws(() => ledger.consume({ ...setupScope, [field]: value }))
    assert.throws(() => ledger.consume(setupScope))
  })
}

test("pending and permits expire, cleanup and restart erase authority", () => {
  let clock = 1000
  const ledger = new AuthorizationLedger(() => clock)
  const pending = ledger.begin(scope, command)
  clock += PENDING_MS
  assert.equal(ledger.finish(scope, pending.command, 0, encoded(pending)), false)
  const second = authorized(() => clock).ledger
  clock += PERMIT_MS
  assert.throws(() => second.consume(setupScope))
  const third = authorized().ledger
  third.clear(scope.session)
  assert.throws(() => third.consume(setupScope))
  assert.throws(() => new AuthorizationLedger().consume(setupScope))
})

test("state bound refuses overflow", () => {
  const ledger = new AuthorizationLedger()
  for (let i = 0; i < MAX_STATE; i++) ledger.begin({ ...scope, session: `s-${i}` }, command)
  assert.throws(() => ledger.begin({ ...scope, session: "overflow" }, command), /conflict/)
})

const requirement = `synthetic-demo==1.0 --hash=sha256:${hash}\n`
const expected = requirements(requirement)
const clean = { dependencies: [{ name: "synthetic_demo", version: "1.0", vulns: [] }], fixes: [] }
test("strict requirements and complete clean audit match normalized package set", () => {
  validateAudit(JSON.stringify(clean), expected)
  samePackages([{ name: "synthetic_demo", version: "1.0" }], expected)
})
test("host markers are evaluated before duplicate checks; no row silently disappears", () => {
  const text = `synthetic-demo==1.0 ; sys_platform == 'win32' --hash=sha256:${hash}\n` +
    `synthetic-demo==2.0 ; sys_platform != 'win32' --hash=sha256:${hash}\n`
  assert.equal(requirements(text, (marker) => marker.includes("!="))[0].version, "2.0")
  assert.throws(() => requirements(text), /marker_evaluation_required/)
  assert.throws(() => requirements(text, () => "false"), /marker_invalid/)
  assert.throws(() => requirements(text, () => true), /duplicate/)
  const evaluated = hostRequirements(text, { python: "/trusted/python", root: "/synthetic" }, { libraries: ["/trusted/library"] }, (exe, args) => {
    assert.equal(exe, "/trusted/python")
    assert.deepEqual(args.slice(0, 4), ["-I", "-S", "-B", "-c"])
    assert.ok(args[4].includes("from packaging.markers import Marker"))
    assert.ok(!args[4].includes("eval("))
    assert.equal(JSON.parse(args[5]).length, 2)
    return "[false, true]"
  })
  assert.equal(evaluated[0].version, "2.0")
  assert.throws(() => hostRequirements(text, { python: "/trusted/python", root: "/synthetic" }, { libraries: [] }, () => "[]"), /marker_invalid/)
})

for (const command of ["uv --version", "uv --help", "uv sync --help", "uv pip list", "uv pip sync --help", "npm --help", "npm run build", "npm run lint", "npm run test", "npm --prefix plugin/gateway-core run build", "node --test test/dependency-risk-guard-hook.test.mjs"]) {
  test(`metadata/build command remains available: ${command}`, () => assert.equal(dependencyCommandRisk(command), false))
}

test("only this actual session's exact runtime prefix is recognized and preserved", () => {
  const prefix = "OPENCODE_SESSION_ID='synthetic-session' "
  assert.deepEqual(nativeDependencyCommand(prefix + "uv sync --locked", "synthetic-session"), { command: "uv sync --locked", prefix })
  for (const command of ["OPENCODE_SESSION_ID='other' uv sync --locked", "OPENCODE_SESSION_ID=synthetic-session uv sync --locked",
    prefix + prefix + "uv sync --locked", "UV_INDEX_URL=other " + prefix + "uv sync --locked"]) {
    assert.notEqual(nativeDependencyCommand(command, "synthetic-session").command, "uv sync --locked")
  }
})

for (const command of ["uv --help", "npm --prefix plugin/gateway-core run lint", "npm run test"]) {
  test(`actual mandatory session hook composes with safe command ${command}`, async () => {
    const directory = ownedTemp("synthetic-runtime-prefix-")
    try {
      const input = { tool: "bash", sessionID: "synthetic-session", callID: "metadata-call" }
      const output = { args: { command } }
      const shell = createNoninteractiveShellGuardHook({ directory, enabled: true, injectEnvPrefix: true, envPrefixes: ["CI=true"], prefixCommands: ["git", "gh"], blockedPatterns: [] })
      await shell.event("tool.execute.before", { input, output })
      assert.equal(output.args.command, "OPENCODE_SESSION_ID='synthetic-session' " + command)
      const guard = createDependencyRiskGuardHook({ directory, enabled: true, lockfilePatterns: [], commandPatterns: [] })
      await guard.event("tool.execute.before", { input, output })
    } finally { rmSync(directory, { recursive: true, force: true }) }
  })
}
for (const text of ["", "demo>=1", "demo @ https://example.invalid/demo.whl", "-e .", "-r other.txt", "--index-url https://example.invalid",
  "demo==1", requirement + requirement, requirement.trim() + "; python_version > '3'", "demo[extra]==1 --hash=sha256:" + hash]) {
  test(`requirements deny unsupported form ${JSON.stringify(text).slice(0, 60)}`, () => assert.throws(() => requirements(text)))
}
const badReports = {
  failed: { ...clean, error: "failed" }, ignored: { ...clean, ignored: ["SYNTHETIC-1"] },
  skipped: { dependencies: [{ name: "synthetic-demo", version: "1.0", skip_reason: "missing" }], fixes: [] },
  vulnerable: { dependencies: [{ name: "synthetic-demo", version: "1.0", vulns: [{ id: "SYNTHETIC-1" }] }], fixes: [] },
  incomplete: { dependencies: [], fixes: [] }, wrongVersion: { dependencies: [{ name: "synthetic-demo", version: "2", vulns: [] }], fixes: [] },
  duplicate: { dependencies: [...clean.dependencies, ...clean.dependencies], fixes: [] },
  extraPackage: { dependencies: [...clean.dependencies, { name: "unexpected", version: "1", vulns: [] }], fixes: [] },
  fixes: { ...clean, fixes: [{ id: "SYNTHETIC-1" }] },
}
for (const [name, value] of Object.entries(badReports)) {
  test(`audit denies ${name}`, () => assert.throws(() => validateAudit(JSON.stringify(value), expected)))
}
for (const report of ["PASS", "{", JSON.stringify(clean) + "{}", JSON.stringify(clean).replace('"fixes":[]', '"fixes":[1],"fixes":[]')]) {
  test(`malformed/duplicate audit ${report.slice(0, 30)} is refused`, () => assert.throws(() => validateAudit(report, expected)))
}

const project = { project: { name: "synthetic-demo", version: "1" }, tool: { uv: { package: false } } }
const lock = { package: [{ name: "synthetic-root", source: { virtual: "." } }, {
  name: "synthetic-demo", source: { registry: "https://pypi.org/simple" }, wheels: [{ url: "https://files.pythonhosted.org/demo.whl", hash: "sha256:" + hash }],
}] }
test("virtual project with registry wheel closure has an empty build closure", () => validateProject(project, lock))
for (const [name, change] of Object.entries({
  build: (p) => { p["build-system"] = { requires: ["synthetic-build==1"], "build-backend": "synthetic.build" } },
  dynamic: (p) => { p.project.dynamic = ["version"] },
  source: (p) => { p.tool.uv.sources = { demo: { path: "." } } },
  workspace: (p) => { p.tool.uv.workspace = { members: ["*"] } },
  index: (p) => { p.tool.uv.index = [{ url: "https://example.invalid" }] },
  group: (p) => { p.tool.uv["default-groups"] = ["other"] },
  packaged: (p) => { p.tool.uv.package = true },
})) {
  test(`project refuses ${name}`, () => {
    const value = structuredClone(project); change(value)
    assert.throws(() => validateProject(value, lock))
  })
}
for (const source of [{ git: "https://example.invalid/repo" }, { editable: "." }, { path: "../other" }, { url: "https://example.invalid/demo.whl" }, { registry: "https://example.invalid/simple" }]) {
  test(`source ${JSON.stringify(source)} is unsupported`, () => {
    const value = structuredClone(lock); value.package[1].source = source
    assert.throws(() => validateProject(project, value))
  })
}
test("missing wheels and wheel URL/path abuse fail closed", () => {
  for (const wheels of [[], [{ url: "https://files.pythonhosted.org.evil.invalid/x.whl", hash: "sha256:" + hash }], [{ url: "file:///tmp/x.whl", hash: "sha256:" + hash }]]) {
    const value = structuredClone(lock); value.package[1].wheels = wheels
    assert.throws(() => validateProject(project, value))
  }
})

test("safe inputs reject symlinks, hardlinks, alias ancestors, directories and oversized files", () => {
  const directory = ownedTemp("synthetic-safe-input-")
  try {
    const path = join(directory, "input")
    writeFileSync(path, "data")
    assert.equal(safeRead(path).toString(), "data")
    symlinkSync(path, join(directory, "symlink"))
    assert.throws(() => safeRead(join(directory, "symlink")))
    linkSync(path, join(directory, "hardlink"))
    assert.throws(() => safeRead(path))
    symlinkSync(directory, join(directory, "alias"))
    assert.throws(() => safeRead(join(directory, "alias", "input")))
    assert.throws(() => safeRead(directory))
    writeFileSync(join(directory, "large"), "12345")
    assert.throws(() => safeRead(join(directory, "large"), 4))
    assert.throws(() => safeRead(directory + "/../input"))
  } finally { rmSync(directory, { recursive: true, force: true }) }
})

test("auditor recapture hashes changed executable code without ever invoking it", () => {
  const directory = ownedTemp("synthetic-auditor-")
  try {
    const cache = join(directory, "cache")
    const root = join(cache, "archive-v0", "synthetic-tool")
    const python = join(directory, "python")
    const marker = join(directory, "executed")
    mkdirSync(join(root, "bin"), { recursive: true })
    mkdirSync(join(root, "lib", "python3.12", "site-packages"), { recursive: true })
    writeFileSync(python, `#!/bin/sh\nprintf unsafe > '${marker}'\n`, { mode: 0o700 })
    symlinkSync(python, join(root, "bin", "python"))
    writeFileSync(join(root, "pyvenv.cfg"), "synthetic")
    const snapshot = { cache, python, uv: "/must-not-execute/uv", root: directory, version: "3.12.16" }
    const before = captureAuditor(root, snapshot)
    assert.equal(exists(marker), false)
    writeFileSync(python, `#!/bin/sh\nprintf mutated > '${marker}'\n`)
    assert.notEqual(captureAuditor(root, snapshot).fingerprint, before.fingerprint)
    assert.equal(exists(marker), false)
    assert.throws(() => captureAuditor(root, { ...snapshot, python: "/different/python" }), /auditor_interpreter_mismatch/)
  } finally { rmSync(directory, { recursive: true, force: true }) }
})

function exchange(path, data) {
  return new Promise((resolve, reject) => {
    const client = connect(path); let result = ""
    client.on("error", reject)
    client.on("connect", () => client.end(data))
    client.on("data", (chunk) => { result += chunk.toString() })
    client.on("end", () => resolve(result))
  })
}
test("host capability permits one exact redemption and then deletes the socket", async () => {
  let checks = 0
  const permit = await capability(hash, () => { checks++ })
  try {
    assert.equal(await exchange(permit.path, JSON.stringify({ nonce: permit.nonce, fingerprint: hash }) + "\n"), "authorized\n")
    assert.equal(checks, 1)
    await assert.rejects(exchange(permit.path, JSON.stringify({ nonce: permit.nonce, fingerprint: hash }) + "\n"))
  } finally { permit.close() }
})
test("forged capability and changed inputs revoke even subsequent correct redemption", async () => {
  for (const mutated of [false, true]) {
    const permit = await capability(hash, () => { if (mutated) throw new Error("changed") })
    try {
      assert.notEqual(await exchange(permit.path, JSON.stringify({ nonce: mutated ? permit.nonce : hash, fingerprint: hash }) + "\n"), "authorized\n")
      await assert.rejects(exchange(permit.path, JSON.stringify({ nonce: permit.nonce, fingerprint: hash }) + "\n"))
    } finally { permit.close() }
  }
})

function syntheticSnapshot(helpersDirectory = dirname(RUNNER), gitMarkerFile = false) {
  const base = ownedTemp("synthetic-bound-snapshot-")
  const root = join(base, "project")
  const cache = join(base, "cache")
  const gitDirectory = gitMarkerFile ? join(base, "git-directory") : join(root, ".git")
  for (const path of [root, cache, gitDirectory]) mkdirSync(path, { recursive: true })
  for (const name of ["pyproject.toml", "uv.lock", ".python-version"]) writeFileSync(join(root, name), "synthetic")
  if (gitMarkerFile) writeFileSync(join(root, ".git"), "gitdir: " + gitDirectory + "\n")
  const markerPath = join(root, ".git")
  const markerStat = lstatSync(markerPath, { bigint: true })
  const marker = { path: markerPath, dev: markerStat.dev.toString(), ino: markerStat.ino.toString(),
    kind: gitMarkerFile ? "file" : "directory", sha256: gitMarkerFile ? digest(safeRead(markerPath)) : "" }
  const paths = Object.fromEntries(["node", "git", "uv", "python"].map((name) => {
    const path = join(base, name)
    writeFileSync(path, `#!/bin/sh\nprintf '${name}' > '${join(base, "executed")}'\n`, { mode: 0o700 })
    return [name, path]
  }))
  const draft = { v: 1, policy: "virtual-wheel-only-v3", root, ...paths, cache, version: "3.12.16",
    inputs: Object.fromEntries(["pyproject.toml", "uv.lock", ".python-version"].map((name) => [name, digest("synthetic")])),
    executables: Object.fromEntries(Object.entries(paths).map(([name, path]) => [name, { path, sha256: digest(safeRead(path)) }])),
    helpers: ["index.js", "protocol.js", "capability.js", "runner.js", "safety.js"].map((name) => {
      const path = join(helpersDirectory, name); return { path, sha256: digest(safeRead(path)) }
    }),
    directories: { root: directoryIdentity(root), cache: directoryIdentity(cache), git: directoryIdentity(gitDirectory) },
    marker, absent: ["uv.toml"] }
  const snapshot = { ...draft, fingerprint: snapshotFingerprint(draft) }
  return { root, base, snapshot, close: () => rmSync(base, { recursive: true, force: true }) }
}

test("canonical bounded snapshots round-trip and reject malformed or substituted evidence", () => {
  const f = syntheticSnapshot()
  try {
    assert.deepEqual(decodeSnapshot(encodeSnapshot(f.snapshot)), f.snapshot)
    assert.equal(recapture(f.snapshot), f.snapshot)
    const raw = JSON.stringify(f.snapshot)
    for (const value of ["", "PASS", "a".repeat(32769),
      Buffer.from(" " + raw).toString("base64url"),
      Buffer.from(raw.replace('"v":1', '"v":2,"v":1')).toString("base64url"),
      Buffer.from(JSON.stringify({ ...f.snapshot, fingerprint: "b".repeat(64) })).toString("base64url"),
      Buffer.from(JSON.stringify({ ...f.snapshot, extra: true })).toString("base64url")]) assert.throws(() => decodeSnapshot(value))
  } finally { f.close() }
})

test("metadata policy retains snapshot binding but cannot enter normal audit/setup", async () => {
  const f = syntheticSnapshot()
  try {
    const draft = { ...f.snapshot, policy: "read-only-editable-dot-metadata-v1" }
    const metadata = { ...draft, fingerprint: snapshotFingerprint(draft) }
    assert.deepEqual(decodeSnapshot(encodeSnapshot(metadata)), metadata)
    assert.equal(recapture(metadata), metadata)
    const never = () => assert.fail("normal authority path reached")
    for (const mode of ["audit", "setup"]) await assert.rejects(execute(mode, f.root, hash, metadata.fingerprint, "", "", "", metadata,
      { inspect: never, subprocess: never, auditor: never, inspectAuditor: never }), /metadata_snapshot_not_authorized/)
    assert.throws(() => runnerCommand(metadata, "audit", hash), /metadata_snapshot_not_authorized/)
    writeFileSync(metadata.uv, "changed")
    assert.throws(() => recapture(metadata), /bound_file_changed/)
    assert.equal(exists(join(f.base, "executed")), false)
  } finally { f.close() }
})

for (const name of ["node", "git", "uv", "python"]) {
  test(`pure recapture rejects changed ${name} without executing its replacement`, () => {
    const f = syntheticSnapshot()
    try {
      writeFileSync(f.snapshot[name], `#!/bin/sh\nprintf unsafe > '${join(f.base, "executed")}'\n`)
      assert.throws(() => recapture(f.snapshot), /bound_file_changed/)
      assert.equal(exists(join(f.base, "executed")), false)
    } finally { f.close() }
  })
}

for (const target of ["pyproject.toml", "uv.lock", ".python-version", "uv.toml", ".git", "root", "cache", "git-directory"]) {
  test(`pure recapture rejects changed ${target} without invoking any executable`, () => {
    const f = syntheticSnapshot(dirname(RUNNER), true)
    try {
      if (["root", "cache", "git-directory"].includes(target)) {
        const path = target === "root" ? f.root : target === "cache" ? f.snapshot.cache : f.snapshot.directories.git.path
        renameSync(path, path + "-old"); mkdirSync(path)
      } else writeFileSync(join(f.root, target), "changed")
      assert.throws(() => recapture(f.snapshot))
      assert.equal(exists(join(f.base, "executed")), false)
    } finally { f.close() }
  })
}

test("pure recapture rejects helper mutation against the already-loaded module identity", async () => {
  const isolated = ownedTemp("synthetic-isolated-helpers-")
  let f
  try {
    writeFileSync(join(isolated, "package.json"), '{"type":"module"}')
    for (const name of ["index.js", "protocol.js", "capability.js", "runner.js", "safety.js"]) copyFileSync(join(dirname(RUNNER), name), join(isolated, name))
    const module = await import(pathToFileURL(join(isolated, "safety.js")).href)
    f = syntheticSnapshot(isolated)
    module.recapture(f.snapshot)
    writeFileSync(join(isolated, "runner.js"), safeRead(join(isolated, "runner.js")).toString() + "\n// changed\n")
    assert.throws(() => module.recapture(f.snapshot), /bound_file_changed/)
    assert.equal(exists(join(f.base, "executed")), false)
  } finally { f?.close(); rmSync(isolated, { recursive: true, force: true }) }
})

test("bound host and runner paths never perform fresh executable discovery", () => {
  const index = readFileSync(new URL("../src/hooks/dependency-risk-guard/index.ts", import.meta.url), "utf8")
  const runner = readFileSync(new URL("../src/hooks/dependency-risk-guard/runner.ts", import.meta.url), "utf8")
  assert.equal(index.match(/\bcapture\(/g)?.length, 1)
  assert.match(index, /command === AUTH_REQUEST[\s\S]*?const snapshot = capture\(directory\)/)
  assert.match(index, /tool.execute.before.final[\s\S]*?recapture\(expected.snapshot\)/)
  assert.equal(runner.match(/\bcapture\(/g), null)
  assert.match(runner, /const subprocess: typeof run = \(\.\.\.args\) => \{ recheck\(\); return boundary.subprocess/)
})

function fixture() {
  const f = syntheticSnapshot()
  const { root, snapshot } = f
  const calls = []
  // Protocol fixture scopes deliberately use a stable synthetic fingerprint.
  const fixtureSnapshot = { ...snapshot, fingerprint: hash }
  let inspectCount = 0
  const options = { fail: "", mutateAt: Infinity, auditorChanged: false, report: JSON.stringify(clean), compiled: requirement, installed: clean.dependencies }
  const auditor = { root: "/synthetic-auditor", fingerprint: hash, python: snapshot.python, libraries: ["/trusted/site-packages"] }
  const boundary = {
    auditor: () => auditor,
    inspectAuditor: () => ({ ...auditor, fingerprint: options.auditorChanged ? "b".repeat(64) : hash }),
    inspect() { return { ...fixtureSnapshot, fingerprint: ++inspectCount >= options.mutateAt ? "b".repeat(64) : hash } },
    subprocess(exe, args, cwd, timeout, environment) {
      calls.push({ exe, args, cwd, timeout, environment })
      const operation = args[0] === "pip" ? args.slice(0, 2).join(" ") : args[0]
      if (operation === options.fail) throw new Error("synthetic subprocess failure")
      if (operation === "export") return requirement
      if (operation === "pip compile") { writeFileSync(args[args.indexOf("--output-file") + 1], options.compiled); return "" }
      if (exe === snapshot.python) return args.includes("--version") ? "pip-audit 2.10.1\n" : options.report
      if (operation === "pip list") return JSON.stringify(options.installed)
      if (["venv", "pip sync", "sync"].includes(operation)) return ""
      throw new Error("unexpected fixture subprocess")
    },
  }
  return { ...f, snapshot: fixtureSnapshot, actualSnapshot: snapshot, calls, options, boundary }
}

test("mock subprocess integration: real host request/result then exactly one freshly audited setup", async () => {
  const f = fixture()
  const ledger = new AuthorizationLedger()
  const actualScope = { ...scope, root: f.root }
  let permit
  try {
    const pending = ledger.begin(actualScope, (nonce) => runnerCommand(f.actualSnapshot, "audit", nonce))
    const result = await execute("audit", f.root, pending.nonce, hash, "", "", "", f.snapshot, f.boundary)
    assert.equal(f.calls.some((c) => ["venv", "sync"].includes(c.args[0]) || c.args.slice(0, 2).join(" ") === "pip sync"), false)
    assert.equal(ledger.finish(actualScope, pending.command, 0, JSON.stringify(result) + "\n"), true)
    ledger.consume({ ...actualScope, call: "setup" })
    permit = await capability(digest(hash + hash), () => {})
    await execute("setup", f.root, permit.nonce, hash, permit.path, "/synthetic-auditor", hash, f.snapshot, f.boundary)
    assert.throws(() => ledger.consume({ ...actualScope, call: "retry" }))
    const installs = f.calls.filter((c) => c.args.slice(0, 2).join(" ") === "pip sync")
    assert.equal(installs.length, 1)
    for (const flag of ["--require-hashes", "--only-binary", "--no-config", "--no-cache", "--strict"]) assert.ok(installs[0].args.includes(flag))
    assert.equal(installs[0].args[installs[0].args.indexOf("--only-binary") + 1], ":all:")
    assert.equal(installs[0].args.includes("--no-build"), false) // UV rejects this redundant flag combination.
    const sync = f.calls.find((c) => c.args[0] === "sync")
    assert.deepEqual(sync.environment, { UV_PROJECT_ENVIRONMENT: join(f.root, ".venv") })
    for (const flag of ["--locked", "--no-build-isolation", "--inexact", "--no-build"]) assert.ok(sync.args.includes(flag))
    assert.equal(f.calls.filter((c) => c.exe === f.snapshot.python && c.args.includes("--strict")).length, 2)
    assert.equal(f.calls.every((c) => Object.values(f.snapshot.executables).some((file) => file.path === c.exe) && !c.args.includes("--ignore-vuln")), true)
    assert.equal(Object.keys(ENV).some((key) => /INDEX|VIRTUAL_ENV|PYTHONPATH|CONSTRAINT/.test(key)), false)
  } finally { permit?.close(); f.close() }
})

for (const fail of ["export", "pip compile", "-I"]) {
  test(`runner ${fail} failure produces no authority or install`, async () => {
    const f = fixture(); f.options.fail = fail
    try { await assert.rejects(execute("audit", f.root, hash, hash, "", "", "", f.snapshot, f.boundary)); assert.equal(f.calls.some((c) => c.args[0] === "venv"), false) }
    finally { f.close() }
  })
}
for (const point of [2, 3, 4]) {
  test(`runner mutated input/interpreter/config at snapshot ${point} refuses before install`, async () => {
    const f = fixture(); f.options.mutateAt = point
    let permit
    try {
      permit = await capability(digest(hash + hash), () => {})
      await assert.rejects(execute("setup", f.root, permit.nonce, hash, permit.path, "/synthetic-auditor", hash, f.snapshot, f.boundary))
      assert.equal(f.calls.some((c) => c.args[0] === "venv"), false)
    } finally { permit?.close(); f.close() }
  })
}
for (const [name, modify] of Object.entries({
  vulnerable: (f) => { f.options.report = JSON.stringify(badReports.vulnerable) },
  omitted: (f) => { f.options.report = JSON.stringify(badReports.incomplete) },
  ignored: (f) => { f.options.report = JSON.stringify(badReports.ignored) },
  compiledExtra: (f) => { f.options.compiled += `unexpected==1 --hash=sha256:${hash}\n` },
  changedHash: (f) => { f.options.compiled = requirement.replace(hash, "b".repeat(64)) },
})) {
  test(`runner ${name} cannot reach setup`, async () => {
    const f = fixture(); modify(f)
    let permit
    try {
      permit = await capability(digest(hash + hash), () => {})
      await assert.rejects(execute("setup", f.root, permit.nonce, hash, permit.path, "/synthetic-auditor", hash, f.snapshot, f.boundary))
      assert.equal(f.calls.some((c) => c.args[0] === "venv"), false)
    } finally { permit?.close(); f.close() }
  })
}

test("setup independently refuses changed installed package coverage", async () => {
  const f = fixture(); f.options.installed = []
  const permit = await capability(digest(hash + hash), () => {})
  try { await assert.rejects(execute("setup", f.root, permit.nonce, hash, permit.path, "/synthetic-auditor", hash, f.snapshot, f.boundary), /coverage/) }
  finally { permit.close(); f.close() }
})

test("auditor mutation or wrong granted identity cannot reach installation", async () => {
  for (const changed of [false, true]) {
    const f = fixture(); f.options.auditorChanged = changed
    const permit = await capability(digest(hash + hash), () => {})
    try {
      await assert.rejects(execute("setup", f.root, permit.nonce, hash, permit.path, "/synthetic-auditor", changed ? hash : "b".repeat(64), f.snapshot, f.boundary), /auditor_changed/)
      assert.equal(f.calls.some((c) => c.args[0] === "venv"), false)
    } finally { permit.close(); f.close() }
  }
})

test("setup never rediscovers or executes a changed granted auditor", async () => {
  const f = fixture()
  f.options.auditorChanged = true
  f.boundary.auditor = () => { throw new Error("setup_must_not_discover_or_execute_auditor") }
  try {
    await assert.rejects(execute("setup", f.root, hash, hash, "/unused-socket", "/synthetic-auditor", hash, f.snapshot, f.boundary), /auditor_changed/)
    assert.equal(f.calls.length, 0)
  } finally { f.close() }
})

test("runner startup rejects a replaced bound interpreter before any subprocess", async () => {
  const f = fixture()
  f.boundary.inspect = recapture
  try {
    writeFileSync(f.actualSnapshot.python, `#!/bin/sh\nprintf unsafe > '${join(f.base, "executed")}'\n`)
    await assert.rejects(execute("setup", f.root, hash, f.actualSnapshot.fingerprint, "/unused-socket", "/synthetic-auditor", hash,
      f.actualSnapshot, f.boundary), /bound_file_changed/)
    assert.equal(f.calls.length, 0)
    assert.equal(exists(join(f.base, "executed")), false)
  } finally { f.close() }
})

test("central subprocess preflight rejects a mutation between operations", async () => {
  const f = fixture()
  f.boundary.inspect = recapture
  const original = f.boundary.subprocess
  f.boundary.subprocess = (...args) => {
    const result = original(...args)
    if (args[1][0] === "export") writeFileSync(f.actualSnapshot.uv, "changed")
    return result
  }
  try {
    await assert.rejects(execute("audit", f.root, hash, f.actualSnapshot.fingerprint, "", "", "", f.actualSnapshot, f.boundary), /bound_file_changed/)
    assert.equal(f.calls.length, 1)
    assert.equal(f.calls[0].args[0], "export")
    assert.equal(exists(join(f.base, "executed")), false)
  } finally { f.close() }
})

test("copied snapshot evidence cannot install without the one-shot host socket", async () => {
  const f = fixture()
  f.boundary.inspect = recapture
  try {
    const copied = decodeSnapshot(encodeSnapshot(f.actualSnapshot))
    await assert.rejects(execute("setup", f.root, hash, copied.fingerprint, "/missing-host-capability", "/synthetic-auditor", hash, copied, f.boundary), /capability_invalid/)
    assert.equal(f.calls.some((c) => c.args[0] === "venv" || c.args.slice(0, 2).join(" ") === "pip sync"), false)
    assert.equal(exists(join(f.root, ".venv")), false)
  } finally { f.close() }
})

test("setup binds its newly created environment identity before package operations", async () => {
  const f = fixture()
  const original = f.boundary.subprocess
  f.boundary.subprocess = (...args) => {
    const result = original(...args)
    if (args[1][0] === "venv") {
      const environment = join(f.root, ".venv")
      renameSync(environment, environment + "-old"); mkdirSync(environment)
    }
    return result
  }
  const permit = await capability(digest(hash + hash), () => {})
  try {
    await assert.rejects(execute("setup", f.root, permit.nonce, hash, permit.path, "/synthetic-auditor", hash, f.snapshot, f.boundary), /environment_changed/)
    assert.equal(f.calls.some((c) => c.args.slice(0, 2).join(" ") === "pip sync"), false)
  } finally { permit.close(); f.close() }
})

test("host refuses correlated success when the current auditor identity changed", () => {
  const ledger = new AuthorizationLedger()
  const pending = ledger.begin(scope, command)
  assert.equal(ledger.finish(scope, pending.command, 0, encoded(pending), () => { throw new Error("auditor_changed") }), false)
  assert.throws(() => ledger.consume(setupScope))
})

for (const command of ["uv sync --locked", "uv sync --locked --extra test", "uv sync", "sh -c 'uv sync --locked'", "'/trusted/uv' sync --locked",
  "OPENCODE_SESSION_ID='other' npm run test", "OPENCODE_SESSION_ID='s' UV_INDEX_URL=other uv sync --locked", "OPENCODE_SESSION_ID='s' OPENCODE_SESSION_ID='s' uv sync --locked",
  "/tmp/attacker/npm run test", "/tmp/attacker/uv --help", "/tmp/attacker/pip list", "/tmp/attacker/npm --prefix project run build",
  "u\\v sync --locked", "npm ci", "npm install", "python -m pip install demo", "node /trusted/dependency-risk-guard/runner.js setup",
  "dependency-security authorize-uv-sync-locked --pass", "true; uv sync --locked", "UV_INDEX_URL=x uv sync --locked"]) {
  test(`production guard refuses unsupported/unauthorized ${command}`, async () => {
    const directory = ownedTemp("synthetic-guard-")
    try {
      const hook = createDependencyRiskGuardHook({ directory, enabled: true, lockfilePatterns: [], commandPatterns: [] })
      await assert.rejects(hook.event("tool.execute.before", { input: { tool: "bash", sessionID: "s", callID: "c" }, output: { args: { command } } }))
    } finally { rmSync(directory, { recursive: true, force: true }) }
  })
}
test("configured command denials still apply to otherwise safe manager commands", async () => {
  const directory = ownedTemp("synthetic-guard-")
  try {
    const hook = createDependencyRiskGuardHook({ directory, enabled: true, lockfilePatterns: [], commandPatterns: ["npm\\s+run\\s+test"] })
    await assert.rejects(hook.event("tool.execute.before", { input: { tool: "bash", sessionID: "s", callID: "c" }, output: { args: { command: "npm run test" } } }))
  } finally { rmSync(directory, { recursive: true, force: true }) }
})
test("production request missing metadata and direct lockfile patches remain denied", async () => {
  const directory = ownedTemp("synthetic-guard-")
  try {
    const hook = createDependencyRiskGuardHook({ directory, enabled: true, lockfilePatterns: [], commandPatterns: [] })
    await assert.rejects(hook.event("tool.execute.before", { input: { tool: "bash" }, output: { args: { command: "dependency-security authorize-uv-sync-locked" } } }))
    await assert.rejects(hook.event("tool.execute.before", { input: { tool: "apply_patch" }, output: { args: { patchText: "*** Update File: uv.lock\n" } } }))
    await assert.rejects(hook.event("tool.execute.before", { input: { tool: "write" }, output: { args: { filePath: "uv.lock" } } }))
  } finally { rmSync(directory, { recursive: true, force: true }) }
})

test("real executable CLI refuses forged invocation without installation or private diagnostics", () => {
  assert.throws(() => execFileSync(process.execPath, [RUNNER, "audit", "/synthetic-missing", hash, hash, "", "extra"], { encoding: "utf8", stdio: "pipe" }),
    (error) => error.status === 1 && error.stdout === "" && error.stderr === "dependency_security_refused\n")
})

test("real snapshot refuses non-root Git paths and symlinked project roots", () => {
  const directory = ownedTemp("synthetic-git-")
  try {
    execFileSync("/usr/bin/git", ["init", "-q", directory])
    mkdirSync(join(directory, "child"))
    assert.throws(() => capture(join(directory, "child")), /worktree_root_required/)
    symlinkSync(directory, join(directory, "alias"))
    assert.throws(() => capture(join(directory, "alias")), /unsafe_worktree/)
  } finally { rmSync(directory, { recursive: true, force: true }) }
})
