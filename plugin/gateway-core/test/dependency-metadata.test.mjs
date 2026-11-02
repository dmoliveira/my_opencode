import assert from "node:assert/strict"
import test from "node:test"
import { mkdtempSync, realpathSync, mkdirSync, writeFileSync, readFileSync, rmSync, existsSync, readdirSync, symlinkSync, renameSync, copyFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { execFileSync } from "node:child_process"
import { METADATA_POLICY, metadataCandidate, proveMetadataConversion, validateMetadataProject, validateProject,
  digest, runnerCommand, discoverAuditor, captureAuditor } from "../dist/hooks/dependency-risk-guard/safety.js"
import { checkMetadata, execute } from "../dist/hooks/dependency-risk-guard/runner.js"

const manifest = '[project]\nname = "synthetic-demo"\nversion = "1.0.0"\nrequires-python = ">=3.12"\ndependencies = []\n[tool.uv]\npackage = false\n'
const lock = '# Unicode café 🧪 editable in a comment\nversion = 1\nrevision = 3\nrequires-python = ">=3.12"\n\n[[package]]\nname = "synthetic-demo"\nversion = "1.0.0"\nsource = { editable = "." } # retain me\n'
const project = { project: { name: "synthetic-demo", version: "1.0.0", "requires-python": ">=3.12", dependencies: [] }, tool: { uv: { package: false } } }
const parsed = { version: 1, revision: 3, "requires-python": ">=3.12", package: [{ name: "synthetic-demo", version: "1.0.0", source: { editable: "." } }] }
const converted = () => ({ ...structuredClone(parsed), package: [{ ...parsed.package[0], source: { virtual: "." } }] })

test("exact UTF-8 source-key span retains comments and every outside byte", () => {
  const original = Buffer.from(lock)
  const { candidate, start, end } = metadataCandidate(original)
  assert.equal(original.subarray(start, end).toString(), "editable")
  assert.ok(original.subarray(0, start).equals(candidate.subarray(0, start)))
  assert.ok(original.subarray(end).equals(candidate.subarray(start + 7)))
  proveMetadataConversion(project, original, candidate, parsed, converted())
  assert.throws(() => validateProject(project, parsed), /source_unsupported/)
  validateProject(project, converted())
})

for (const [label, mutate] of Object.entries({
  topLevel: (x) => { x.revision++ }, closure: (x) => { x.package.push({ name: "extra" }) },
  edge: (x) => { x.package[0].dependencies = [{ name: "extra" }] },
  hash: (x) => { x.package[0].wheels = [{ hash: "sha256:" + "b".repeat(64) }] },
  root: (x) => { x.package[0].source.virtual = "elsewhere" },
})) test(`semantic proof rejects altered ${label}`, () => {
  const changed = converted(); mutate(changed)
  assert.throws(() => proveMetadataConversion(project, Buffer.from(lock), metadataCandidate(Buffer.from(lock)).candidate, parsed, changed), /metadata_semantics_changed/)
})

for (const text of [lock + lock, lock.replace('source = { editable = "." }', 'source={editable="."}'), lock.replace("editable", "editable").replace('editable = "."', 'editable = "other"')]) {
  test(`ambiguous/noncanonical span fails closed ${text.length}`, () => assert.throws(() => metadataCandidate(Buffer.from(text))))
}
test("invalid UTF-8 and outside-span byte edits fail closed", () => {
  assert.throws(() => metadataCandidate(Buffer.concat([Buffer.from([0xff]), Buffer.from(lock)])))
  assert.throws(() => proveMetadataConversion(project, Buffer.from(lock), Buffer.from(lock.replace("editable", "virtual") + "# extra\n"), parsed, converted()), /metadata_bytes_changed/)
})

test("external registry closure, edges, hashes and top-level fields are retained exactly", () => {
  const external = { name: "external", version: "2.0", source: { registry: "https://pypi.org/simple" },
    wheels: [{ url: "https://files.pythonhosted.org/synthetic/external-2.0-py3-none-any.whl", hash: "sha256:" + "a".repeat(64) }] }
  const source = { ...parsed, package: [{ ...parsed.package[0], dependencies: [{ name: "external" }] }, external] }
  const target = structuredClone(source); target.package[0].source = { virtual: "." }
  const original = Buffer.from(lock + 'dependencies = [{ name = "external" }]\n\n[[package]]\nname = "external"\nversion = "2.0"\nsource = { registry = "https://pypi.org/simple" }\nwheels = [{ url = "https://files.pythonhosted.org/synthetic/external-2.0-py3-none-any.whl", hash = "sha256:' + "a".repeat(64) + '" }]\n')
  const candidate = metadataCandidate(original).candidate
  const { start, end } = metadataCandidate(original)
  assert.ok(original.subarray(end).equals(candidate.subarray(start + 7)))
  proveMetadataConversion(project, original, candidate, source, target)
  for (const mutate of [
    (x) => { x.package[1].wheels[0].hash = "sha256:" + "b".repeat(64) },
    (x) => { x.package[1].version = "3.0" },
    (x) => { x.package[0].dependencies = [] },
    (x) => { x["requires-python"] = ">=3.13" },
  ]) {
    const changed = structuredClone(target); mutate(changed)
    assert.throws(() => proveMetadataConversion(project, original, candidate, source, changed), /metadata_semantics_changed/)
  }
})

for (const [label, change] of Object.entries({
  duplicate: (p, l) => l.package.push(structuredClone(l.package[0])),
  multiple: (p, l) => l.package.push({ ...l.package[0], name: "another", source: { virtual: "." } }),
  mismatch: (p) => { p.project.version = "2" },
  backend: (p) => { p["build-system"] = {} }, dynamic: (p) => { p.project.dynamic = ["version"] },
  config: (p) => { p.tool.uv.sources = {} }, tool: (p) => { p.tool.other = {} },
  source: (p, l) => l.package.push({ name: "external", source: { git: "elsewhere" } }),
  url: (p) => { p.project.dependencies = ["demo @ https://example.invalid/demo.whl"] },
})) test(`metadata policy rejects ${label}`, () => {
  const p = structuredClone(project), l = structuredClone(parsed); change(p, l)
  assert.throws(() => validateMetadataProject(p, l))
})

function fixture() {
  const base = realpathSync(mkdtempSync(join(tmpdir(), "synthetic-metadata-unit-")))
  const root = join(base, "source"), stagingParent = join(base, "staging")
  mkdirSync(root); mkdirSync(stagingParent)
  const previous = Object.fromEntries(["TMPDIR", "TMP", "TEMP"].map((name) => [name, process.env[name]]))
  for (const name of Object.keys(previous)) process.env[name] = stagingParent
  const inputs = { "pyproject.toml": manifest, "uv.lock": lock, ".python-version": "3.12.16\n" }
  for (const [name, data] of Object.entries(inputs)) writeFileSync(join(root, name), data)
  mkdirSync(join(root, ".venv")); writeFileSync(join(root, ".venv", "sentinel"), "unchanged")
  const sentinel = { path: join(root, ".venv", "sentinel"), sha256: digest("unchanged") }
  const snapshot = { policy: METADATA_POLICY, root, version: "3.12.16", python: "/bound/python", uv: "/bound/uv", fingerprint: "a".repeat(64), inputs: Object.fromEntries(Object.entries(inputs).map(([k, v]) => [k, digest(v)])) }
  const calls = [], stages = []
  const boundary = {
    inspect: (s) => {
      for (const [name, hash] of Object.entries(s.inputs)) assert.equal(digest(readFileSync(join(root, name))), hash, "input_changed")
      return s
    },
    subprocess: (exe, args, cwd, timeout, env) => {
      calls.push([exe, args]); stages.push(cwd)
      assert.equal(timeout, 60000); assert.equal(env.TMPDIR, cwd)
      assert.equal(env.UV_CACHE_DIR, join(cwd, "cache"))
      if (exe === snapshot.python) return JSON.stringify({ project, original: parsed, candidate: converted(), version: snapshot.version })
      assert.equal(exe, snapshot.uv)
      if (args[0] === "--version") return "uv 0.13.6 (synthetic)"
      assert.deepEqual(args, ["lock", "--check", "--offline", "--no-config", "--no-cache", "--no-build", "--no-python-downloads", "--python", snapshot.python, "--project", cwd])
      return ""
    },
  }
  return { base, root, stagingParent, snapshot, sentinel, calls, stages, boundary, close: () => {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[name]
      else process.env[name] = value
    }
    rmSync(base, { recursive: true, force: true })
  } }
}

