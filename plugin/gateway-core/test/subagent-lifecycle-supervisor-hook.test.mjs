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


test("subagent-lifecycle-supervisor auto-recovers idle child sessions in the parent turn", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-subagent-lifecycle-"))
  try {
    let promptCalls = 0
    let lastPromptBody = null
    const hook = createSubagentLifecycleSupervisorHook({
      directory,
      enabled: true,
      maxRetriesPerSession: 3,
      staleRunningMs: 0,
      blockOnExhausted: true,
      client: {
        session: {
          async messages() {
            return {
              data: [],
            }
          },
          async promptAsync(args) {
            promptCalls += 1
            lastPromptBody = args.body
          },
        },
      },
    })

    const beforeOutput = {
      args: { subagent_type: "reviewer", prompt: "[DELEGATION TRACE idle-trace] review" },
    }
    await hook.event("tool.execute.before", {
      input: { tool: "task", sessionID: "session-life-idle-parent" },
      output: beforeOutput,
      directory,
    })

    await hook.event("session.created", {
      properties: {
        info: {
          id: "child-idle-1",
          parentID: "session-life-idle-parent",
          title: "[DELEGATION TRACE idle-trace]\n\nIdle child (@reviewer subagent)",
          metadata: beforeOutput.metadata,
        },
      },
    })

    await hook.event("session.idle", {
      properties: {
        sessionID: "child-idle-1",
      },
      directory,
    })

    assert.equal(promptCalls, 1)
    assert.match(lastPromptBody?.parts?.[0]?.text ?? "", /delegated reviewer child stalled - continuing in parent turn/i)
    assert.match(lastPromptBody?.parts?.[0]?.text ?? "", /child_session: child-idle-1/)

    await hook.event("tool.execute.before", {
      input: { tool: "task", sessionID: "session-life-idle-parent" },
      output: { args: { subagent_type: "reviewer", prompt: "[DELEGATION TRACE idle-trace] retry" } },
      directory,
    })
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("subagent-lifecycle-supervisor forces idle-child recovery even when parent turn is incomplete", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-subagent-lifecycle-"))
  try {
    let promptCalls = 0
    const hook = createSubagentLifecycleSupervisorHook({
      directory,
      enabled: true,
      maxRetriesPerSession: 3,
      staleRunningMs: 0,
      blockOnExhausted: true,
      client: {
        session: {
          async messages(args) {
            if (args.path.id === "session-life-idle-parent-2") {
              return {
                data: [
                  {
                    info: {
                      role: "assistant",
                      time: {},
                    },
                  },
                ],
              }
            }
            return {
              data: [],
            }
          },
          async promptAsync() {
            promptCalls += 1
          },
        },
      },
    })

    const beforeOutput = {
      args: { subagent_type: "reviewer", prompt: "[DELEGATION TRACE idle-trace-2] review" },
    }
    await hook.event("tool.execute.before", {
      input: { tool: "task", sessionID: "session-life-idle-parent-2" },
      output: beforeOutput,
      directory,
    })

    await hook.event("session.created", {
      properties: {
        info: {
          id: "child-idle-2",
          parentID: "session-life-idle-parent-2",
          title: "[DELEGATION TRACE idle-trace-2]\n\nIdle child (@reviewer subagent)",
          metadata: beforeOutput.metadata,
        },
      },
    })

    await hook.event("session.idle", {
      properties: {
        sessionID: "child-idle-2",
      },
      directory,
    })

    assert.equal(promptCalls, 1)
    await hook.event("tool.execute.before", {
      input: { tool: "task", sessionID: "session-life-idle-parent-2" },
      output: { args: { subagent_type: "reviewer", prompt: "[DELEGATION TRACE idle-trace-2] retry" } },
      directory,
    })
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("subagent-lifecycle-supervisor skips idle recovery for fresh active child sessions", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-subagent-lifecycle-"))
  try {
    let promptCalls = 0
    const hook = createSubagentLifecycleSupervisorHook({
      directory,
      enabled: true,
      maxRetriesPerSession: 3,
      staleRunningMs: 60000,
      blockOnExhausted: true,
      client: {
        session: {
          async messages() {
            return {
              data: [
                {
                  info: { role: "assistant", time: {} },
                  parts: [{ type: "text", text: "Still analyzing the repository." }],
                },
              ],
            }
          },
          async promptAsync() {
            promptCalls += 1
          },
        },
      },
    })

    const beforeOutput = {
      args: { subagent_type: "reviewer", prompt: "[DELEGATION TRACE active-idle-trace] review" },
    }
    await hook.event("tool.execute.before", {
      input: { tool: "task", sessionID: "session-life-idle-active-parent" },
      output: beforeOutput,
      directory,
    })
    await hook.event("session.created", {
      properties: {
        info: {
          id: "child-idle-active-1",
          parentID: "session-life-idle-active-parent",
          title: "[DELEGATION TRACE active-idle-trace]\n\nIdle child (@reviewer subagent)",
          metadata: beforeOutput.metadata,
        },
      },
    })
    await hook.event("session.idle", {
      properties: { sessionID: "child-idle-active-1" },
      directory,
    })

    assert.equal(promptCalls, 0)
    await assert.rejects(
      () =>
        hook.event("tool.execute.before", {
          input: { tool: "task", sessionID: "session-life-idle-active-parent" },
          output: { args: { subagent_type: "reviewer", prompt: "[DELEGATION TRACE active-idle-trace] retry" } },
          directory,
        }),
      /already running/i,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("subagent-lifecycle-supervisor reconciles completed idle child without parent recovery", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-subagent-lifecycle-"))
  try {
    let promptCalls = 0
    const hook = createSubagentLifecycleSupervisorHook({
      directory,
      enabled: true,
      maxRetriesPerSession: 3,
      staleRunningMs: 60000,
      blockOnExhausted: true,
      client: {
        session: {
          async messages() {
            return {
              data: [
                {
                  info: { role: "assistant", time: { completed: Date.now() } },
                },
              ],
            }
          },
          async promptAsync() {
            promptCalls += 1
          },
        },
      },
    })

    const beforeOutput = {
      args: { subagent_type: "reviewer", prompt: "[DELEGATION TRACE completed-idle-trace] review" },
    }
    await hook.event("tool.execute.before", {
      input: { tool: "task", sessionID: "session-life-idle-completed-parent" },
      output: beforeOutput,
      directory,
    })
    await hook.event("session.created", {
      properties: {
        info: {
          id: "child-idle-completed-1",
          parentID: "session-life-idle-completed-parent",
          title: "[DELEGATION TRACE completed-idle-trace]\n\nIdle child (@reviewer subagent)",
          metadata: beforeOutput.metadata,
        },
      },
    })
    await hook.event("session.idle", {
      properties: { sessionID: "child-idle-completed-1" },
      directory,
    })

    assert.equal(promptCalls, 0)
    await hook.event("tool.execute.before", {
      input: { tool: "task", sessionID: "session-life-idle-completed-parent" },
      output: { args: { subagent_type: "reviewer", prompt: "[DELEGATION TRACE completed-idle-trace] retry" } },
      directory,
    })
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
