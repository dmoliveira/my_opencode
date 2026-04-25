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

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-primary-branch-hop-rtk" },
        { args: { command: "rtk git switch feature/qux" } }
      ),
      /Branch switching to 'feature\/qux' is blocked/
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-branch-allowed" },
      { args: { command: "git switch main" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-branch-allowed-rtk" },
      { args: { command: "rtk git switch main" } }
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-primary-branch-reset" },
        { args: { command: "git switch -C main" } }
      ),
      /Branch switching to 'main' is blocked/
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-checkout-path" },
      { args: { command: "git checkout main -- file.txt" } }
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

test("primary-worktree-guard allows apply_patch targeting a linked worktree from the primary worktree", async () => {
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
      { tool: "apply_patch", sessionID: "session-primary-dir-linked-patch", directory },
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
      { tool: "apply_patch", sessionID: "session-primary-dir-linked-patch-relative", directory },
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

test("primary-worktree-guard reroutes mutating bash commands in the primary worktree", async () => {
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

    const mutatePayload = { args: { command: "echo hi > file.txt" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-bash-mutate" },
      mutatePayload
    )
    assert.match(mutatePayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)

    const ghPayload = { args: { command: "gh api -X POST repos/foo/bar/issues" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-gh-api" },
      ghPayload
    )
    assert.match(ghPayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)

    const chainPayload = { args: { command: "git status --short --branch && echo hi > file.txt" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-chain" },
      chainPayload
    )
    assert.match(chainPayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-primary-chain-switch" },
        { args: { command: "git switch main && git switch feature/foo" } }
      ),
      /Branch switching to 'main' is blocked/
    )

    const redirectPayload = { args: { command: "git status --short --branch > file.txt" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-redirection" },
      redirectPayload
    )
    assert.match(redirectPayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)

    const commandSubstitutionPayload = {
      args: { command: 'git status --short --branch "$(touch /tmp/pwn)"' },
    }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-command-substitution" },
      commandSubstitutionPayload
    )
    assert.match(commandSubstitutionPayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)
    assert.match(commandSubstitutionPayload.args.command, /--command 'git status --short --branch "\$\(touch \/tmp\/pwn\)"' --json/)

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
      { tool: "bash", sessionID: "session-primary-worktree-list-safe" },
      { args: { command: `git -C "${directory}" worktree list` } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-worktree-list-abs-safe" },
      { args: { command: `/usr/bin/git -C "${directory}" worktree list` } }
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
      { tool: "bash", sessionID: "session-primary-fetch-all-prune-quiet-safe" },
      { args: { command: "git fetch --all --prune --quiet" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-remote-verbose-safe" },
      { args: { command: "git remote -v" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-remote-get-url-safe" },
      { args: { command: "git remote get-url origin" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-remote-add-safe" },
      { args: { command: "git remote add origin https://github.com/foo/bar.git" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-remote-set-url-safe" },
      { args: { command: "git remote set-url origin git@github.com:foo/bar.git" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-pull-autostash-safe" },
      { args: { command: "git pull --rebase --autostash" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-pull-origin-main-safe" },
      { args: { command: "git pull --rebase origin main" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-merge-no-edit-safe" },
      { args: { command: "git merge --no-edit feature/test" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-merge-ff-only-safe" },
      { args: { command: "git merge --ff-only origin/main" } }
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
      { tool: "bash", sessionID: "session-primary-worktree-remove-safe" },
      { args: { command: 'git worktree remove "/tmp/gateway-linked"' } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-branch-delete-safe" },
      { args: { command: "git branch -d feature/test" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-cleanup-chain-safe" },
      {
        args: {
          command:
            'git worktree remove "/tmp/gateway-linked" && git branch -d feature/test',
        },
      }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-stash-push-safe" },
      { args: { command: 'git stash push -m "temp" -- docs/plan/docs-automation-summary.md' } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-stash-list-safe" },
      { args: { command: "git stash list" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-safe-chain" },
      { args: { command: "git stash list && git status --short --branch" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-restore-safe" },
      { args: { command: "git restore --source main -- docs/plan/docs-automation-summary.md" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-checkout-restore-safe" },
      { args: { command: "git checkout main -- docs/plan/docs-automation-summary.md" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-oc-current-safe" },
      { args: { command: "oc current" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-oc-queue-safe" },
      { args: { command: "oc queue" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-oc-next-scoped-safe" },
      { args: { command: "oc next --scope dmoliveira/my_opencode --limit 5" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-oc-queue-scoped-safe" },
      { args: { command: "oc queue --scope dmoliveira/my_opencode --limit 10" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-oc-current-json-safe" },
      { args: { command: "oc current --format json" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-oc-resume-safe" },
      { args: { command: "oc resume --task task_171" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-oc-done-safe" },
      { args: { command: "oc done task_171 --note \"completed\"" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-oc-end-session-safe" },
      { args: { command: "oc end-session --outcome done session_62 --achievements \"cleanup complete\"" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-branch-contains-safe" },
      { args: { command: "git branch -r --contains origin/main" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-gh-auth-status-safe" },
      { args: { command: "gh auth status" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-gh-repo-view-safe" },
      { args: { command: "gh repo view --json nameWithOwner" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-gh-repo-create-safe" },
      { args: { command: "gh repo create foo/bar --private --source . --remote origin --push" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-gh-repo-edit-safe" },
      { args: { command: "gh repo edit --visibility private" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-gh-api-user-safe" },
      { args: { command: "gh api user" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-push-main-safe" },
      { args: { command: "git push -u origin main" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-date-safe" },
      { args: { command: 'date +"%Y-%m-%d %H:%M"' } }
    )

    const blockedPullPayload = { args: { command: "git pull --rebase origin feature/x" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-pull-feature-rerouted" },
      blockedPullPayload
    )
    assert.match(blockedPullPayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)

    const blockedStashPopPayload = { args: { command: "git stash pop" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-stash-pop-rerouted" },
      blockedStashPopPayload
    )
    assert.match(blockedStashPopPayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("primary-worktree-guard explains reroute failures when helper path is missing", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-primary-worktree-"))
  const originalHelper = process.env.OPENCODE_MAINTENANCE_HELPER_PATH
  process.env.OPENCODE_MAINTENANCE_HELPER_PATH = join(directory, "missing-helper.py")
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
        { tool: "bash", sessionID: "session-primary-helper-missing" },
        { args: { command: "echo hi > file.txt" } }
      ),
      /Intended reroute:/,
    )
  } finally {
    if (originalHelper === undefined) {
      delete process.env.OPENCODE_MAINTENANCE_HELPER_PATH
    } else {
      process.env.OPENCODE_MAINTENANCE_HELPER_PATH = originalHelper
    }
    rmSync(directory, { recursive: true, force: true })
  }
})
