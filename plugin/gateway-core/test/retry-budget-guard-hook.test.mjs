import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("retry-budget-guard adds escalation message after max retries", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-retry-budget-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["retry-budget-guard"], disabled: [] },
        retryBudgetGuard: {
          enabled: true,
          maxRetries: 1,
        },
      },
    })
    const first = { output: "[ERROR] task failed" }
    await plugin["tool.execute.after"]({ tool: "task", sessionID: "session-retry" }, first)
    const second = { output: "[ERROR] task failed" }
    await plugin["tool.execute.after"]({ tool: "task", sessionID: "session-retry" }, second)
    assert.ok(second.output.includes("Retry budget exceeded"))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
