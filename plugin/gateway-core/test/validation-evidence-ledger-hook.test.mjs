import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import {
  chmodSync,
  linkSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  statSync,
  symlinkSync,
  writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { createValidationEvidenceLedgerHook } from "../dist/hooks/validation-evidence-ledger/index.js"
import {
  captureGitStateFingerprint,
  markValidationEvidence,
  missingValidationMarkers,
  validationEvidence,
  validationEvidenceStatus,
  worktreeValidationEvidence,
} from "../dist/hooks/validation-evidence-ledger/evidence.js"

let callSequence = 0

function createGitDirectory(prefix = "gateway-validation-ledger-") {
  const directory = mkdtempSync(join(tmpdir(), prefix))
  execFileSync("git", ["init", "-q"], { cwd: directory })
  execFileSync("git", ["config", "user.email", "gateway@example.invalid"], { cwd: directory })
  execFileSync("git", ["config", "user.name", "Gateway Test"], { cwd: directory })
  writeFileSync(join(directory, ".gitignore"), ".opencode/*\n")
  writeFileSync(join(directory, "tracked.txt"), "baseline\n")
  execFileSync("git", ["add", ".gitignore", "tracked.txt"], { cwd: directory })
  execFileSync("git", ["commit", "-qm", "fixture"], { cwd: directory })
  return directory
}

function pluginFor(directory, requiredMarkers = ["test"]) {
  return GatewayCorePlugin({
    directory,
    config: {
      hooks: {
        enabled: true,
        order: ["validation-evidence-ledger", "done-proof-enforcer"],
        disabled: [],
      },
      validationEvidenceLedger: { enabled: true },
      doneProofEnforcer: {
        enabled: true,
        requiredMarkers,
        requireLedgerEvidence: true,
        allowTextFallback: false,
      },
    },
  })
}

async function executeBash(
  target,
  {
    sessionID,
    command,
    callID = `call-${++callSequence}`,
    exit = 0,
    output = "",
    includeMetadata = true,
    afterCommand,
    afterCallID,
  },
) {
  const beforeInput = { tool: "bash", sessionID, callID }
  const beforeOutput = { args: { command } }
  await target["tool.execute.before"](beforeInput, beforeOutput)
  const finalCommand = afterCommand ?? beforeOutput.args.command
  const afterOutput = includeMetadata
    ? { output, metadata: { exit, output, truncated: false } }
    : { output }
  await target["tool.execute.after"](
    {
      tool: "bash",
      sessionID,
      callID: afterCallID ?? callID,
      args: { command: finalCommand },
    },
    afterOutput,
  )
  return { callID, finalCommand, beforeOutput, afterOutput }
}

async function executeLedger(hook, directory, options) {
  const callID = options.callID ?? `call-${++callSequence}`
  await hook.event("tool.execute.before", {
    input: { tool: "bash", sessionID: options.sessionID, callID },
    output: { args: { command: options.command } },
    directory,
  })
  await hook.event("tool.execute.after", {
    input: {
      tool: "bash",
      sessionID: options.sessionID,
      callID: options.afterCallID ?? callID,
      args: { command: options.afterCommand ?? options.command },
    },
    output: options.includeMetadata === false
      ? { output: options.output ?? "" }
      : {
          output: options.output ?? "",
          metadata: {
            exit: options.exit ?? 0,
            output: options.output ?? "",
            truncated: false,
          },
        },
    directory,
  })
}

test("validation evidence records authoritative exit-zero checks in schema v2", async () => {
  const directory = createGitDirectory()
  try {
    const plugin = pluginFor(directory, ["lint", "test", "build"])
    await executeBash(plugin, { sessionID: "session-authoritative", command: "npm run lint" })
    await executeBash(plugin, { sessionID: "session-authoritative", command: "npm test", output: "ok" })
    await executeBash(plugin, { sessionID: "session-authoritative", command: "npm run build" })

    assert.deepEqual(
      missingValidationMarkers("session-authoritative", ["lint", "test", "build"], directory),
      [],
    )
    assert.equal(validationEvidence("session-authoritative", directory).test, true)
    const path = join(directory, ".opencode", "runtime", "validation-evidence.json")
    const persisted = JSON.parse(readFileSync(path, "utf8"))
    const fingerprint = captureGitStateFingerprint(directory)
    assert.equal(persisted.version, 2)
    assert.equal(statSync(path).mode & 0o777, 0o600)
    assert.equal(statSync(join(directory, ".opencode", "runtime")).mode & 0o777, 0o700)
    assert.equal(
      persisted.worktrees[fingerprint.root].fingerprint.digest,
      fingerprint.digest,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("validation evidence requires call correlation, final command, and numeric exit", async () => {
  const directory = createGitDirectory()
  try {
    const hook = createValidationEvidenceLedgerHook({ directory, enabled: true })
    await executeLedger(hook, directory, {
      sessionID: "session-text-only",
      command: "npm test",
      includeMetadata: false,
      output: "all tests passed",
    })
    await executeLedger(hook, directory, {
      sessionID: "session-nonzero",
      command: "npm test",
      exit: 1,
      output: "0 failed",
    })
    await executeLedger(hook, directory, {
      sessionID: "session-call-mismatch",
      command: "npm test",
      afterCallID: "different-call",
    })
    await executeLedger(hook, directory, {
      sessionID: "session-command-mismatch",
      command: "npm test",
      afterCommand: "git status",
    })
    for (const sessionID of [
      "session-text-only",
      "session-nonzero",
      "session-call-mismatch",
      "session-command-mismatch",
    ]) {
      assert.equal(validationEvidence(sessionID, directory).test, false)
    }
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("empty stdout with authoritative exit zero is valid", async () => {
  const directory = createGitDirectory()
  try {
    const plugin = pluginFor(directory)
    await executeBash(plugin, {
      sessionID: "session-empty-output",
      command: "node --test test/example.test.mjs",
      output: "",
    })
    assert.equal(validationEvidence("session-empty-output", directory).test, true)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("ledger observes the final command after shell rewrites", async () => {
  const directory = createGitDirectory()
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["validation-evidence-ledger", "noninteractive-shell-guard"],
          disabled: [],
        },
        validationEvidenceLedger: { enabled: true },
        noninteractiveShellGuard: { enabled: true },
      },
    })
    const run = await executeBash(plugin, {
      sessionID: "session-rewritten-command",
      command: "npm test",
    })
    assert.match(run.finalCommand, /^OPENCODE_SESSION_ID=/)
    assert.equal(validationEvidence("session-rewritten-command", directory).test, true)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("overlapping calls correlate only by call ID", async () => {
  const directory = createGitDirectory()
  try {
    const hook = createValidationEvidenceLedgerHook({ directory, enabled: true })
    await hook.event("tool.execute.before", {
      input: { tool: "bash", sessionID: "session-overlap", callID: "lint-call" },
      output: { args: { command: "npm run lint" } },
      directory,
    })
    await hook.event("tool.execute.before", {
      input: { tool: "bash", sessionID: "session-overlap", callID: "test-call" },
      output: { args: { command: "npm test" } },
      directory,
    })
    await hook.event("tool.execute.after", {
      input: { tool: "bash", sessionID: "session-overlap", callID: "test-call", args: { command: "npm test" } },
      output: { output: "", metadata: { exit: 0 } },
      directory,
    })
    await hook.event("tool.execute.after", {
      input: { tool: "bash", sessionID: "session-overlap", callID: "lint-call", args: { command: "npm run lint" } },
      output: { output: "", metadata: { exit: 0 } },
      directory,
    })
    assert.deepEqual(missingValidationMarkers("session-overlap", ["lint", "test"], directory), [])
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("repository changes during validation discard evidence", async () => {
  const directory = createGitDirectory()
  try {
    const hook = createValidationEvidenceLedgerHook({ directory, enabled: true })
    await hook.event("tool.execute.before", {
      input: { tool: "bash", sessionID: "session-mutated", callID: "mutating-call" },
      output: { args: { command: "npm test" } },
      directory,
    })
    writeFileSync(join(directory, "tracked.txt"), "changed during validation\n")
    await hook.event("tool.execute.after", {
      input: { tool: "bash", sessionID: "session-mutated", callID: "mutating-call", args: { command: "npm test" } },
      output: { output: "", metadata: { exit: 0 } },
      directory,
    })
    assert.equal(validationEvidence("session-mutated", directory).test, false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("worktree fallback is valid only for the byte-identical repository state", async () => {
  const directory = createGitDirectory()
  try {
    const plugin = pluginFor(directory)
    await executeBash(plugin, { sessionID: "session-origin", command: "npm test" })
    assert.deepEqual(validationEvidenceStatus("session-new", ["test"], directory), {
      missing: [],
      source: "worktree",
    })
    writeFileSync(join(directory, "tracked.txt"), "dirty\n")
    assert.deepEqual(validationEvidenceStatus("session-new", ["test"], directory), {
      missing: ["test"],
      source: "none",
    })
    writeFileSync(join(directory, "tracked.txt"), "baseline\n")
    assert.deepEqual(validationEvidenceStatus("session-new", ["test"], directory), {
      missing: [],
      source: "worktree",
    })
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("git-state fingerprint covers staged, unstaged, untracked, executable, and symlink state", () => {
  const directory = createGitDirectory()
  try {
    const baseline = captureGitStateFingerprint(directory)
    assert.ok(baseline)
    writeFileSync(join(directory, "tracked.txt"), "unstaged\n")
    assert.notEqual(captureGitStateFingerprint(directory).digest, baseline.digest)
    execFileSync("git", ["checkout", "--", "tracked.txt"], { cwd: directory })
    writeFileSync(join(directory, "staged.txt"), "staged\n")
    execFileSync("git", ["add", "staged.txt"], { cwd: directory })
    assert.notEqual(captureGitStateFingerprint(directory).digest, baseline.digest)
    execFileSync("git", ["reset", "-q", "HEAD", "staged.txt"], { cwd: directory })
    rmSync(join(directory, "staged.txt"))
    writeFileSync(join(directory, "untracked.txt"), "one\n")
    const untracked = captureGitStateFingerprint(directory)
    assert.notEqual(untracked.digest, baseline.digest)
    chmodSync(join(directory, "untracked.txt"), 0o755)
    assert.notEqual(captureGitStateFingerprint(directory).digest, untracked.digest)
    rmSync(join(directory, "untracked.txt"))
    symlinkSync("tracked.txt", join(directory, "link.txt"))
    assert.notEqual(captureGitStateFingerprint(directory).digest, baseline.digest)
    assert.equal(lstatSync(join(directory, "link.txt")).isSymbolicLink(), true)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session compaction clears memory while exact worktree evidence remains", async () => {
  const directory = createGitDirectory()
  try {
    const plugin = pluginFor(directory)
    await executeBash(plugin, { sessionID: "session-compacted", command: "npm test" })
    await plugin.event({ event: { type: "session.compacted", properties: { info: { id: "session-compacted" } } } })
    assert.equal(validationEvidence("session-compacted", directory).test, false)
    assert.deepEqual(validationEvidenceStatus("session-compacted", ["test"], directory), {
      missing: [],
      source: "worktree",
    })
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("LLM classification remains telemetry-only", async () => {
  const directory = createGitDirectory()
  let decisionCalls = 0
  try {
    const hook = createValidationEvidenceLedgerHook({
      directory,
      enabled: true,
      decisionRuntime: {
        config: {
          enabled: true,
          mode: "assist",
          command: "opencode",
          model: "openai/gpt-5.4-mini",
          timeoutMs: 1000,
          maxPromptChars: 200,
          maxContextChars: 200,
          enableCache: true,
          cacheTtlMs: 10000,
          maxCacheEntries: 8,
        },
        decide: async () => {
          decisionCalls += 1
          return {
            mode: "assist",
            accepted: true,
            char: "T",
            raw: "T",
            durationMs: 1,
            model: "openai/gpt-5.4-mini",
            templateId: "validation-command-classifier-v1",
            meaning: "test",
          }
        },
      },
    })
    await executeLedger(hook, directory, {
      sessionID: "session-llm-telemetry",
      command: "./scripts/custom-check api smoke",
    })
    assert.equal(decisionCalls, 1)
    assert.equal(validationEvidence("session-llm-telemetry", directory).test, false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("old or permissive persisted evidence is untrusted and replaced securely", () => {
  const directory = createGitDirectory()
  try {
    const runtime = join(directory, ".opencode", "runtime")
    mkdirSync(runtime, { recursive: true, mode: 0o700 })
    chmodSync(runtime, 0o700)
    const path = join(runtime, "validation-evidence.json")
    writeFileSync(path, JSON.stringify({ sessions: {}, worktrees: { [directory]: { test: true } } }))
    chmodSync(path, 0o644)
    assert.equal(worktreeValidationEvidence(directory).test, false)
    assert.equal(markValidationEvidence("session-upgrade", ["test"], directory).test, true)
    assert.equal(statSync(path).mode & 0o777, 0o600)
    assert.equal(JSON.parse(readFileSync(path, "utf8")).version, 2)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("symlink and hard-link evidence targets fail closed without mutating victims", () => {
  for (const targetKind of ["symlink", "hardlink"]) {
    const directory = createGitDirectory(`gateway-validation-${targetKind}-`)
    try {
      const runtime = join(directory, ".opencode", "runtime")
      mkdirSync(runtime, { recursive: true, mode: 0o700 })
      chmodSync(runtime, 0o700)
      const victim = join(directory, "victim.json")
      writeFileSync(victim, "ORIGINAL\n")
      const target = join(runtime, "validation-evidence.json")
      if (targetKind === "symlink") {
        symlinkSync(victim, target)
      } else {
        linkSync(victim, target)
      }
      assert.throws(() => markValidationEvidence(`session-${targetKind}`, ["test"], directory))
      assert.equal(readFileSync(victim, "utf8"), "ORIGINAL\n")
      assert.equal(validationEvidence(`session-${targetKind}`, directory).test, false)
    } finally {
      rmSync(directory, { recursive: true, force: true })
    }
  }
})
