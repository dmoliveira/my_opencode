import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("adaptive-validation-scheduler reminds after edit bursts and clears on validation", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-validation-scheduler-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["adaptive-validation-scheduler"],
          disabled: [],
        },
        adaptiveValidationScheduler: {
          enabled: true,
          reminderEditThreshold: 2,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "write", sessionID: "session-scheduler" },
      { args: { filePath: "src/a.ts" } },
    )
    await plugin["tool.execute.before"](
      { tool: "edit", sessionID: "session-scheduler" },
      { args: { filePath: "src/b.ts" } },
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-scheduler" },
      { args: { command: "git status" } },
    )
    const output1 = { output: "status" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-scheduler" }, output1)
    assert.ok(output1.output.includes("adaptive-validation-scheduler"))

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-scheduler" },
      { args: { command: "npm run lint" } },
    )
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-scheduler" },
      { output: "lint passed" },
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-scheduler" },
      { args: { command: "git status" } },
    )
    const output2 = { output: "status" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-scheduler" }, output2)
    assert.equal(output2.output.includes("adaptive-validation-scheduler"), false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
