import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("read-budget-optimizer warns on repeated small reads", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-read-budget-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["read-budget-optimizer"],
          disabled: [],
        },
        readBudgetOptimizer: {
          enabled: true,
          smallReadLimit: 60,
          maxConsecutiveSmallReads: 2,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "read", sessionID: "session-read-budget" },
      { args: { filePath: "/tmp/a.ts", limit: 40, offset: 1 } },
    )
    const output1 = { output: "chunk-1" }
    await plugin["tool.execute.after"]({ tool: "read", sessionID: "session-read-budget" }, output1)
    assert.equal(output1.output.includes("read-budget-optimizer"), false)

    await plugin["tool.execute.before"](
      { tool: "read", sessionID: "session-read-budget" },
      { args: { filePath: "/tmp/a.ts", limit: 40, offset: 41 } },
    )
    const output2 = { output: "chunk-2" }
    await plugin["tool.execute.after"]({ tool: "read", sessionID: "session-read-budget" }, output2)
    assert.ok(output2.output.includes("read-budget-optimizer"))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
