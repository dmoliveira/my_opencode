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

test("delegate-task-retry appends fallback guidance for aborted delegated tasks", async () => {
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
      output: {
        output: 'task tool failed: Tool execution aborted',
      },
    }
    await plugin["tool.execute.after"]({ tool: "task", sessionID: "session-task-3" }, output)
    assert.equal(typeof output.output.output, "string")
    assert.ok(output.output.output.includes("delegated_task_aborted"))
    assert.ok(output.output.output.includes("Do not leave the parent session silent"))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("delegate-task-retry does not append abort guidance when a structured task result is present", async () => {
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
      output: {
        output: `<task_result>\nRecovered useful delegated output\n</task_result>\n[task CALL FAILED - IMMEDIATE RETRY REQUIRED]\nError Type: delegated_task_aborted\nFix: retry`,
      },
    }
    await plugin["tool.execute.after"]({ tool: "task", sessionID: "session-task-4" }, output)
    assert.equal(typeof output.output.output, "string")
    assert.equal(output.output.output.match(/delegated_task_aborted/g)?.length ?? 0, 1)
    assert.equal(output.output.output.match(/IMMEDIATE RETRY REQUIRED/g)?.length ?? 0, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
