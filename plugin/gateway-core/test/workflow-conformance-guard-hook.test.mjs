import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

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