for (const config of ["pyproject.toml", "uv.toml", ".python-version"]) {
  for (const kind of ["file", "directory", "dangling-symlink"]) test(`foreign ancestor ${config} (${kind}) blocks before staging/subprocess`, () => {
    const f = fixture()
    try {
      const path = join(f.base, config)
      if (kind === "file") writeFileSync(path, config === "pyproject.toml" ? '[tool.uv.workspace]\nmembers = ["staging/*"]\n' : "foreign")
      else if (kind === "directory") mkdirSync(path)
      else symlinkSync(join(f.base, "missing-target"), path)
      assert.throws(() => checkMetadata(f.snapshot, [f.sentinel], f.boundary), /metadata_staging_ancestor_config/)
      assert.deepEqual(readdirSync(f.stagingParent), [])
      assert.equal(f.calls.length, 0)
    } finally { f.close() }
  })
}

for (const location of ["root", "descendant", "alias-descendant"]) test(`source ${location} TMPDIR rejected before staging creation`, () => {
  const f = fixture()
  try {
    const inside = location === "root" ? f.root : join(f.root, "temporary-parent")
    if (inside !== f.root) mkdirSync(inside)
    const before = readdirSync(inside)
    if (location === "alias-descendant") {
      const alias = join(f.base, "alias"); symlinkSync(inside, alias); process.env.TMPDIR = alias
    } else process.env.TMPDIR = inside
    assert.throws(() => checkMetadata(f.snapshot, [f.sentinel], f.boundary), /metadata_staging_inside_source/)
    assert.deepEqual(readdirSync(inside), before)
    assert.equal(f.calls.length, 0)
    assert.deepEqual(readdirSync(f.stagingParent), [])
  } finally { f.close() }
})

