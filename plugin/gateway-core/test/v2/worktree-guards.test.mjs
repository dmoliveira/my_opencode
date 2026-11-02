import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { mkdtemp, rm, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import { registerV2WorktreeGuards } from "../../dist/v2/worktree-guards.js"

test("V2 worktree guards resolve native paths, patch targets, and shell commands", async () => {
  const root = await mkdtemp(join(tmpdir(), "v2-worktree-guard-"))
  const main = join(root, "main")
  const linked = join(root, "linked")
  const git = (args, cwd = root) => execFileSync("git", args, { cwd, stdio: "ignore" })
  let callback
  try {
    git(["init", "--initial-branch=main", main])
    await writeFile(join(main, "tracked.txt"), "original")
    git(["add", "tracked.txt"], main)
    git(["-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "initial"], main)
    git(["worktree", "add", "-b", "test-linked", linked], main)
    const dispose = await registerV2WorktreeGuards({ async hook(_name, handler) {
      callback = handler
      return { async dispose() {} }
    } }, async () => main, {
      directory: main,
      writeExisting: { enabled: true },
      primary: { enabled: true, allowedBranches: ["main", "master"], blockEdits: true, blockBranchSwitches: true },
      workflow: { enabled: true, protectedBranches: ["main", "master"], blockEditsOnProtectedBranches: true },
    })
    const base = { sessionID: "ses_v2test", id: "call_test", agent: "build" }
    await assert.rejects(callback({ ...base, tool: "edit", input: { path: "tracked.txt", oldString: "original", newString: "new" } }), /blocked in the primary/)
    await assert.rejects(callback({ ...base, tool: "write", input: { path: "tracked.txt", content: "new" } }), /already exists/)
    await assert.rejects(callback({ ...base, tool: "patch", input: { patchText: "*** Begin Patch\n*** Add File: new.txt\n+x\n*** End Patch" } }), /blocked in the primary/)
    await assert.rejects(callback({ ...base, tool: "shell", input: { command: "git switch other" } }), /Branch switching/)
    await callback({ ...base, tool: "edit", input: { path: join(linked, "tracked.txt"), oldString: "original", newString: "new" } })
    await assert.rejects(callback({ ...base, tool: "edit", input: { filePath: "tracked.txt" } }), /invalid V2 file target/)
    await dispose()
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})
