import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("delegate-task-retry appends guidance for task argument errors", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-delegate-task-retry-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["delegate-task-retry"],
          disabled: [],
        },
        delegateTaskRetry: {
          enabled: true,
        },
      },
    })
    const output = {
      output: "[ERROR] Invalid arguments: missing run_in_background",
    }
    await plugin["tool.execute.after"]({ tool: "task", sessionID: "session-task-1" }, output)
    assert.ok(output.output.includes("IMMEDIATE RETRY REQUIRED"))
    assert.ok(output.output.includes("missing_run_in_background"))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("delegate-task-retry ignores non-task tool outputs", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-delegate-task-retry-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["delegate-task-retry"],
          disabled: [],
        },
        delegateTaskRetry: {
          enabled: true,
        },
      },
    })
    const output = {
      output: "[ERROR] Invalid arguments: missing run_in_background",
    }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-task-2" }, output)
    assert.equal(output.output, "[ERROR] Invalid arguments: missing run_in_background")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
