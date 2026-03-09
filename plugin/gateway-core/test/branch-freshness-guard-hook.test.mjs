import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

function commitAll(directory, message) {
  execSync("git add .", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
  execSync(`git -c user.name=test -c user.email=test@example.com commit -m \"${message}\"`, {
    cwd: directory,
    stdio: ["ignore", "pipe", "pipe"],
  })
}

test("branch-freshness-guard blocks PR create when branch is behind base", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-branch-freshness-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "file.txt"), "v1\n", "utf-8")
    commitAll(directory, "init")
    execSync("git checkout -b feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    execSync("git checkout main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "file.txt"), "v2\n", "utf-8")
    commitAll(directory, "advance-main")
    execSync("git checkout feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["branch-freshness-guard"],
          disabled: ["pr-readiness-guard", "pr-body-evidence-guard", "primary-worktree-guard"],
        },
        branchFreshnessGuard: {
          enabled: true,
          baseRef: "main",
          maxBehind: 0,
          enforceOnPrCreate: true,
          enforceOnPrMerge: true,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-branch-freshness" },
        { args: { command: "gh pr create --title test --body test" } },
      ),
      /behind 'main' by 1 commit/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("branch-freshness-guard allows PR create within behind budget", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-branch-freshness-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "file.txt"), "v1\n", "utf-8")
    commitAll(directory, "init")
    execSync("git checkout -b feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    execSync("git checkout main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "file.txt"), "v2\n", "utf-8")
    commitAll(directory, "advance-main")
    execSync("git checkout feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["branch-freshness-guard"],
          disabled: ["pr-readiness-guard", "pr-body-evidence-guard", "primary-worktree-guard"],
        },
        branchFreshnessGuard: {
          enabled: true,
          baseRef: "main",
          maxBehind: 1,
          enforceOnPrCreate: true,
          enforceOnPrMerge: true,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-branch-freshness" },
      { args: { command: "gh pr create --title test --body test" } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("branch-freshness-guard skips when base ref is unavailable", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-branch-freshness-"))
  try {
    execSync("git init -b feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["branch-freshness-guard"],
          disabled: ["pr-readiness-guard", "pr-body-evidence-guard", "primary-worktree-guard"],
        },
        branchFreshnessGuard: {
          enabled: true,
          baseRef: "main",
          maxBehind: 0,
          enforceOnPrCreate: true,
          enforceOnPrMerge: true,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-branch-freshness" },
      { args: { command: "gh pr create --title test --body test" } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("branch-freshness-guard applies gh api PR creation to freshness checks", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-branch-freshness-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "file.txt"), "v1\n", "utf-8")
    commitAll(directory, "init")
    execSync("git checkout -b feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    execSync("git checkout main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "file.txt"), "v2\n", "utf-8")
    commitAll(directory, "advance-main")
    execSync("git checkout feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["branch-freshness-guard"],
          disabled: ["pr-readiness-guard", "pr-body-evidence-guard", "primary-worktree-guard"],
        },
        branchFreshnessGuard: {
          enabled: true,
          baseRef: "main",
          maxBehind: 0,
          enforceOnPrCreate: true,
          enforceOnPrMerge: true,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-branch-freshness-api" },
        { args: { command: "gh api repos/foo/bar/pulls -X POST -f title=test -f head=feature -f base=main" } },
      ),
      /behind 'main' by 1 commit/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("branch-freshness-guard applies gh api PR merge to freshness checks", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-branch-freshness-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "file.txt"), "v1\n", "utf-8")
    commitAll(directory, "init")
    execSync("git checkout -b feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    execSync("git checkout main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "file.txt"), "v2\n", "utf-8")
    commitAll(directory, "advance-main")
    execSync("git checkout feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["branch-freshness-guard"],
          disabled: ["pr-readiness-guard", "pr-body-evidence-guard", "primary-worktree-guard"],
        },
        branchFreshnessGuard: {
          enabled: true,
          baseRef: "main",
          maxBehind: 0,
          enforceOnPrCreate: true,
          enforceOnPrMerge: true,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-branch-freshness-merge-api" },
        { args: { command: "gh api repos/foo/bar/pulls/10/merge -X PUT -f merge_method=merge" } },
      ),
      /behind 'main' by 1 commit/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("branch-freshness-guard ignores merge text inside PR create bodies", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-branch-freshness-"))
  try {
    execSync("git init -b feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["branch-freshness-guard"],
          disabled: ["pr-readiness-guard", "pr-body-evidence-guard", "primary-worktree-guard"],
        },
        branchFreshnessGuard: {
          enabled: true,
          baseRef: "main",
          maxBehind: 0,
          enforceOnPrCreate: false,
          enforceOnPrMerge: true,
        },
      },
    })

    const command = `gh pr ${"create"} --title test --body "Run \`gh pr ${"merge"} --delete-branch\` after checks pass."`
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-branch-freshness-false-positive" },
      { args: { command } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
