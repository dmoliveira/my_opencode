// Explicit non-installing integration smoke; network/scanner cache required. Not a unit-suite gate.
import assert from "node:assert/strict"
import { execFileSync, spawnSync } from "node:child_process"
import { mkdtempSync, realpathSync, writeFileSync, readFileSync, rmSync, existsSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { createDependencyRiskGuardHook } from "../dist/hooks/dependency-risk-guard/index.js"
import { ENV } from "../dist/hooks/dependency-risk-guard/safety.js"

const root = realpathSync(mkdtempSync(join(tmpdir(), "synthetic-authorization-smoke-")))
try {
  execFileSync("/usr/bin/git", ["init", "-q", root])
  writeFileSync(join(root, ".python-version"), "3.12.16\n")
  writeFileSync(join(root, "pyproject.toml"), `[project]
name = "synthetic-authorization-smoke"
version = "0.0.1"
requires-python = ">=3.12,<3.13"
dependencies = ["idna==3.20"]
[dependency-groups]
dev = ["colorama==0.4.6; sys_platform == 'win32'"]
[tool.uv]
package = false
`)
  // Generate synthetic lock metadata only. Never venv, sync, install or tool preparation here.
  execFileSync("uv", ["lock", "--no-config", "--no-python-downloads", "--python", "3.12.16"], { cwd: root, env: ENV, timeout: 60_000, stdio: "pipe" })
  const hook = createDependencyRiskGuardHook({ directory: root, enabled: true, lockfilePatterns: [], commandPatterns: [] })
  const input = { tool: "bash", sessionID: "synthetic-smoke", callID: "actual-audit" }
  const output = { args: { command: "dependency-security authorize-uv-sync-locked" } }
  await hook.event("tool.execute.before", { input, output })
  await hook.event("tool.execute.before.final", { input, output })
  const result = spawnSync("/bin/bash", ["--noprofile", "--norc", "-c", output.args.command], { cwd: root, env: ENV, timeout: 180_000, encoding: "utf8", maxBuffer: 4096 })
  assert.equal(result.status, 0, result.stderr || result.error?.message)
  const report = JSON.parse(result.stdout)
  assert.equal(report.packages, 1) // Windows-only dev dependency is not applicable on this host.
  await hook.event("tool.execute.after", { input: { ...input, args: output.args }, output: { output: result.stdout, metadata: { exit: result.status } } })
  const setupInput = { tool: "bash", sessionID: input.sessionID, callID: "setup-never-executed" }
  const setupOutput = { args: { command: "uv sync --locked" } }
  await hook.event("tool.execute.before", { input: setupInput, output: setupOutput })
  assert.match(setupOutput.args.command, /'setup'/)
  await hook.event("tool.execute.before.final", { input: setupInput, output: setupOutput })
  // Permission/sandbox failure simulation: discard setup, consume the permit, close its socket.
  await hook.event("tool.execute.before.error", { input: setupInput, output: setupOutput })
  await assert.rejects(hook.event("tool.execute.before", { input: { ...setupInput, callID: "replay" }, output: { args: { command: "uv sync --locked" } } }))
  // A later before-hook rewrite invalidates the binding before anything runs.
  const mutatedInput = { ...input, callID: "late-mutation-never-executed" }
  const mutatedOutput = { args: { command: "dependency-security authorize-uv-sync-locked" } }
  await hook.event("tool.execute.before", { input: mutatedInput, output: mutatedOutput })
  mutatedOutput.args.command += "; true"
  await assert.rejects(hook.event("tool.execute.before.final", { input: mutatedInput, output: mutatedOutput }), /final_command_mismatch/)
  await assert.rejects(hook.event("tool.execute.before", { input: { ...setupInput, callID: "after-mutation" }, output: { args: { command: "uv sync --locked" } } }))
  const staleInput = { ...input, callID: "stale-input-never-executed" }
  const staleOutput = { args: { command: "dependency-security authorize-uv-sync-locked" } }
  await hook.event("tool.execute.before", { input: staleInput, output: staleOutput })
  const manifest = readFileSync(join(root, "pyproject.toml"))
  writeFileSync(join(root, "pyproject.toml"), manifest.toString() + "\n# changed after binding\n")
  await assert.rejects(hook.event("tool.execute.before.final", { input: staleInput, output: staleOutput }), /final_command_mismatch/)
  writeFileSync(join(root, "pyproject.toml"), manifest)
  await assert.rejects(hook.event("tool.execute.before", { input: { ...setupInput, callID: "after-stale-input" }, output: { args: { command: "uv sync --locked" } } }))
  assert.equal(existsSync(join(root, ".venv")), false)
  console.log("dependency_authorization_noninstalling_smoke_passed")
} finally { rmSync(root, { recursive: true, force: true }) }
