import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import { createPostMergeSyncGuardHook } from "../dist/hooks/post-merge-sync-guard/index.js"

function commitAll(directory, message) {
  execSync("git add .", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
  execSync(`git -c user.name=test -c user.email=test@example.com commit -m "${message}"`, {
    cwd: directory,
    stdio: ["ignore", "pipe", "pipe"],
  })
}

test("post-merge-sync-guard blocks merge command without delete-branch when required", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-post-merge-"))
  try {
    const hook = createPostMergeSyncGuardHook({
      directory,
      enabled: true,
      requireDeleteBranch: true,
      enforceMainSyncInline: false,
      reminderCommands: ["git pull --rebase"],
    })

    await assert.rejects(
      hook.event("tool.execute.before", {
        input: { tool: "bash", sessionID: "session-post-merge" },
        output: { args: { command: "gh pr merge 10 --merge" } },
        directory,
      }),
      /--delete-branch/
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("post-merge-sync-guard appends sync reminder after merge without inline pull", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-post-merge-"))
  try {
    const hook = createPostMergeSyncGuardHook({
      directory,
      enabled: true,
      requireDeleteBranch: true,
      enforceMainSyncInline: false,
      reminderCommands: ["git pull --rebase"],
    })

    await hook.event("tool.execute.before", {
      input: { tool: "bash", sessionID: "session-post-merge" },
      output: { args: { command: "gh pr merge 10 --merge --delete-branch" } },
      directory,
    })

    const afterPayload = {
      input: { tool: "bash", sessionID: "session-post-merge" },
      output: { output: "merged" },
      directory,
    }
    await hook.event("tool.execute.after", afterPayload)
    assert.match(String(afterPayload.output.output), /Merge complete\./)
    assert.match(String(afterPayload.output.output), /inspect worktrees before syncing/)
    assert.match(String(afterPayload.output.output), /git worktree list/)
    assert.match(String(afterPayload.output.output), /git status --short --branch/)
    assert.doesNotMatch(String(afterPayload.output.output), /git checkout main/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("post-merge-sync-guard enforces inline main sync when configured", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-post-merge-"))
  try {
    const hook = createPostMergeSyncGuardHook({
      directory,
      enabled: true,
      requireDeleteBranch: true,
      enforceMainSyncInline: true,
      reminderCommands: ["git pull --rebase"],
    })

    await assert.rejects(
      hook.event("tool.execute.before", {
        input: { tool: "bash", sessionID: "session-post-merge" },
        output: { args: { command: "gh pr merge 10 --merge --delete-branch" } },
        directory,
      }),
      /inline main sync/
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("post-merge-sync-guard avoids checkout guidance when no main worktree is checked out", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-post-merge-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "file.txt"), "v1\n", "utf-8")
    commitAll(directory, "init")
    execSync("git checkout -b feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })

    const hook = createPostMergeSyncGuardHook({
      directory,
      enabled: true,
      requireDeleteBranch: true,
      enforceMainSyncInline: false,
      reminderCommands: ["git pull --rebase"],
    })

    await hook.event("tool.execute.before", {
      input: { tool: "bash", sessionID: "session-post-merge" },
      output: { args: { command: "gh pr merge 10 --merge --delete-branch" } },
      directory,
    })

    const afterPayload = {
      input: { tool: "bash", sessionID: "session-post-merge" },
      output: { output: "merged" },
      directory,
    }
    await hook.event("tool.execute.after", afterPayload)
    assert.match(String(afterPayload.output.output), /No checked-out main worktree was found/)
    assert.match(String(afterPayload.output.output), /git worktree list/)
    assert.match(String(afterPayload.output.output), /git status --short --branch/)
    assert.doesNotMatch(String(afterPayload.output.output), /git checkout main/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("post-merge-sync-guard applies merge reminders to gh api PR merge", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-post-merge-"))
  try {
    const hook = createPostMergeSyncGuardHook({
      directory,
      enabled: true,
      requireDeleteBranch: false,
      enforceMainSyncInline: false,
      reminderCommands: ["git pull --rebase"],
    })

    await hook.event("tool.execute.before", {
      input: { tool: "bash", sessionID: "session-post-merge-api" },
      output: { args: { command: "gh api repos/foo/bar/pulls/10/merge -X PUT -f merge_method=merge" } },
      directory,
    })

    const afterPayload = {
      input: { tool: "bash", sessionID: "session-post-merge-api" },
      output: { output: "merged" },
      directory,
    }
    await hook.event("tool.execute.after", afterPayload)
    assert.match(String(afterPayload.output.output), /Merge complete\./)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("post-merge-sync-guard downgrades benign gh merge worktree warnings", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-post-merge-"))
  try {
    const hook = createPostMergeSyncGuardHook({
      directory,
      enabled: true,
      requireDeleteBranch: false,
      enforceMainSyncInline: false,
      reminderCommands: ["git pull --rebase"],
    })

    await hook.event("tool.execute.before", {
      input: { tool: "bash", sessionID: "session-post-merge-benign-warning" },
      output: { args: { command: "gh pr merge 10 --merge --delete-branch" } },
      directory,
    })

    const afterPayload = {
      input: { tool: "bash", sessionID: "session-post-merge-benign-warning" },
      output: {
        output:
          "failed to run git: fatal: 'main' is already used by worktree at '/tmp/primary'\n\n[post-merge-sync-guard] Merge complete. Run cleanup sync:\n- git pull --rebase",
      },
      directory,
    }
    await hook.event("tool.execute.after", afterPayload)
    assert.doesNotMatch(String(afterPayload.output.output), /failed to run git/)
    assert.doesNotMatch(String(afterPayload.output.output), /already used by worktree/)
    assert.match(String(afterPayload.output.output), /PR merged on GitHub/)
    assert.match(String(afterPayload.output.output), /git pull --rebase/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