for (const before of ["--version", "lock"]) test(`ancestor config introduced before ${before} blocks next subprocess and cleans staging`, () => {
  const f = fixture(), base = f.boundary.subprocess
  try {
    f.boundary.subprocess = (...args) => {
      const result = base(...args)
      if ((before === "--version" && args[0] === f.snapshot.python) || (before === "lock" && args[1][0] === "--version")) {
        writeFileSync(join(f.base, "pyproject.toml"), '[tool.uv.workspace]\nmembers = ["staging/*"]\n')
      }
      return result
    }
    assert.throws(() => checkMetadata(f.snapshot, [f.sentinel], f.boundary), /metadata_staging_ancestor_config/)
    assert.ok(!f.calls.some(([, args]) => args[0] === before))
    assert.deepEqual(readdirSync(f.stagingParent), [])
    assert.equal(readFileSync(join(f.root, "uv.lock"), "utf8"), lock)
    assert.equal(digest(readFileSync(f.sentinel.path)), f.sentinel.sha256)
  } finally { f.close() }
})

test("replacement of owned staging with identical files fails directory identity binding", () => {
  const f = fixture(), base = f.boundary.subprocess
  try {
    f.boundary.subprocess = (...args) => {
      const result = base(...args)
      if (args[0] === f.snapshot.python) {
        const cwd = args[2], old = join(f.base, "old-stage")
        renameSync(cwd, old); mkdirSync(cwd)
        for (const name of ["pyproject.toml", "uv.lock", ".python-version"]) copyFileSync(join(old, name), join(cwd, name))
      }
      return result
    }
    assert.throws(() => checkMetadata(f.snapshot, [f.sentinel], f.boundary), /metadata_staging_changed/)
    assert.equal(f.calls.length, 1)
    assert.deepEqual(readdirSync(f.stagingParent), [])
  } finally { f.close() }
})

test("checker has exactly parser/version/read-only check calls, private stage cleanup and unchanged environment", () => {
  const f = fixture()
  try {
    const result = checkMetadata(f.snapshot, [f.sentinel], f.boundary)
    assert.equal(result.policy, METADATA_POLICY); assert.equal(f.calls.length, 3)
    assert.equal(readFileSync(join(f.root, "uv.lock"), "utf8"), lock)
    assert.equal(digest(readFileSync(f.sentinel.path)), f.sentinel.sha256)
    assert.ok(f.stages.every((path) => !existsSync(path)))
    assert.equal("operation" in result, false); assert.equal("nonce" in result, false)
  } finally { f.close() }
})

