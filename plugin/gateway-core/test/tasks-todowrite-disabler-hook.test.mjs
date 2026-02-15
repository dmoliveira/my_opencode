import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("tasks-todowrite-disabler blocks task tool", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-task-disabler-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["tasks-todowrite-disabler"],
          disabled: [],
        },
        tasksTodowriteDisabler: { enabled: true },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "task", sessionID: "session-task-disabler" },
        { args: {} },
      ),
      /disabled in this workflow/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("tasks-todowrite-disabler allows other tools", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-task-disabler-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["tasks-todowrite-disabler"],
          disabled: [],
        },
        tasksTodowriteDisabler: { enabled: true },
      },
    })
    await plugin["tool.execute.before"]({ tool: "bash", sessionID: "session-ok" }, { args: {} })
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
