import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("subagent-lifecycle-supervisor blocks duplicate running delegations", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-subagent-lifecycle-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["subagent-lifecycle-supervisor"],
          disabled: [],
        },
        subagentLifecycleSupervisor: {
          enabled: true,
          maxRetriesPerSession: 3,
          staleRunningMs: 60000,
          blockOnExhausted: true,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-life-1" },
      { args: { subagent_type: "explore" } },
    )

    await assert.rejects(
      () =>
        plugin["tool.execute.before"](
          { tool: "task", sessionID: "session-life-1" },
          { args: { subagent_type: "explore" } },
        ),
      /already running/i,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("subagent-lifecycle-supervisor blocks exhausted retry sessions", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-subagent-lifecycle-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["subagent-lifecycle-supervisor"],
          disabled: [],
        },
        subagentLifecycleSupervisor: {
          enabled: true,
          maxRetriesPerSession: 1,
          staleRunningMs: 1000,
          blockOnExhausted: true,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-life-2" },
      { args: { subagent_type: "reviewer" } },
    )
    const failedOutput = { output: "[ERROR] Invalid arguments" }
    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-life-2" },
      failedOutput,
    )

    await assert.rejects(
      () =>
        plugin["tool.execute.before"](
          { tool: "task", sessionID: "session-life-2" },
          { args: { subagent_type: "reviewer" } },
        ),
      /retry budget exhausted/i,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
