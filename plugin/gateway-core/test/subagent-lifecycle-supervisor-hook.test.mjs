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
      { args: { subagent_type: "explore", prompt: "[DELEGATION TRACE same-trace] first" } },
    )

    await assert.rejects(
      () =>
        plugin["tool.execute.before"](
          { tool: "task", sessionID: "session-life-1" },
          { args: { subagent_type: "explore", prompt: "[DELEGATION TRACE same-trace] second" } },
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
      { args: { subagent_type: "reviewer", prompt: "[DELEGATION TRACE retry-trace] first" } },
    )
    const failedOutput = {
      args: { subagent_type: "reviewer", prompt: "[DELEGATION TRACE retry-trace] first" },
      output: "[ERROR] Invalid arguments",
    }
    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-life-2" },
      failedOutput,
    )

    await assert.rejects(
      () =>
        plugin["tool.execute.before"](
          { tool: "task", sessionID: "session-life-2" },
          { args: { subagent_type: "reviewer", prompt: "[DELEGATION TRACE retry-trace] second" } },
        ),
      /retry budget exhausted/i,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("subagent-lifecycle-supervisor allows parallel delegations in one session when trace ids differ", async () => {
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
      { tool: "task", sessionID: "session-life-3" },
      { args: { subagent_type: "explore", prompt: "[DELEGATION TRACE trace-a] first" } },
    )

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-life-3" },
      { args: { subagent_type: "explore", prompt: "[DELEGATION TRACE trace-b] second" } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("subagent-lifecycle-supervisor allows mixed subagents in one session without explicit traces", async () => {
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
      { tool: "task", sessionID: "session-life-4" },
      { args: { subagent_type: "explore" } },
    )
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-life-4" },
      { args: { subagent_type: "strategic-planner" } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("subagent-lifecycle-supervisor preserves running entries on ambiguous trace-less after events", async () => {
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
      { tool: "task", sessionID: "session-life-5" },
      { args: { subagent_type: "explore", prompt: "[DELEGATION TRACE explore-trace] first" } },
    )
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-life-5" },
      { args: { subagent_type: "strategic-planner", prompt: "[DELEGATION TRACE planner-trace] second" } },
    )

    const afterOutput = { output: "done" }
    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-life-5" },
      afterOutput,
    )

    assert.match(afterOutput.output, /ambiguous trace-less completion observed/i)
    await assert.rejects(
      () =>
        plugin["tool.execute.before"](
          { tool: "task", sessionID: "session-life-5" },
          { args: { subagent_type: "explore", prompt: "[DELEGATION TRACE explore-trace] retry" } },
        ),
      /already running/i,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("subagent-lifecycle-supervisor does not mark plain analytical output as failed", async () => {
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
          staleRunningMs: 60000,
          blockOnExhausted: true,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-life-6" },
      { args: { subagent_type: "reviewer" } },
    )
    const output = {
      output: "The first approach failed because the prompt omitted context, but the final recommendation is complete.",
    }
    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-life-6" },
      output,
    )

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-life-6" },
      { args: { subagent_type: "reviewer" } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("subagent-lifecycle-supervisor resolves trace-less completion from output subagent hint", async () => {
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
      { tool: "task", sessionID: "session-life-7" },
      { args: { subagent_type: "explore", prompt: "[DELEGATION TRACE explore-trace-7] first" } },
    )
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-life-7" },
      { args: { subagent_type: "strategic-planner", prompt: "[DELEGATION TRACE planner-trace-7] second" } },
    )
    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-life-7" },
      {
        output: "done\n\n[agent-context-shaper] delegation context\n- subagent: strategic-planner\n- recommended_category: deep",
      },
    )

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-life-7" },
      { args: { subagent_type: "strategic-planner" } },
    )
    await assert.rejects(
      () =>
        plugin["tool.execute.before"](
          { tool: "task", sessionID: "session-life-7" },
          { args: { subagent_type: "explore", prompt: "[DELEGATION TRACE explore-trace-7] retry" } },
        ),
      /already running/i,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("agent-context-shaper stamps metadata before lifecycle handles trace-less completion", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-subagent-lifecycle-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["agent-context-shaper", "subagent-lifecycle-supervisor"],
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
      { tool: "task", sessionID: "session-life-8" },
      { args: { subagent_type: "explore", prompt: "[DELEGATION TRACE trace-8] first" } },
    )
    const afterOutput = { output: "done" }
    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-life-8" },
      afterOutput,
    )

    assert.doesNotMatch(String(afterOutput.output), /ambiguous trace-less completion observed/i)
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-life-8" },
      { args: { subagent_type: "explore", prompt: "[DELEGATION TRACE trace-8b] second" } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
