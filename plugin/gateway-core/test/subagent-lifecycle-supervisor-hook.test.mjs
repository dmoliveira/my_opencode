import assert from "node:assert/strict"
import { mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { createSubagentLifecycleSupervisorHook } from "../dist/hooks/subagent-lifecycle-supervisor/index.js"

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

test("subagent-lifecycle-supervisor force-cleans ambiguous trace-less after events", async () => {
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

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-life-5" },
      { args: { subagent_type: "explore", prompt: "[DELEGATION TRACE explore-trace] retry" } },
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


test("subagent-lifecycle-supervisor completes from child-run-only metadata on after events", async () => {
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

    const beforeOutput = { args: { subagent_type: "explore", prompt: "first" } }
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-life-child-run-after" },
      beforeOutput,
    )

    const childRunId = beforeOutput.metadata?.gateway?.delegation?.childRunId
    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-life-child-run-after" },
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
      { tool: "task", sessionID: "session-life-child-run-after" },
      { args: { subagent_type: "explore", prompt: "second" } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("subagent-lifecycle-supervisor uses child run id metadata before fallback cleanup", async () => {
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

    const beforeOutput = { args: { subagent_type: "explore", prompt: "first" } }
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-life-child-run" },
      beforeOutput,
    )

    const childRunId = beforeOutput.metadata?.gateway?.delegation?.childRunId
    assert.match(String(childRunId), /^subagent-run\//)

    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-life-child-run" },
      { metadata: beforeOutput.metadata, output: "done" },
    )

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-life-child-run" },
      { args: { subagent_type: "explore", prompt: "second" } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("subagent-lifecycle-supervisor records fallback and ambiguous cleanup audit reasons", async () => {
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
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
      { tool: "task", sessionID: "session-life-audit" },
      { args: { subagent_type: "explore", prompt: "[DELEGATION TRACE life-audit-explore] first" } },
    )
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-life-audit" },
      { args: { subagent_type: "strategic-planner", prompt: "[DELEGATION TRACE life-audit-plan] second" } },
    )
    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-life-audit" },
      {
        output: `done

[agent-context-shaper] delegation context
- subagent: strategic-planner
- recommended_category: deep`,
      },
    )
    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-life-audit" },
      { output: "done" },
    )
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-life-audit-ambiguous" },
      { args: { subagent_type: "explore", prompt: "[DELEGATION TRACE life-audit-ambiguous-explore] first" } },
    )
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-life-audit-ambiguous" },
      { args: { subagent_type: "strategic-planner", prompt: "[DELEGATION TRACE life-audit-ambiguous-plan] second" } },
    )
    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-life-audit-ambiguous" },
      { output: "done" },
    )

    const events = readFileSync(join(directory, ".opencode", "gateway-events.jsonl"), "utf-8")
      .split(/\n+/)
      .filter(Boolean)
      .map((line) => JSON.parse(line))
    assert.ok(events.some((entry) => entry.reason_code === "subagent_lifecycle_subagent_fallback_matched"))
    assert.ok(events.some((entry) => entry.reason_code === "subagent_lifecycle_after_ambiguous_forced_completed"))
  } finally {
    rmSync(directory, { recursive: true, force: true })
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    }
  }
})

test("subagent-lifecycle-supervisor reconciles child sessions from metadata-only links", async () => {
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

    const beforeOutput = { args: { subagent_type: "explore", prompt: "first" } }
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-life-metadata-link" },
      beforeOutput,
    )
    const delegation = beforeOutput.metadata?.gateway?.delegation

    await plugin.event({
      event: {
        type: "session.created",
        properties: {
          info: {
            id: "child-life-metadata-link",
            parentID: "session-life-metadata-link",
            title: "delegated child without trace title",
            metadata: {
              gateway: {
                delegation,
              },
            },
          },
        },
      },
    })
    await plugin.event({
      event: {
        type: "message.updated",
        properties: {
          info: {
            role: "assistant",
            sessionID: "child-life-metadata-link",
            time: { completed: Date.now() },
          },
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-life-metadata-link" },
      { args: { subagent_type: "explore", prompt: "second" } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("subagent-lifecycle-supervisor writes after-event fallback audit to the payload directory", async () => {
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  const rootDirectory = mkdtempSync(join(tmpdir(), "gateway-subagent-lifecycle-root-"))
  const eventDirectory = mkdtempSync(join(tmpdir(), "gateway-subagent-lifecycle-events-"))
  try {
    const hook = createSubagentLifecycleSupervisorHook({
      directory: rootDirectory,
      enabled: true,
      maxRetriesPerSession: 3,
      staleRunningMs: 60000,
      blockOnExhausted: true,
    })

    await hook.event("tool.execute.before", {
      input: { tool: "task", sessionID: "session-life-event-dir" },
      output: { args: { subagent_type: "explore", prompt: "first" } },
      directory: eventDirectory,
    })
    await hook.event("tool.execute.before", {
      input: { tool: "task", sessionID: "session-life-event-dir" },
      output: { args: { subagent_type: "strategic-planner", prompt: "second" } },
      directory: eventDirectory,
    })
    await hook.event("tool.execute.after", {
      input: { tool: "task", sessionID: "session-life-event-dir" },
      output: {
        output: `done

[agent-context-shaper] delegation context
- subagent: strategic-planner
- recommended_category: deep`,
      },
      directory: eventDirectory,
    })

    const events = readFileSync(join(eventDirectory, ".opencode", "gateway-events.jsonl"), "utf-8")
      .split(/\n+/)
      .filter(Boolean)
      .map((line) => JSON.parse(line))
    assert.ok(events.some((entry) => entry.reason_code === "subagent_lifecycle_subagent_fallback_matched"))
  } finally {
    rmSync(rootDirectory, { recursive: true, force: true })
    rmSync(eventDirectory, { recursive: true, force: true })
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    }
  }
})