for (const kind of ["input", "tool", "parser", "version", "lock", "stage", "sentinel", "duplicate-toml"]) test(`checker fails closed on ${kind}`, () => {
  const f = fixture()
  const base = f.boundary.subprocess
  try {
    if (kind === "input") writeFileSync(join(f.root, "uv.lock"), lock + "# changed")
    if (kind === "tool") f.boundary.inspect = () => { throw new Error("bound_file_changed") }
    f.boundary.subprocess = (...args) => {
      const [exe, argv, cwd] = args
      if (kind === "parser" && exe === f.snapshot.python) throw new Error("parser_failed")
      if (kind === "version" && argv[0] === "--version") return "uv 0.0.0"
      if (kind === "lock" && argv[0] === "lock") throw new Error("offline_check_failed")
      if (kind === "stage") writeFileSync(join(cwd, "uv.lock"), "changed")
      if (kind === "sentinel") writeFileSync(f.sentinel.path, "changed")
      if (kind === "duplicate-toml" && exe === f.snapshot.python) {
        // Real trusted stdlib parsing rejects duplicate TOML rather than accepting last-key-wins.
        return execFileSync("python3.12", [...argv.slice(0, 5), argv[5], argv[6] + '\nversion = 2\nversion = 3\n', argv[7]], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] })
      }
      return base(...args)
    }
    assert.throws(() => checkMetadata(f.snapshot, [f.sentinel], f.boundary))
    assert.ok(f.stages.every((path) => !existsSync(path)))
    if (["input", "tool"].includes(kind)) assert.equal(f.calls.length, 0)
    if (!["lock"].includes(kind)) assert.ok(!f.calls.some(([, args]) => args[0] === "lock"))
  } finally { f.close() }
})

test("strict parser validates Unicode proof through the same checker boundary without a resolver", () => {
  const f = fixture(), base = f.boundary.subprocess
  try {
    f.boundary.subprocess = (exe, args, ...rest) => exe === f.snapshot.python
      ? execFileSync("python3.12", args, { encoding: "utf8" }) : base(exe, args, ...rest)
    checkMetadata(f.snapshot, [f.sentinel], f.boundary)
  } finally { f.close() }
})

for (const operation of ["--version", "lock"]) test(`continuity preflight catches original/tool mutation before ${operation}`, () => {
  for (const kind of ["input", "tool"]) {
    const f = fixture(), base = f.boundary.subprocess, inspect = f.boundary.inspect
    let toolChanged = false
    try {
      f.boundary.inspect = (s) => { if (toolChanged) throw new Error("bound_file_changed"); return inspect(s) }
      f.boundary.subprocess = (...args) => {
        const value = base(...args)
        if ((operation === "--version" && args[0] === f.snapshot.python) ||
            (operation === "lock" && args[1][0] === "--version")) {
          if (kind === "tool") toolChanged = true
          else writeFileSync(join(f.root, "pyproject.toml"), "changed")
        }
        return value
      }
      assert.throws(() => checkMetadata(f.snapshot, [f.sentinel], f.boundary))
      assert.ok(!f.calls.some(([, args]) => args[0] === operation))
      assert.ok(f.stages.every((path) => !existsSync(path)))
    } finally { f.close() }
  }
})

test("metadata policy is rejected before any normal audit/setup/scanner/runner subprocess", async () => {
  const f = fixture(), never = () => { assert.fail("authorization boundary reached") }
  try {
    for (const mode of ["audit", "setup"]) await assert.rejects(execute(mode, f.root, "a".repeat(64), f.snapshot.fingerprint, "socket", "", "", f.snapshot,
      { inspect: never, subprocess: never, auditor: never, inspectAuditor: never }), /metadata_snapshot_not_authorized/)
    assert.throws(() => discoverAuditor(f.snapshot, never), /metadata_snapshot_not_authorized/)
    assert.throws(() => captureAuditor("/unused", f.snapshot), /metadata_snapshot_not_authorized/)
    assert.throws(() => runnerCommand(f.snapshot, "audit", "unused"), /metadata_snapshot_not_authorized/)
    assert.throws(() => checkMetadata({ ...f.snapshot, policy: "virtual-wheel-only-v3" }, [], { inspect: never, subprocess: never }), /metadata_snapshot_required/)
  } finally { f.close() }
})
