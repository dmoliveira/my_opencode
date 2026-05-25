import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

function commitAll(directory, message) {
  execSync("git add .", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
  execSync(`git commit -m ${JSON.stringify(message)}`, {
    cwd: directory,
    stdio: ["ignore", "pipe", "pipe"],
    env: {
      ...process.env,
      GIT_AUTHOR_NAME: "Test",
      GIT_AUTHOR_EMAIL: "test@example.com",
      GIT_COMMITTER_NAME: "Test",
      GIT_COMMITTER_EMAIL: "test@example.com",
    },
  })
}

function repoRoot(directory) {
  return execSync("git rev-parse --show-toplevel", {
    cwd: directory,
    stdio: ["ignore", "pipe", "pipe"],
    encoding: "utf-8",
  }).trim()
}

test("stale-path-healer rewrites missing stale workdir to the active repo root", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-stale-path-"))
  const staleWorktree = `${directory}-wt-old`
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "README.md"), "hello\n", "utf-8")
    commitAll(directory, "init")
    const root = repoRoot(directory)

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["stale-path-healer"], disabled: [] },
      },
    })

    const output = { args: { command: "git status --short --branch", workdir: staleWorktree } }
    await plugin["tool.execute.before"]({ tool: "bash", sessionID: "session-stale-path-1", directory }, output)
    assert.equal(output.args.workdir, root)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("stale-path-healer rewrites absolute file paths from stale worktrees to the active repo", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-stale-path-"))
  const staleWorktree = `${directory}-wt-old`
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    mkdirSync(join(directory, "plugin", "gateway-core", "src"), { recursive: true })
    writeFileSync(join(directory, "README.md"), "hello\n", "utf-8")
    commitAll(directory, "init")
    const root = repoRoot(directory)

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["stale-path-healer"], disabled: [] },
      },
    })

    const staleFile = join(staleWorktree, "plugin", "gateway-core", "src", "index.ts")
    const output = { args: { filePath: staleFile } }
    await plugin["tool.execute.before"]({ tool: "read", sessionID: "session-stale-path-2", directory }, output)
    assert.equal(output.args.filePath, join(root, "plugin", "gateway-core", "src", "index.ts"))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("stale-path-healer rewrites absolute patch targets from stale worktrees", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-stale-path-"))
  const staleWorktree = `${directory}-wt-old`
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    mkdirSync(join(directory, "plugin", "gateway-core", "src"), { recursive: true })
    writeFileSync(join(directory, "README.md"), "hello\n", "utf-8")
    commitAll(directory, "init")

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["stale-path-healer"], disabled: [] },
      },
    })

    const staleFile = join(staleWorktree, "plugin", "gateway-core", "src", "new.ts")
    const output = {
      args: {
        patchText: `*** Begin Patch\n*** Add File: ${staleFile}\n+export const value = 1\n*** End Patch`,
      },
    }
    await plugin["tool.execute.before"]({ tool: "apply_patch", sessionID: "session-stale-path-3", directory }, output)
    assert.match(output.args.patchText, new RegExp(directory.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))
    assert.doesNotMatch(output.args.patchText, /-wt-old/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("stale-path-healer does not rewrite unrelated absolute paths outside the active repo root", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-stale-path-"))
  const unrelated = mkdtempSync(join(tmpdir(), "gateway-stale-path-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    mkdirSync(join(directory, "plugin", "gateway-core", "src"), { recursive: true })
    writeFileSync(join(directory, "README.md"), "hello\n", "utf-8")
    commitAll(directory, "init")

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["stale-path-healer"], disabled: [] },
      },
    })

    const unrelatedFile = join(unrelated, "plugin", "gateway-core", "src", "other.ts")
    const output = { args: { filePath: unrelatedFile } }
    await plugin["tool.execute.before"]({ tool: "read", sessionID: "session-stale-path-4", directory }, output)
    assert.equal(output.args.filePath, unrelatedFile)
  } finally {
    rmSync(unrelated, { recursive: true, force: true })
    rmSync(directory, { recursive: true, force: true })
  }
})
