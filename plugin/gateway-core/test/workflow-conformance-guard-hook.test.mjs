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

test("workflow-conformance-guard reroutes git commit on protected branch", async () => {
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

    const payload = { args: { command: "git commit -m \"msg\"" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow" },
      payload,
    )
    assert.match(payload.args.command, /python3 ".*scripts\/worktree_helper_command\.py" maintenance --directory/)
    assert.match(payload.args.command, /--command "git commit -m \\\"msg\\\"" --json/)
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
      { tool: "bash", sessionID: "session-workflow-rtk-safe" },
      { args: { command: "rtk git status --short --branch" } }
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
      { tool: "bash", sessionID: "session-workflow-worktree-list-safe" },
      { args: { command: `git -C "${directory}" worktree list` } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-worktree-list-abs-safe" },
      { args: { command: `/usr/bin/git -C "${directory}" worktree list` } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-env-no-pager-log-safe" },
      {
        args: {
          command:
            "CI=true GIT_TERMINAL_PROMPT=0 GIT_EDITOR=true GIT_PAGER=cat PAGER=cat GCM_INTERACTIVE=never git --no-pager log --oneline --decorate --graph -20",
        },
      }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-fetch-safe" },
      { args: { command: "git fetch" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-fetch-prune-safe" },
      { args: { command: "git fetch --prune" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-worktree-add-safe" },
      {
        args: {
          command:
            'git worktree add -b feature/test "/tmp/gateway-linked" origin/main',
        },
      }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-stash-push-safe" },
      { args: { command: 'git stash push -m "temp" -- docs/plan/docs-automation-summary.md' } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-stash-pop-safe" },
      { args: { command: "git stash pop" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-stash-list-safe" },
      { args: { command: "git stash list" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-safe-chain" },
      { args: { command: "git stash pop && git status --short --branch" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-restore-safe" },
      { args: { command: "git restore --source main -- docs/plan/docs-automation-summary.md" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-checkout-restore-safe" },
      { args: { command: "git checkout main -- docs/plan/docs-automation-summary.md" } }
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("workflow-conformance-guard reroutes env-prefixed git mutation commands", async () => {
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

    const payload = { args: { command: "env GIT_TRACE=1 git commit -m \"msg\"" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-env" },
      payload
    )
    assert.match(payload.args.command, /python3 ".*scripts\/worktree_helper_command\.py" maintenance --directory/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("workflow-conformance-guard reroutes wrapped rtk git commit on protected branch", async () => {
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

    const payload = { args: { command: 'rtk git commit -m "msg"' } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-rtk-commit" },
      payload,
    )
    assert.match(payload.args.command, /python3 ".*scripts\/worktree_helper_command\.py" maintenance --directory/)
    assert.match(payload.args.command, /--command "rtk git commit -m \\\"msg\\\"" --json/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("workflow-conformance-guard allows apply_patch targeting a linked worktree from protected main", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-guard-"))
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

    await plugin["tool.execute.before"](
      { tool: "apply_patch", sessionID: "session-protected-dir-linked-patch", directory },
      {
        args: {
          patchText: `*** Begin Patch
*** Add File: ${join(linked, "src/new.ts")}
+export const value = 1
*** End Patch`,
        },
      }
    )
    await plugin["tool.execute.before"](
      { tool: "apply_patch", sessionID: "session-protected-dir-linked-patch-relative", directory },
      {
        args: {
          patchText: `*** Begin Patch
*** Add File: ${relative(directory, join(linked, "src/relative.ts"))}
+export const relativeValue = 1
*** End Patch`,
        },
      }
    )
  } finally {
    rmSync(linked, { recursive: true, force: true })
    rmSync(directory, { recursive: true, force: true })
  }
})

test("workflow-conformance-guard reroutes mutating bash commands on protected branches", async () => {
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

    const mutatePayload = { args: { command: "echo hi > file.txt" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-bash-mutate" },
      mutatePayload
    )
    assert.match(mutatePayload.args.command, /python3 ".*scripts\/worktree_helper_command\.py" maintenance --directory/)
    assert.match(mutatePayload.args.command, /--command "echo hi > file\.txt" --json/)

    const ghPayload = { args: { command: "gh api -X POST repos/foo/bar/issues" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-gh-api" },
      ghPayload
    )
    assert.match(ghPayload.args.command, /python3 ".*scripts\/worktree_helper_command\.py" maintenance --directory/)

    const chainPayload = { args: { command: "git status --short --branch && echo hi > file.txt" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-chain" },
      chainPayload
    )
    assert.match(chainPayload.args.command, /--command "git status --short --branch && echo hi > file\.txt" --json/)

    const pullPayload = { args: { command: "git pull --rebase origin feature/x" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-refspec-pull" },
      pullPayload
    )
    assert.match(pullPayload.args.command, /python3 ".*scripts\/worktree_helper_command\.py" maintenance --directory/)

    const fetchPayload = { args: { command: "git fetch origin +feature/x:main" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-fetch-refspec" },
      fetchPayload
    )
    assert.match(fetchPayload.args.command, /python3 ".*scripts\/worktree_helper_command\.py" maintenance --directory/)

    const redirectPayload = { args: { command: "git status --short --branch > file.txt" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-redirection" },
      redirectPayload
    )
    assert.match(redirectPayload.args.command, /python3 ".*scripts\/worktree_helper_command\.py" maintenance --directory/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("workflow-conformance-guard allows linked worktree edits even when the linked branch is main", async () => {
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

    await plugin["tool.execute.before"](
      { tool: "write", sessionID: "session-linked-protected-edit" },
      { args: { filePath: "src/new.ts" } }
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

test("workflow-conformance-guard allows linked worktree targets when session directory is protected main", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-guard-"))
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

    await plugin["tool.execute.before"](
      { tool: "write", sessionID: "session-protected-dir-linked-write", directory },
      { args: { filePath: join(linked, "src/new.ts") } }
    )
    await plugin["tool.execute.before"](
      { tool: "write", sessionID: "session-protected-dir-linked-write-relative", directory },
      { args: { filePath: relative(directory, join(linked, "src/new.ts")) } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-protected-dir-linked-bash", directory },
      { args: { command: "git status --short --branch", workdir: linked } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-protected-dir-linked-bash-relative", directory },
      { args: { command: "git status --short --branch", workdir: relative(directory, linked) } }
    )
  } finally {
    rmSync(linked, { recursive: true, force: true })
    rmSync(directory, { recursive: true, force: true })
  }
})
