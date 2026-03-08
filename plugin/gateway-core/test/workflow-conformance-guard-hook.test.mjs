import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

function commitAll(directory, message) {
  execSync("git add .", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
  execSync(`git -c user.name=test -c user.email=test@example.com commit -m "${message}"`, {
    cwd: directory,
    stdio: ["ignore", "pipe", "pipe"],
  })
}

test("workflow-conformance-guard blocks git commit on protected branch", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-guard-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["workflow-conformance-guard"], disabled: [] },
        workflowConformanceGuard: {
          enabled: true,
          protectedBranches: ["main"],
          blockEditsOnProtectedBranches: true,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-workflow" },
        { args: { command: "git commit -m \"msg\"" } },
      ),
      /protected branch/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("workflow-conformance-guard blocks file edits on protected branch", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-guard-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["workflow-conformance-guard"], disabled: [] },
        workflowConformanceGuard: {
          enabled: true,
          protectedBranches: ["main"],
          blockEditsOnProtectedBranches: true,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "write", sessionID: "session-workflow-edit" },
        { args: { filePath: "src/new.ts" } },
      ),
      /File edits are blocked on protected branch/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("workflow-conformance-guard allows safe inspection bash commands on protected branches", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-guard-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["workflow-conformance-guard"], disabled: [] },
        workflowConformanceGuard: {
          enabled: true,
          protectedBranches: ["main"],
          blockEditsOnProtectedBranches: true,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-safe" },
      { args: { command: "git status --short --branch" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-no-pager-log-safe" },
      { args: { command: "git --no-pager log --oneline --decorate --graph -20" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-no-pager-status-safe" },
      { args: { command: "git --no-pager status --short --branch" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-fetch-safe" },
      { args: { command: "git fetch" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-fetch-prune-safe" },
      { args: { command: "git fetch --prune" } }
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("workflow-conformance-guard still blocks env-prefixed git mutation commands", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-guard-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["workflow-conformance-guard"], disabled: [] },
        workflowConformanceGuard: {
          enabled: true,
          protectedBranches: ["main"],
          blockEditsOnProtectedBranches: true,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-workflow-env" },
        { args: { command: "env GIT_TRACE=1 git commit -m \"msg\"" } }
      ),
      /protected branch/
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("workflow-conformance-guard blocks mutating bash commands on protected branches", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-guard-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["workflow-conformance-guard"], disabled: [] },
        workflowConformanceGuard: {
          enabled: true,
          protectedBranches: ["main"],
          blockEditsOnProtectedBranches: true,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-workflow-bash-mutate" },
        { args: { command: "echo hi > file.txt" } }
      ),
      /limited to inspection, validation, and exact sync commands/
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-workflow-gh-api" },
        { args: { command: "gh api -X POST repos/foo/bar/issues" } }
      ),
      /limited to inspection, validation, and exact sync commands/
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-workflow-chain" },
        { args: { command: "git status --short --branch && echo hi > file.txt" } }
      ),
      /limited to inspection, validation, and exact sync commands/
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-workflow-refspec-pull" },
        { args: { command: "git pull --rebase origin feature/x" } }
      ),
      /limited to inspection, validation, and exact sync commands/
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-workflow-fetch-refspec" },
        { args: { command: "git fetch origin +feature/x:main" } }
      ),
      /limited to inspection, validation, and exact sync commands/
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-workflow-redirection" },
        { args: { command: "git status --short --branch > file.txt" } }
      ),
      /limited to inspection, validation, and exact sync commands/
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("workflow-conformance-guard blocks edits in linked worktrees on protected branches", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-guard-"))
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
        hooks: {
          enabled: true,
          order: ["primary-worktree-guard", "workflow-conformance-guard"],
          disabled: [],
        },
        primaryWorktreeGuard: {
          enabled: true,
          allowedBranches: ["main", "master"],
          blockEdits: true,
          blockBranchSwitches: true,
        },
        workflowConformanceGuard: {
          enabled: true,
          protectedBranches: ["main"],
          blockEditsOnProtectedBranches: true,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "write", sessionID: "session-linked-protected-edit" },
        { args: { filePath: "src/new.ts" } }
      ),
      /File edits are blocked on protected branch/
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-linked-protected-sync" },
      { args: { command: "git pull --rebase" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-linked-protected-fetch" },
      { args: { command: "git fetch --prune" } }
    )
  } finally {
    rmSync(linked, { recursive: true, force: true })
    rmSync(directory, { recursive: true, force: true })
  }
})
