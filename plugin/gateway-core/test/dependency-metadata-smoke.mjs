// Explicit opt-in only: not part of **/*.test.mjs. Synthetic inputs, no installer.
import assert from "node:assert/strict"
import { mkdtempSync, realpathSync, mkdirSync, writeFileSync, rmSync, readdirSync } from "node:fs"
import { tmpdir } from "node:os"
import { dirname, join } from "node:path"
import { captureMetadata, digest, recapture, safeRead } from "../dist/hooks/dependency-risk-guard/safety.js"
import { checkMetadata } from "../dist/hooks/dependency-risk-guard/runner.js"

const base = realpathSync(mkdtempSync(join(tmpdir(), "synthetic-metadata-smoke-")))
const root = join(base, "source"), stagingParent = join(base, "staging")
const previous = Object.fromEntries(["TMPDIR", "TMP", "TEMP"].map((name) => [name, process.env[name]]))
try {
  mkdirSync(root); mkdirSync(stagingParent)
  for (const name of Object.keys(previous)) process.env[name] = stagingParent
  // A minimal synthetic Git marker supports only read-only discovery; no git init.
  mkdirSync(join(root, ".git", "objects"), { recursive: true })
  mkdirSync(join(root, ".git", "refs"))
  writeFileSync(join(root, ".git", "HEAD"), "ref: refs/heads/synthetic\n")
  writeFileSync(join(root, ".git", "config"), "[core]\nrepositoryformatversion = 0\nbare = false\n")
  writeFileSync(join(root, "pyproject.toml"), '[project]\nname = "synthetic-demo"\nversion = "1.0.0"\nrequires-python = ">=3.12"\ndependencies = ["idna==3.11"]\n[tool.uv]\npackage = false\n')
  // Frozen, hand-authored metadata. The wheel hash is synthetic, not provenance:
  // --check validates freshness, never downloads/verifies or installs this wheel.
  writeFileSync(join(root, "uv.lock"), `# Synthetic café 🧪 — preserve all closure bytes\nversion = 1
revision = 3
requires-python = ">=3.12"

[[package]]
name = "idna"
version = "3.11"
source = { registry = "https://pypi.org/simple" }
wheels = [{ url = "https://files.pythonhosted.org/packages/synthetic/idna-3.11-py3-none-any.whl", hash = "sha256:${"a".repeat(64)}", size = 1 }]

[[package]]
name = "synthetic-demo"
version = "1.0.0"
source = { editable = "." } # this key alone may change in private staging
dependencies = [{ name = "idna" }]

[package.metadata]
requires-dist = [{ name = "idna", specifier = "==3.11" }]
`)
  writeFileSync(join(root, ".python-version"), "3.12.16\n")
  mkdirSync(join(root, ".venv"))
  const sentinel = join(root, ".venv", "synthetic-sentinel")
  writeFileSync(sentinel, "not an actual environment; must remain untouched\n")
  const sentinels = [{ path: sentinel, sha256: digest(safeRead(sentinel)) }]
  const snapshot = captureMetadata(root)
  const result = checkMetadata(snapshot, sentinels)
  const check = result.commands.find((command) => command.args[0] === "lock")
  const stage = check.args[check.args.indexOf("--project") + 1]
  assert.equal(dirname(stage), stagingParent)
  assert.deepEqual(readdirSync(stagingParent), [])
  assert.equal(recapture(snapshot).fingerprint, snapshot.fingerprint)
  assert.equal(digest(safeRead(sentinel)), sentinels[0].sha256)
  console.log(JSON.stringify({ result, tools: snapshot.executables, pythonVersion: snapshot.version,
    originalInputs: snapshot.inputs, originalInputsUnchanged: true, environmentSentinelUnchanged: true,
    isolation: { source: root, canonicalParent: stagingParent, stage, stagingCleaned: true,
      boundary: "parent/source separation and manifest/config-free ancestry rechecked before every subprocess; explicit cwd/project and bound stage identity" },
    cache: "--no-cache; temporary/cache paths confined to private staging, no dependency cache metadata used",
    guarantees: "documented offline/no-build/no-python-downloads; consistency only, not audit or artifact verification",
    tracing: "no process or network tracing collected" }, null, 2))
} finally {
  for (const [name, value] of Object.entries(previous)) {
    if (value === undefined) delete process.env[name]
    else process.env[name] = value
  }
  rmSync(base, { recursive: true, force: true })
}
