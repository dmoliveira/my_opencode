import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("task-resume-info appends task_id resume hint", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-task-resume-info-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["task-resume-info"],
          disabled: [],
        },
        taskResumeInfo: { enabled: true },
      },
    })
    const output = { output: "Task completed. task_id: abc-123" }
    await plugin["tool.execute.after"]({ tool: "task", sessionID: "session-task-1" }, output)
    assert.ok(output.output.includes("Resume hint"))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
