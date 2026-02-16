import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import { createPostMergeSyncGuardHook } from "../dist/hooks/post-merge-sync-guard/index.js"

test("post-merge-sync-guard blocks merge command without delete-branch when required", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-post-merge-"))
  try {
    const hook = createPostMergeSyncGuardHook({
      directory,
      enabled: true,
      requireDeleteBranch: true,
      enforceMainSyncInline: false,
      reminderCommands: ["git checkout main", "git pull --rebase"],
    })

    await assert.rejects(
      hook.event("tool.execute.before", {
        input: { tool: "bash", sessionID: "session-post-merge" },
        output: { args: { command: "gh pr merge 10 --merge" } },
        directory,
      }),
      /--delete-branch/,
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
      reminderCommands: ["git checkout main", "git pull --rebase"],
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
    assert.match(String(afterPayload.output.output), /Merge complete\. Run cleanup sync/)
    assert.match(String(afterPayload.output.output), /git pull --rebase/)
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
      reminderCommands: ["git checkout main", "git pull --rebase"],
    })

    await assert.rejects(
      hook.event("tool.execute.before", {
        input: { tool: "bash", sessionID: "session-post-merge" },
        output: { args: { command: "gh pr merge 10 --merge --delete-branch" } },
        directory,
      }),
      /inline main sync/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
