import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("empty-task-response-detector adds warning when task output is empty", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-empty-task-response-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["empty-task-response-detector"], disabled: [] },
        emptyTaskResponseDetector: { enabled: true },
      },
    })
    const output = { output: "   " }
    await plugin["tool.execute.after"]({ tool: "task", sessionID: "session-empty-task" }, output)
    assert.ok(output.output.includes("Empty task output detected"))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
