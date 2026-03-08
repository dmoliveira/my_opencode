import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { setTimeout as delay } from "node:timers/promises"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("delegation-concurrency-guard counts mixed subagents separately without explicit traces", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-delegation-concurrency-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["delegation-concurrency-guard"],
          disabled: [],
        },
        delegationConcurrencyGuard: {
          enabled: true,
          maxTotalConcurrent: 2,
          maxExpensiveConcurrent: 2,
          maxDeepConcurrent: 2,
          maxCriticalConcurrent: 1,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-concurrency-1" },
      { args: { subagent_type: "explore" } },
    )
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-concurrency-1" },
      { args: { subagent_type: "strategic-planner" } },
    )

    await assert.rejects(
      () =>
        plugin["tool.execute.before"](
          { tool: "task", sessionID: "session-concurrency-1" },
          { args: { subagent_type: "reviewer" } },
        ),
      /maxTotalConcurrent/i,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("delegation-concurrency-guard keeps parallel reservations when after event is trace-less and ambiguous", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-delegation-concurrency-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["delegation-concurrency-guard"],
          disabled: [],
        },
        delegationConcurrencyGuard: {
          enabled: true,
          maxTotalConcurrent: 2,
          maxExpensiveConcurrent: 2,
          maxDeepConcurrent: 2,
          maxCriticalConcurrent: 1,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-concurrency-2" },
      { args: { subagent_type: "explore" } },
    )
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-concurrency-2" },
      { args: { subagent_type: "strategic-planner" } },
    )

    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-concurrency-2" },
      { output: "done" },
    )

    await assert.rejects(
      () =>
        plugin["tool.execute.before"](
          { tool: "task", sessionID: "session-concurrency-2" },
          { args: { subagent_type: "reviewer" } },
        ),
      /maxTotalConcurrent/i,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("delegation-concurrency-guard prunes stale ambiguous reservations before new work", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-delegation-concurrency-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["delegation-concurrency-guard"],
          disabled: [],
        },
        delegationConcurrencyGuard: {
          enabled: true,
          maxTotalConcurrent: 2,
          maxExpensiveConcurrent: 2,
          maxDeepConcurrent: 2,
          maxCriticalConcurrent: 1,
        },
        subagentLifecycleSupervisor: {
          enabled: true,
          maxRetriesPerSession: 3,
          staleRunningMs: 1,
          blockOnExhausted: true,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-concurrency-3" },
      { args: { subagent_type: "explore" } },
    )
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-concurrency-3" },
      { args: { subagent_type: "strategic-planner" } },
    )
    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-concurrency-3" },
      { output: "done" },
    )

    await delay(5)

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-concurrency-3" },
      { args: { subagent_type: "reviewer" } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("delegation-concurrency-guard releases matching reservation from output subagent hint", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-delegation-concurrency-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["delegation-concurrency-guard"],
          disabled: [],
        },
        delegationConcurrencyGuard: {
          enabled: true,
          maxTotalConcurrent: 2,
          maxExpensiveConcurrent: 2,
          maxDeepConcurrent: 2,
          maxCriticalConcurrent: 1,
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
      { tool: "task", sessionID: "session-concurrency-4" },
      { args: { subagent_type: "explore" } },
    )
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-concurrency-4" },
      { args: { subagent_type: "strategic-planner" } },
    )
    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-concurrency-4" },
      {
        output: "done\n\n[agent-context-shaper] delegation context\n- subagent: strategic-planner\n- recommended_category: deep",
      },
    )

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-concurrency-4" },
      { args: { subagent_type: "reviewer" } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("delegation-concurrency-guard releases reservation from child-run-only after metadata", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-delegation-concurrency-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["delegation-concurrency-guard"],
          disabled: [],
        },
        delegationConcurrencyGuard: {
          enabled: true,
          maxTotalConcurrent: 1,
          maxExpensiveConcurrent: 1,
          maxDeepConcurrent: 1,
          maxCriticalConcurrent: 1,
        },
      },
    })

    const beforeOutput = { args: { subagent_type: "explore", prompt: "first" } }
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-concurrency-child-run-after" },
      beforeOutput,
    )

    const childRunId = beforeOutput.metadata?.gateway?.delegation?.childRunId
    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-concurrency-child-run-after" },
      {
        metadata: {
          gateway: {
            delegation: {
              childRunId,
            },
          },
        },
        output: "done",
      },
    )

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-concurrency-child-run-after" },
      { args: { subagent_type: "reviewer", prompt: "second" } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("delegation-concurrency-guard releases reservation from child run id metadata", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-delegation-concurrency-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["delegation-concurrency-guard"],
          disabled: [],
        },
        delegationConcurrencyGuard: {
          enabled: true,
          maxTotalConcurrent: 1,
          maxExpensiveConcurrent: 1,
          maxDeepConcurrent: 1,
          maxCriticalConcurrent: 1,
        },
      },
    })

    const beforeOutput = { args: { subagent_type: "explore", prompt: "first" } }
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-concurrency-child-run" },
      beforeOutput,
    )

    const childRunId = beforeOutput.metadata?.gateway?.delegation?.childRunId
    assert.match(String(childRunId), /^subagent-run\//)

    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-concurrency-child-run" },
      { metadata: beforeOutput.metadata, output: "done" },
    )

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-concurrency-child-run" },
      { args: { subagent_type: "reviewer", prompt: "second" } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
