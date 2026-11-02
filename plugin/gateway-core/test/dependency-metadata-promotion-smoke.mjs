// Opt-in full-plugin/native synthetic proof. Fresh random fixtures only. No installer.
import assert from "node:assert/strict"
import { spawn } from "node:child_process"
import { mkdtempSync, realpathSync, mkdirSync, writeFileSync, readFileSync, readdirSync, rmSync, existsSync, lstatSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import GatewayCorePlugin from "../dist/index.js"
import { ENV, digest, safeRead, metadataCandidate, metadataPaths, decodeMetadataContext } from "../dist/hooks/dependency-risk-guard/safety.js"
import { decodeMetadataInvocation } from "../dist/hooks/dependency-risk-guard/protocol.js"
import { createDependencyRiskGuardHook } from "../dist/hooks/dependency-risk-guard/index.js"

const selected = process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH
assert.ok(selected, "run with the documented enforced sidecar selected")
const config = JSON.parse(readFileSync(selected, "utf8"))
assert.equal(config.hooks.enabled, true); assert.deepEqual(config.hooks.disabled, []); assert.equal(config.dependencyRiskGuard.enabled, true)
const previous = Object.fromEntries(["TMPDIR", "TMP", "TEMP"].map((k) => [k, process.env[k]]))
const temporaryRoot = realpathSync(tmpdir())
const outcomes = []
let children = 0
let sdkProbes = 0
async function child(command, root, staging) {
  children++
  // Must yield to the host's private socket server; spawnSync deadlocks redemption.
  return await new Promise((resolve, reject) => {
    const p = spawn("/bin/bash", ["--noprofile", "--norc", "-c", command], {
      cwd: root, env: { ...ENV, TMPDIR: staging, TMP: staging, TEMP: staging }, stdio: ["ignore", "pipe", "pipe"],
    })
    let stdout = "", stderr = ""
    const timer = setTimeout(() => { p.kill(); reject(new Error("synthetic_child_timeout")) }, 120000)
    p.on("error", reject)
    p.stdout.on("data", (b) => { stdout += b; if (stdout.length > 8192) p.kill() })
    p.stderr.on("data", (b) => { stderr += b; if (stderr.length > 8192) p.kill() })
    p.on("close", (exit) => { clearTimeout(timer); resolve({ stdout, stderr, exit }) })
  })
}
try {
  for (const { linked, environment, probes } of [{ linked: false, environment: false, probes: true },
    ...[false, true].flatMap((linked) => [false, true].map((environment) => ({ linked, environment, probes: false })))]) {
    const base = realpathSync(mkdtempSync(join(temporaryRoot, "synthetic-metadata-promotion-")))
    const root = join(base, "source"), staging = join(base, "staging"), common = linked ? join(base, "common") : join(root, ".git")
    const git = linked ? join(base, "git-dir") : common
    const sessionID = `synthetic-metadata-${linked}-${environment}`
    let plugin
    try {
      for (const path of new Set([root, staging, common, git])) mkdirSync(path, { recursive: true })
      for (const key of Object.keys(previous)) process.env[key] = staging
      mkdirSync(join(common, "objects")); mkdirSync(join(common, "refs"))
      writeFileSync(join(common, "config"), "[core]\nrepositoryformatversion = 0\nbare = false\n")
      writeFileSync(join(git, "HEAD"), "ref: refs/heads/synthetic\n")
      if (linked) { writeFileSync(join(root, ".git"), `gitdir: ${git}\n`); writeFileSync(join(git, "commondir"), "../common\n") }
      writeFileSync(join(root, "pyproject.toml"), '[project]\nname = "synthetic-demo"\nversion = "1.0.0"\nrequires-python = ">=3.12"\ndependencies = ["idna==3.11"]\n[tool.uv]\npackage = false\n')
      writeFileSync(join(root, ".python-version"), "3.12.16\n")
      const original = Buffer.from('# Synthetic café 🧪\nversion = 1\nrevision = 3\nrequires-python = ">=3.12"\n\n[[package]]\nname = "idna"\nversion = "3.11"\nsource = { registry = "https://pypi.org/simple" }\nwheels = [{ url = "https://files.pythonhosted.org/packages/synthetic/idna-3.11-py3-none-any.whl", hash = "sha256:' + "a".repeat(64) + '", size = 1 }]\n\n[[package]]\nname = "synthetic-demo"\nversion = "1.0.0"\nsource = { editable = "." } # retain these bytes\ndependencies = [{ name = "idna" }]\n\n[package.metadata]\nrequires-dist = [{ name = "idna", specifier = "==3.11" }]\n')
      writeFileSync(join(root, "uv.lock"), original, { mode: 0o644 })
      const nonLock = ["pyproject.toml", ".python-version", ".git"].filter((name) => name !== ".git" || linked)
      const hashes = Object.fromEntries(nonLock.map((name) => [name, digest(safeRead(join(root, name)))]))
      if (environment) { mkdirSync(join(root, ".venv")); writeFileSync(join(root, ".venv", "sentinel"), "synthetic environment; preserve\n") }
      const sentinelHash = environment ? digest(safeRead(join(root, ".venv", "sentinel"))) : null
      plugin = GatewayCorePlugin({ directory: root, config: { hooks: { enabled: true, disabled: [],
        order: ["noninteractive-shell-guard", "dependency-risk-guard", "validation-evidence-ledger"] }, dependencyRiskGuard: { enabled: true } } })
      const before = async (callID, command) => {
        const input = { tool: "bash", sessionID, callID }, output = { args: { command } }
        await plugin["tool.execute.before"](input, output)
        assert.ok(output.args.command.startsWith(`OPENCODE_SESSION_ID='${sessionID}' `))
        return { input, output }
      }
      const run = async (request) => {
        const r = await child(request.output.args.command, root, staging)
        assert.equal(r.exit, 0, r.stderr)
        await plugin["tool.execute.after"]({ ...request.input, args: request.output.args }, { output: r.stdout, metadata: { exit: r.exit } })
        assert.deepEqual(readdirSync(staging), [])
        return JSON.parse(r.stdout)
      }
      if (probes) {
        // Explicit synthetic SDK/boundary probes, using actual checker frames only.
        for (const attack of ["missing-final-check", "late-command", "wrong-call", "wrong-session", "wrong-command", "string-exit", "malformed-frame",
          "compacted", "deleted", "before-error", "unrelated-bash", "normal-audit", "normal-setup", "concurrent-check", "missing-final-migrate", "cancelled-migrate", "lost-completion"]) {
          sdkProbes++
          const sid = `synthetic-sdk-${attack}`
          const hook = createDependencyRiskGuardHook({ directory: root, enabled: true, lockfilePatterns: [], commandPatterns: [] })
          const request = async (callID, command, final = true) => {
            const input = { tool: "bash", sessionID: sid, callID }, output = { args: { command: `OPENCODE_SESSION_ID='${sid}' ${command}` } }
            await hook.event("tool.execute.before", { input, output, directory: root })
            if (final) await hook.event("tool.execute.before.final", { input, output, directory: root })
            return { input, output }
          }
          const after = async (q, r, input = {}, output = {}) => hook.event("tool.execute.after", {
            input: { ...q.input, args: q.output.args, ...input }, output: { output: r.stdout, metadata: { exit: r.exit }, ...output }, directory: root,
          })
          try {
            const q = await request("check", "dependency-security check-uv-lock-virtual", attack !== "missing-final-check")
            if (attack === "late-command") {
              q.output.args.command += "; true"
              await assert.rejects(hook.event("tool.execute.before.final", { ...q, directory: root }))
            } else if (attack === "concurrent-check") {
              await assert.rejects(request("second-check", "dependency-security check-uv-lock-virtual"))
            } else {
              const r = await child(q.output.args.command, root, staging); assert.equal(r.exit, 0, r.stderr)
              if (attack === "wrong-call") await after(q, r, { callID: "wrong" })
              else if (attack === "wrong-session") {
                await after(q, r, { sessionID: "wrong" })
                await hook.event("session.deleted", { properties: { sessionID: sid } })
              } else if (attack === "wrong-command") await after(q, r, { args: { command: q.output.args.command + " " } })
              else if (attack === "string-exit") await after(q, r, {}, { metadata: { exit: "0" } })
              else if (attack === "malformed-frame") await after(q, r, {}, { output: r.stdout.replace('"v":1', '"v":1,"v":1') })
              else await after(q, r)
              if (["compacted", "deleted", "before-error"].includes(attack)) await hook.event(attack === "compacted" ? "session.compacted" : attack === "deleted" ? "session.deleted" : "tool.execute.before.error", { properties: { sessionID: sid } })
              if (attack === "unrelated-bash") await request("unrelated", "true")
              if (attack === "normal-audit" || attack === "normal-setup") await assert.rejects(request("normal", attack === "normal-audit" ? "dependency-security authorize-uv-sync-locked" : "uv sync --locked"))
              if (["missing-final-migrate", "cancelled-migrate", "lost-completion"].includes(attack)) {
                const m = await request("migrate", "dependency-security migrate-uv-lock-virtual", attack !== "missing-final-migrate")
                const invocation = decodeMetadataInvocation(/'([A-Za-z0-9_-]+)'$/.exec(m.output.args.command)[1])
                const paths = metadataPaths(decodeMetadataContext(invocation.context), invocation.nonce)
                if (attack === "cancelled-migrate") await hook.event("session.compacted", { properties: { sessionID: sid } })
                const result = await child(m.output.args.command, root, staging)
                assert.equal(result.exit, attack === "lost-completion" ? 0 : 1)
                // Lost completion after real promotion: host sees malformed frame, never grants authority.
                if (attack === "lost-completion") {
                  await after(m, result, {}, { output: "{truncated" })
                  assert.equal(digest(safeRead(join(root, "uv.lock"))), invocation.candidate)
                  await assert.rejects(request("retry", "dependency-security migrate-uv-lock-virtual"))
                  await assert.rejects(request("setup", "uv sync --locked"))
                  assert.ok(safeRead(paths.backup).equals(original))
                  for (const [name, hash] of Object.entries(hashes)) assert.equal(digest(safeRead(join(root, name))), hash)
                  assert.equal(existsSync(join(root, ".venv")), false)
                  // Fixture teardown follows this probe; never rollback a promoted source.
                  outcomes.push({ syntheticSdkProbe: "lost-completion", backupVerified: true, retryAndSetupDenied: true })
                  break
                }
                await after(m, result)
                assert.ok(safeRead(paths.backup).equals(original)); assert.equal(existsSync(paths.candidate), false)
              }
            }
            await assert.rejects(request("migrate-denied", "dependency-security migrate-uv-lock-virtual"))
            await assert.rejects(request("setup-never-executed", "uv sync --locked"))
            assert.ok(safeRead(join(root, "uv.lock")).equals(original))
          } finally { await hook.event("session.deleted", { properties: { sessionID: sid } }) }
        }
        // The lost-completion probe promoted this fixture. Preserve it until fixture teardown.
        continue
      }
      const checked = await run(await before("check-call", "dependency-security check-uv-lock-virtual"))
      assert.equal(checked.phase, "check"); assert.equal(checked.original, digest(original))
      assert.ok(safeRead(join(root, "uv.lock")).equals(original))
      const migrate = await before("migrate-call", "dependency-security migrate-uv-lock-virtual")
      const encoded = /'([A-Za-z0-9_-]+)'$/.exec(migrate.output.args.command)[1]
      const invocation = decodeMetadataInvocation(encoded), context = decodeMetadataContext(invocation.context)
      const paths = metadataPaths(context, invocation.nonce)
      assert.equal(context.common.path, common)
      const promoted = await run(migrate)
      assert.equal(promoted.phase, "migrate"); assert.equal(promoted.issuer, "check-call")
      assert.equal(promoted.candidate, checked.candidate)
      const actual = safeRead(join(root, "uv.lock"))
      assert.ok(actual.equals(metadataCandidate(original).candidate))
      assert.equal(actual.length, original.length - 1)
      assert.ok(readFileSync(paths.backup).equals(original))
      assert.equal(lstatSync(paths.namespace).mode & 0o777, 0o700)
      assert.equal(lstatSync(paths.job).mode & 0o777, 0o700)
      assert.equal(lstatSync(paths.backup).mode & 0o777, 0o600)
      assert.equal(existsSync(paths.candidate), false)
      for (const [name, hash] of Object.entries(hashes)) assert.equal(digest(safeRead(join(root, name))), hash)
      assert.equal(existsSync(join(root, ".venv")), environment)
      if (environment) assert.equal(digest(safeRead(join(root, ".venv", "sentinel"))), sentinelHash)
      // Pre-execution denials only. Never spawn setup, even as a negative probe.
      await assert.rejects(before("setup-never-executed", "uv sync --locked"))
      await assert.rejects(before("retry-never-executed", "dependency-security migrate-uv-lock-virtual"))
      assert.ok(safeRead(join(root, "uv.lock")).equals(actual)); assert.ok(readFileSync(paths.backup).equals(original))
      outcomes.push({ linked, environment, checkerCommands: 6, nativeChildren: 2, backupVerified: true,
        nonLockInputsUnchanged: true, environmentPreserved: true, setupDeniedBeforeExecution: true, retryDeniedBeforeExecution: true,
        exactInodeTransition: "host verified retained candidate descriptor at native completion", hashes: { original: checked.original, candidate: checked.candidate } })
    } finally {
      if (plugin) await plugin.event({ event: { type: "session.deleted", properties: { info: { id: sessionID } } } })
      rmSync(base, { recursive: true, force: true })
    }
  }
  console.log(JSON.stringify({ syntheticOnly: true, syntheticSdkProbes: sdkProbes, children, checkerCommands: children * 3, installers: 0,
    guarantee: "atomic replacement and recovery evidence across process failure, not power-loss durability", outcomes }, null, 2))
} finally {
  for (const [key, value] of Object.entries(previous)) { if (value === undefined) delete process.env[key]; else process.env[key] = value }
}
