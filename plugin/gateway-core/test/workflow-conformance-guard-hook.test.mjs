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
    assert.match(payload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)
    assert.match(payload.args.command, /--command 'git commit -m "msg"' --json/)
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
      { tool: "bash", sessionID: "session-workflow-sqlite-readonly-safe" },
      { args: { command: 'sqlite3 -readonly "/tmp/runtime.db" ".tables"' } }
    )

    const sqliteSchemaPayload = {
      args: { command: 'sqlite3 -readonly "/tmp/runtime.db" ".schema session"' },
    }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-sqlite-dot-schema-safe" },
      sqliteSchemaPayload
    )
    assert.equal(
      sqliteSchemaPayload.args.command,
      'sqlite3 -readonly "/tmp/runtime.db" ".schema session"',
    )

    const sqlitePragmaPayload = {
      args: {
        command:
          'CI=true OPENCODE_SESSION_ID=demo sqlite3 -readonly "/tmp/runtime.db" "PRAGMA table_info(session);"',
      },
    }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-sqlite-schema-safe" },
      sqlitePragmaPayload
    )
    assert.equal(
      sqlitePragmaPayload.args.command,
      'CI=true OPENCODE_SESSION_ID=demo sqlite3 -readonly "/tmp/runtime.db" "PRAGMA table_info(session);"',
    )

    const sqliteSelectPayload = {
      args: { command: 'sqlite3 -readonly "/tmp/runtime.db" "SELECT id, title FROM session"' },
    }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-sqlite-select-safe" },
      sqliteSelectPayload
    )
    assert.equal(
      sqliteSelectPayload.args.command,
      'sqlite3 -readonly "/tmp/runtime.db" "SELECT id, title FROM session"',
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-gh-abs-safe" },
      { args: { command: "/usr/bin/gh pr view --json number" } }
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
      { tool: "bash", sessionID: "session-workflow-fetch-all-prune-quiet-safe" },
      { args: { command: "git fetch --all --prune --quiet" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-remote-verbose-safe" },
      { args: { command: "git remote -v" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-remote-get-url-safe" },
      { args: { command: "git remote get-url origin" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-remote-add-safe" },
      { args: { command: "git remote add origin https://github.com/foo/bar.git" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-remote-set-url-safe" },
      { args: { command: "git remote set-url origin git@github.com:foo/bar.git" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-push-main-safe" },
      { args: { command: "git push -u origin main" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-pull-autostash-safe" },
      { args: { command: "git pull --rebase --autostash" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-pull-origin-main-safe" },
      { args: { command: "git pull --rebase origin main" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-merge-no-edit-safe" },
      { args: { command: "git merge --no-edit feature/test" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-merge-ff-only-safe" },
      { args: { command: "git merge --ff-only origin/main" } }
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
      { tool: "bash", sessionID: "session-workflow-worktree-remove-safe" },
      { args: { command: 'git worktree remove "/tmp/gateway-linked"' } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-branch-delete-safe" },
      { args: { command: "git branch -d feature/test" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-cleanup-chain-safe" },
      {
        args: {
          command:
            'git worktree remove "/tmp/gateway-linked" && git branch -d feature/test',
        },
      }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-stash-push-safe" },
      { args: { command: 'git stash push -m "temp" -- docs/plan/docs-automation-summary.md' } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-stash-list-safe" },
      { args: { command: "git stash list" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-safe-chain" },
      { args: { command: "git stash list && git status --short --branch" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-restore-safe" },
      { args: { command: "git restore --source main -- docs/plan/docs-automation-summary.md" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-checkout-restore-safe" },
      { args: { command: "git checkout main -- docs/plan/docs-automation-summary.md" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-oc-current-safe" },
      { args: { command: "oc current" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-oc-next-safe" },
      { args: { command: "oc next" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-oc-next-scoped-safe" },
      { args: { command: "oc next --scope dmoliveira/my_opencode --limit 5" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-oc-queue-scoped-safe" },
      { args: { command: "oc queue --scope dmoliveira/my_opencode --limit 10" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-oc-current-json-safe" },
      { args: { command: "oc current --format json" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-oc-resume-safe" },
      { args: { command: "oc resume --task task_171" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-oc-done-safe" },
      { args: { command: "oc done task_171 --note \"completed\"" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-oc-end-session-safe" },
      { args: { command: "oc end-session --outcome done session_62 --achievements \"cleanup complete\"" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-branch-contains-safe" },
      { args: { command: "git branch -r --contains origin/main" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-gh-auth-status-safe" },
      { args: { command: "gh auth status" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-gh-repo-view-safe" },
      { args: { command: "gh repo view --json nameWithOwner" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-gh-repo-create-safe" },
      { args: { command: "gh repo create foo/bar --private --source . --remote origin --push" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-gh-repo-edit-safe" },
      { args: { command: "gh repo edit --visibility private" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-gh-api-user-safe" },
      { args: { command: "gh api user" } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-date-safe" },
      { args: { command: 'date +"%Y-%m-%d %H:%M"' } }
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
    assert.match(payload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)
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
    assert.match(payload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)
    assert.match(payload.args.command, /--command 'rtk git commit -m "msg"' --json/)
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
    assert.match(mutatePayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)
    assert.match(mutatePayload.args.command, /--command 'echo hi > file\.txt' --json/)

    const ghPayload = { args: { command: "gh api -X POST repos/foo/bar/issues" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-gh-api" },
      ghPayload
    )
    assert.match(ghPayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)

    const chainPayload = { args: { command: "git status --short --branch && echo hi > file.txt" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-chain" },
      chainPayload
    )
    assert.match(chainPayload.args.command, /--command 'git status --short --branch && echo hi > file\.txt' --json/)

    const pullPayload = { args: { command: "git pull --rebase origin feature/x" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-refspec-pull" },
      pullPayload
    )
    assert.match(pullPayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)

    const fetchPayload = { args: { command: "git fetch origin +feature/x:main" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-fetch-refspec" },
      fetchPayload
    )
    assert.match(fetchPayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)

    const stashPopPayload = { args: { command: "git stash pop" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-stash-pop-rerouted" },
      stashPopPayload
    )
    assert.match(stashPopPayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)

    const redirectPayload = { args: { command: "git status --short --branch > file.txt" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-redirection" },
      redirectPayload
    )
    assert.match(redirectPayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)

    const commandSubstitutionPayload = {
      args: { command: 'git status --short --branch "$(touch /tmp/pwn)"' },
    }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-command-substitution" },
      commandSubstitutionPayload
    )
    assert.match(commandSubstitutionPayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)
    assert.match(commandSubstitutionPayload.args.command, /--command 'git status --short --branch "\$\(touch \/tmp\/pwn\)"' --json/)

    const envExpansionPayload = { args: { command: 'CI="$(id)" git fetch' } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-env-expansion" },
      envExpansionPayload
    )
    assert.match(envExpansionPayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)
    assert.match(envExpansionPayload.args.command, /--command 'CI="\$\(id\)" git fetch' --json/)

    const sqliteShellPayload = {
      args: { command: 'sqlite3 -readonly "/tmp/runtime.db" -cmd ".shell touch /tmp/pwn" ".tables"' },
    }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-sqlite-shell" },
      sqliteShellPayload
    )
    assert.match(sqliteShellPayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)

    const sqliteOutputPayload = {
      args: { command: 'sqlite3 -readonly "/tmp/runtime.db" ".output /tmp/dump.txt"' },
    }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-sqlite-output" },
      sqliteOutputPayload
    )
    assert.match(sqliteOutputPayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)

    const sqlitePragmaMutatePayload = {
      args: { command: 'sqlite3 -readonly "/tmp/runtime.db" "PRAGMA journal_mode=WAL;"' },
    }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-sqlite-pragma-mutate" },
      sqlitePragmaMutatePayload
    )
    assert.match(sqlitePragmaMutatePayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)

    const sqliteWithInsertPayload = {
      args: {
        command:
          'sqlite3 -readonly "/tmp/runtime.db" "WITH recent AS (SELECT 1) INSERT INTO audit_log SELECT * FROM recent;"',
      },
    }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-sqlite-with-insert" },
      sqliteWithInsertPayload
    )
    assert.match(sqliteWithInsertPayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)

    const sqliteSelectBypassPayload = {
      args: { command: 'sqlite3 -readonly "/tmp/runtime.db" "SELECT 1; DELETE FROM audit_log;"' },
    }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-sqlite-select-bypass" },
      sqliteSelectBypassPayload
    )
    assert.match(sqliteSelectBypassPayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)

    const sqlitePragmaBypassPayload = {
      args: {
        command:
          'sqlite3 -readonly "/tmp/runtime.db" "PRAGMA table_info(session); INSERT INTO audit_log VALUES (1);"',
      },
    }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-sqlite-pragma-bypass" },
      sqlitePragmaBypassPayload
    )
    assert.match(sqlitePragmaBypassPayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)

    const sqliteLoadExtensionPayload = {
      args: { command: 'sqlite3 -readonly "/tmp/runtime.db" "SELECT load_extension(\"/tmp/pwn\");"' },
    }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-sqlite-load-extension" },
      sqliteLoadExtensionPayload
    )
    assert.match(sqliteLoadExtensionPayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)

    const sqliteEnvBypassPayload = {
      args: { command: 'BASH_ENV=/tmp/evil.sh sqlite3 -readonly "/tmp/runtime.db" ".tables"' },
    }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-sqlite-env-bypass" },
      sqliteEnvBypassPayload
    )
    assert.match(sqliteEnvBypassPayload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("workflow-conformance-guard explains reroute failures when helper path is missing", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-guard-"))
  const originalHelper = process.env.OPENCODE_MAINTENANCE_HELPER_PATH
  process.env.OPENCODE_MAINTENANCE_HELPER_PATH = join(directory, "missing-helper.py")
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
        { tool: "bash", sessionID: "session-workflow-helper-missing" },
        { args: { command: 'git commit -m "msg"' } },
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
