import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("parallel-opportunity-detector suggests parallel diagnostics once per session", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-parallel-opportunity-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["parallel-opportunity-detector"],
          disabled: [],
        },
        parallelOpportunityDetector: {
          enabled: true,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-parallel" },
      { args: { command: "git status" } },
    )
    const output1 = { output: "status output" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-parallel" }, output1)
    assert.ok(output1.output.includes("parallel-opportunity-detector"))

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-parallel" },
      { args: { command: "git diff" } },
    )
    const output2 = { output: "diff output" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-parallel" }, output2)
    assert.equal(output2.output.includes("parallel-opportunity-detector"), false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
