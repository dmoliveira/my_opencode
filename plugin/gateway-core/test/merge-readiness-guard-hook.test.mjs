import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("merge-readiness-guard enforces merge flags", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-merge-readiness-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["merge-readiness-guard"],
          disabled: ["gh-checks-merge-guard"],
        },
        mergeReadinessGuard: {
          enabled: true,
          requireDeleteBranch: true,
          requireStrategy: true,
          disallowAdminBypass: true,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-merge" },
        { args: { command: "gh pr merge 10" } },
      ),
      /Merge strategy flag is required/,
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-merge" },
        { args: { command: "gh pr merge 10 --merge" } },
      ),
      /--delete-branch/,
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-merge" },
        { args: { command: "gh pr merge 10 --merge --delete-branch --admin" } },
      ),
      /--admin/,
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-merge" },
      { args: { command: "gh pr merge 10 --merge --delete-branch" } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
