import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("pr-readiness-guard blocks PR creation when worktree is dirty", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-pr-readiness-"))
  try {
    execSync("git init -b feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "scratch.txt"), "dirty\n", "utf-8")

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["pr-readiness-guard"],
          disabled: [],
        },
        prReadinessGuard: {
          enabled: true,
          requireCleanWorktree: true,
          requireValidationEvidence: false,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-pr-dirty" },
        { args: { command: "gh pr create --title x --body y" } },
      ),
      /Worktree is dirty/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("pr-readiness-guard blocks PR creation when validation evidence is missing", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-pr-readiness-"))
  try {
    execSync("git init -b feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["pr-readiness-guard"],
          disabled: [],
        },
        doneProofEnforcer: {
          enabled: true,
          requiredMarkers: ["lint"],
          requireLedgerEvidence: true,
          allowTextFallback: false,
        },
        prReadinessGuard: {
          enabled: true,
          requireCleanWorktree: false,
          requireValidationEvidence: true,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-pr-validation" },
        { args: { command: "gh pr create --title x --body y" } },
      ),
      /Missing validation evidence/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("pr-readiness-guard applies gh api PR creation to the same readiness checks", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-pr-readiness-"))
  try {
    execSync("git init -b feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "scratch.txt"), "dirty\n", "utf-8")

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["pr-readiness-guard"],
          disabled: [],
        },
        prReadinessGuard: {
          enabled: true,
          requireCleanWorktree: true,
          requireValidationEvidence: false,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-pr-api-dirty" },
        { args: { command: "gh api repos/foo/bar/pulls -X POST -f title=x -f head=feature -f base=main" } },
      ),
      /Worktree is dirty/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("pr-readiness-guard accepts validation evidence from another session in the same worktree", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-pr-readiness-"))
  try {
    execSync("git init -b feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["validation-evidence-ledger", "pr-readiness-guard"],
          disabled: [],
        },
        validationEvidenceLedger: {
          enabled: true,
        },
        doneProofEnforcer: {
          enabled: true,
          requiredMarkers: ["test"],
          requireLedgerEvidence: true,
          allowTextFallback: false,
        },
        prReadinessGuard: {
          enabled: true,
          requireCleanWorktree: false,
          requireValidationEvidence: true,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-pr-validation-a" },
      { args: { command: "node --test plugin/gateway-core/test/pr-readiness-guard-hook.test.mjs" } },
    )
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-pr-validation-a" },
      { output: "tests passed" },
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-pr-validation-b" },
      { args: { command: "gh pr create --title x --body y" } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
