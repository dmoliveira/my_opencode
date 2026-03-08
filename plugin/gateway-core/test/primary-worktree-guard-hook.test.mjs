import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join, relative } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

function commitAll(directory, message) {
  execSync("git add .", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
  execSync(`git -c user.name=test -c user.email=test@example.com commit -m "${message}"`, {
    cwd: directory,
    stdio: ["ignore", "pipe", "pipe"],
  })
}

test("primary-worktree-guard blocks file edits in the primary worktree", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-primary-worktree-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "file.txt"), "v1\n", "utf-8")
    commitAll(directory, "init")
    execSync("git checkout -b feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["primary-worktree-guard"], disabled: [] },
        primaryWorktreeGuard: {
          enabled: true,
          allowedBranches: ["main", "master"],
          blockEdits: true,
          blockBranchSwitches: true,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "write", sessionID: "session-primary-edit" },
        { args: { filePath: "src/new.ts" } }
      ),
      /primary project folder/
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("primary-worktree-guard blocks switching the primary worktree onto task branches", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-primary-worktree-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "file.txt"), "v1\n", "utf-8")
    commitAll(directory, "init")

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["primary-worktree-guard"], disabled: [] },
        primaryWorktreeGuard: {
          enabled: true,
          allowedBranches: ["main", "master"],
          blockEdits: true,
          blockBranchSwitches: true,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-primary-branch-hop" },
        { args: { command: "git switch feature/foo" } }
      ),
      /Branch switching to 'feature\/foo' is blocked/
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-primary-branch-hop-abs" },
        { args: { command: "/usr/bin/git switch feature/bar" } }
      ),
      /Branch switching to 'feature\/bar' is blocked/
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-primary-branch-hop-env" },
        { args: { command: "env GIT_TRACE=1 git switch feature/baz" } }
      ),
      /Branch switching to 'feature\/baz' is blocked/
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-branch-allowed" },
      { args: { command: "git switch main" } }
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-primary-branch-reset" },
        { args: { command: "git switch -C main" } }
      ),
      /Branch switching to 'main' is blocked/
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-primary-checkout-path" },
        { args: { command: "git checkout main -- file.txt" } }
      ),
      /limited to inspection, validation, and exact default-branch sync commands/
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("primary-worktree-guard allows edits in linked worktrees", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-primary-worktree-"))
  const linked = `${directory}-linked`
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "file.txt"), "v1\n", "utf-8")
    commitAll(directory, "init")
    execSync("git checkout -b feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    execSync(`git worktree add "${linked}" main`, { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })

    const plugin = GatewayCorePlugin({
      directory: linked,
      config: {
        hooks: { enabled: true, order: ["primary-worktree-guard"], disabled: [] },
        primaryWorktreeGuard: {
          enabled: true,
          allowedBranches: ["main", "master"],
          blockEdits: true,
          blockBranchSwitches: true,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "write", sessionID: "session-linked-edit" },
      { args: { filePath: "src/new.ts" } }
    )
  } finally {
    rmSync(linked, { recursive: true, force: true })
    rmSync(directory, { recursive: true, force: true })
  }
})

test("primary-worktree-guard allows linked worktree targets even when session directory is the primary worktree", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-primary-worktree-"))
  const linked = `${directory}-linked`
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "file.txt"), "v1\n", "utf-8")
    commitAll(directory, "init")
    execSync("git checkout -b feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    execSync(`git worktree add "${linked}" main`, { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["primary-worktree-guard"], disabled: [] },
        primaryWorktreeGuard: {
          enabled: true,
          allowedBranches: ["main", "master"],
          blockEdits: true,
          blockBranchSwitches: true,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "write", sessionID: "session-primary-dir-linked-write", directory },
      { args: { filePath: join(linked, "src/new.ts") } }
    )
    await plugin["tool.execute.before"](
      { tool: "write", sessionID: "session-primary-dir-linked-write-relative", directory },
      { args: { filePath: relative(directory, join(linked, "src/new.ts")) } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-dir-linked-bash", directory },
      { args: { command: "git status --short --branch", workdir: linked } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-dir-linked-bash-relative", directory },
      { args: { command: "git status --short --branch", workdir: relative(directory, linked) } }
    )
  } finally {
    rmSync(linked, { recursive: true, force: true })
    rmSync(directory, { recursive: true, force: true })
  }
})

test("primary-worktree-guard blocks mutating bash commands in the primary worktree", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-primary-worktree-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "file.txt"), "v1\n", "utf-8")
    commitAll(directory, "init")

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["primary-worktree-guard"], disabled: [] },
        primaryWorktreeGuard: {
          enabled: true,
          allowedBranches: ["main", "master"],
          blockEdits: true,
          blockBranchSwitches: true,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-primary-bash-mutate" },
        { args: { command: "echo hi > file.txt" } }
      ),
      /limited to inspection, validation, and exact default-branch sync commands/
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-primary-gh-api" },
        { args: { command: "gh api -X POST repos/foo/bar/issues" } }
      ),
      /limited to inspection, validation, and exact default-branch sync commands/
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-primary-chain" },
        { args: { command: "git status --short --branch && echo hi > file.txt" } }
      ),
      /limited to inspection, validation, and exact default-branch sync commands/
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-primary-chain-switch" },
        { args: { command: "git switch main && git switch feature/foo" } }
      ),
      /Branch switching to 'main' is blocked/
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-primary-redirection" },
        { args: { command: "git status --short --branch > file.txt" } }
      ),
      /limited to inspection, validation, and exact default-branch sync commands/
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-bash-safe" },
      { args: { command: "git status --short --branch" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-no-pager-log-safe" },
      { args: { command: "git --no-pager log --oneline --decorate --graph -20" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-no-pager-status-safe" },
      { args: { command: "git --no-pager status --short --branch" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-env-no-pager-log-safe" },
      {
        args: {
          command:
            "CI=true GIT_TERMINAL_PROMPT=0 GIT_EDITOR=true GIT_PAGER=cat PAGER=cat GCM_INTERACTIVE=never git --no-pager log --oneline --decorate --graph -20",
        },
      }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-fetch-plain-safe" },
      { args: { command: "git fetch" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-fetch-safe" },
      { args: { command: "git fetch --prune" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-worktree-add-safe" },
      {
        args: {
          command:
            'git worktree add -b feature/test "/tmp/gateway-linked" origin/main',
        },
      }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-stash-push-safe" },
      { args: { command: 'git stash push -m "temp" -- docs/plan/docs-automation-summary.md' } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-stash-pop-safe" },
      { args: { command: "git stash pop" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-stash-list-safe" },
      { args: { command: "git stash list" } }
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
