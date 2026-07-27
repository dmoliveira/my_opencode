import assert from "node:assert/strict"
import { mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import {
  delegationTerminalChildSessionId,
} from "../dist/hooks/shared/delegation-child-session.js"
import {
  DELEGATION_HOOK_EVENTS,
  dispatchDelegationTerminalHooks,
} from "../dist/hooks/shared/delegation-terminal-dispatch.js"
import { createDelegationConcurrencyGuardHook } from "../dist/hooks/delegation-concurrency-guard/index.js"
import { createSubagentLifecycleSupervisorHook } from "../dist/hooks/subagent-lifecycle-supervisor/index.js"
import { createSubagentTelemetryTimelineHook } from "../dist/hooks/subagent-telemetry-timeline/index.js"

const HOOK_IDS = [
  "delegation-concurrency-guard",
  "subagent-lifecycle-supervisor",
  "subagent-telemetry-timeline",
]

const DELETION_REASONS = {
  "delegation-concurrency-guard": "delegation_concurrency_child_deleted_released",
  "subagent-lifecycle-supervisor": "subagent_lifecycle_child_deleted_reconciled",
  "subagent-telemetry-timeline": "subagent_telemetry_child_deleted_reconciled",
}

function permutations(items) {
  if (items.length <= 1) return [items]
  return items.flatMap((item, index) =>
    permutations(items.filter((_, itemIndex) => itemIndex !== index)).map((rest) => [item, ...rest]),
  )
}

function createPlugin(directory, order = HOOK_IDS, disabled = [], maxTotalConcurrent = 1) {
  return GatewayCorePlugin({
    directory,
    config: {
      hooks: { enabled: true, order, disabled },
      delegationConcurrencyGuard: {
        enabled: true,
        maxTotalConcurrent,
        maxExpensiveConcurrent: maxTotalConcurrent,
        maxDeepConcurrent: maxTotalConcurrent,
        maxCriticalConcurrent: maxTotalConcurrent,
        staleReservationMs: 60000,
      },
      subagentLifecycleSupervisor: {
        enabled: true,
        maxRetriesPerSession: 3,
        staleRunningMs: 60000,
        blockOnExhausted: true,
      },
      subagentTelemetryTimeline: {
        enabled: true,
        maxTimelineEntries: 100,
        persistState: false,
        stateFile: ".opencode/test-delegation-terminal-state.json",
        stateMaxEntries: 100,
      },
    },
  })
}

async function reserveAndLink(plugin, suffix, subagentType = "explore") {
  const parentSessionId = `parent-${suffix}`
  const childSessionId = `child-${suffix}`
  const traceId = `trace-${suffix}`
  const output = {
    args: {
      subagent_type: subagentType,
      category: subagentType === "reviewer" ? "critical" : "quick",
      prompt: `[DELEGATION TRACE ${traceId}] delegated work`,
      description: `delegation ${suffix}`,
    },
  }
  await plugin["tool.execute.before"](
    { tool: "task", sessionID: parentSessionId },
    output,
  )
  const delegation = output.metadata?.gateway?.delegation
  assert.ok(delegation)
  await plugin.event({
    event: {
      type: "session.created",
      properties: {
        info: {
          id: childSessionId,
          parentID: parentSessionId,
          title: `[DELEGATION TRACE ${traceId}] ${subagentType} child`,
          metadata: { gateway: { delegation } },
        },
      },
    },
  })
  return { parentSessionId, childSessionId, traceId, delegation }
}

function auditEntries(directory) {
  const path = join(directory, ".opencode", "gateway-events.jsonl")
  return readFileSync(path, "utf8")
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line))
}

async function withAudit(run) {
  const previous = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  try {
    await run()
  } finally {
    if (previous === undefined) delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    else process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previous
  }
}

test("delegation terminal extractor excludes idle and progress", () => {
  assert.equal(
    delegationTerminalChildSessionId("session.idle", {
      properties: { sessionID: "child-idle" },
    }),
    "",
  )
  assert.equal(
    delegationTerminalChildSessionId("message.updated", {
      properties: { info: { role: "assistant", sessionID: "child-progress", time: {} } },
    }),
    "",
  )
  assert.equal(
    delegationTerminalChildSessionId("message.updated", {
      properties: {
        info: { role: "assistant", sessionID: "child-complete", time: { completed: 1 } },
      },
    }),
    "child-complete",
  )
  assert.equal(
    delegationTerminalChildSessionId("session.deleted", {
      properties: { info: { id: "child-deleted" } },
    }),
    "child-deleted",
  )
})

test("delegation hooks declare exact event subscriptions", () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-terminal-events-"))
  try {
    const hooks = [
      createDelegationConcurrencyGuardHook({
        directory,
        enabled: true,
        maxTotalConcurrent: 1,
        maxExpensiveConcurrent: 1,
        maxDeepConcurrent: 1,
        maxCriticalConcurrent: 1,
        staleReservationMs: 60000,
      }),
      createSubagentLifecycleSupervisorHook({
        directory,
        enabled: true,
        maxRetriesPerSession: 3,
        staleRunningMs: 60000,
        blockOnExhausted: true,
      }),
      createSubagentTelemetryTimelineHook({
        directory,
        enabled: true,
        maxTimelineEntries: 100,
        persistState: false,
        stateFile: ".opencode/test-state.json",
        stateMaxEntries: 100,
      }),
    ]
    for (const hook of hooks) assert.deepEqual(hook.events, DELEGATION_HOOK_EVENTS)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("deletion fans out through every consumer in all six orders", async () => {
  await withAudit(async () => {
    for (const [index, order] of permutations(HOOK_IDS).entries()) {
      const directory = mkdtempSync(join(tmpdir(), `gateway-terminal-order-${index}-`))
      try {
        const plugin = createPlugin(directory, order)
        const linked = await reserveAndLink(plugin, `order-${index}`)
        await plugin.event({
          event: {
            type: "session.deleted",
            properties: { info: { id: linked.childSessionId } },
          },
        })
        const entries = auditEntries(directory).filter((entry) => entry.trace_id === linked.traceId)
        for (const reason of Object.values(DELETION_REASONS)) {
          assert.equal(entries.filter((entry) => entry.reason_code === reason).length, 1)
        }
        await plugin["tool.execute.before"](
          { tool: "task", sessionID: linked.parentSessionId },
          {
            args: {
              subagent_type: "explore",
              category: "quick",
              prompt: `[DELEGATION TRACE followup-${index}] follow-up`,
            },
          },
        )
      } finally {
        rmSync(directory, { recursive: true, force: true })
      }
    }
  })
})

test("deletion cleanup works with each consumer disabled", async () => {
  await withAudit(async () => {
    for (const disabledHook of HOOK_IDS) {
      const directory = mkdtempSync(join(tmpdir(), "gateway-terminal-disabled-"))
      try {
        const plugin = createPlugin(directory, HOOK_IDS, [disabledHook])
        const linked = await reserveAndLink(plugin, `disabled-${disabledHook}`)
        await plugin.event({
          event: {
            type: "session.deleted",
            properties: { info: { id: linked.childSessionId } },
          },
        })
        const entries = auditEntries(directory).filter((entry) => entry.trace_id === linked.traceId)
        for (const hookId of HOOK_IDS) {
          const expected = hookId === disabledHook ? 0 : 1
          assert.equal(
            entries.filter((entry) => entry.reason_code === DELETION_REASONS[hookId]).length,
            expected,
          )
        }
      } finally {
        rmSync(directory, { recursive: true, force: true })
      }
    }
  })
})

test("completed message wins and later deletion is idempotent", async () => {
  await withAudit(async () => {
    const directory = mkdtempSync(join(tmpdir(), "gateway-terminal-message-"))
    try {
      const plugin = createPlugin(directory)
      const linked = await reserveAndLink(plugin, "message-first")
      await plugin.event({
        event: {
          type: "message.updated",
          properties: {
            info: {
              role: "assistant",
              sessionID: linked.childSessionId,
              time: { completed: Date.now() },
            },
          },
        },
      })
      await plugin.event({
        event: {
          type: "session.deleted",
          properties: { info: { id: linked.childSessionId } },
        },
      })
      const entries = auditEntries(directory).filter((entry) => entry.trace_id === linked.traceId)
      const messageReasons = [
        "delegation_concurrency_child_message_completed_released",
        "subagent_lifecycle_child_message_completed_reconciled",
        "subagent_telemetry_child_message_completed_reconciled",
      ]
      for (const reason of messageReasons) {
        assert.equal(entries.filter((entry) => entry.reason_code === reason).length, 1)
      }
      for (const reason of Object.values(DELETION_REASONS)) {
        assert.equal(entries.filter((entry) => entry.reason_code === reason).length, 0)
      }
    } finally {
      rmSync(directory, { recursive: true, force: true })
    }
  })
})

test("interleaved, duplicate, unknown, and parent deletions remain isolated", async () => {
  await withAudit(async () => {
    const directory = mkdtempSync(join(tmpdir(), "gateway-terminal-isolation-"))
    try {
      const plugin = createPlugin(directory, HOOK_IDS, [], 2)
      const first = await reserveAndLink(plugin, "interleaved-a")
      const second = await reserveAndLink(plugin, "interleaved-b", "strategic-planner")
      for (const sessionId of ["unknown-child", first.childSessionId, first.childSessionId, second.childSessionId, first.parentSessionId]) {
        await plugin.event({
          event: { type: "session.deleted", properties: { info: { id: sessionId } } },
        })
      }
      const entries = auditEntries(directory)
      for (const linked of [first, second]) {
        const traceEntries = entries.filter((entry) => entry.trace_id === linked.traceId)
        for (const reason of Object.values(DELETION_REASONS)) {
          assert.equal(traceEntries.filter((entry) => entry.reason_code === reason).length, 1)
        }
      }
    } finally {
      rmSync(directory, { recursive: true, force: true })
    }
  })
})

test("idle active, probe-failed, and recent-unknown states retain lifecycle work", async () => {
  const scenarios = [
    {
      name: "active",
      messages: async () => ({
        data: [{ info: { role: "assistant", time: {} }, parts: [{ type: "text", text: "working" }] }],
      }),
    },
    { name: "probe-failed", messages: async () => { throw new Error("probe failed") } },
    { name: "recent-unknown", messages: async () => ({ data: [] }) },
  ]
  for (const scenario of scenarios) {
    const directory = mkdtempSync(join(tmpdir(), `gateway-terminal-idle-${scenario.name}-`))
    try {
      const hook = createSubagentLifecycleSupervisorHook({
        directory,
        enabled: true,
        maxRetriesPerSession: 3,
        staleRunningMs: 60000,
        blockOnExhausted: true,
        client: { session: { messages: scenario.messages } },
      })
      const traceId = `idle-${scenario.name}-trace`
      const output = {
        args: {
          subagent_type: "reviewer",
          prompt: `[DELEGATION TRACE ${traceId}] review`,
        },
      }
      await hook.event("tool.execute.before", {
        input: { tool: "task", sessionID: `idle-${scenario.name}-parent` },
        output,
        directory,
      })
      await hook.event("session.created", {
        properties: {
          info: {
            id: `idle-${scenario.name}-child`,
            parentID: `idle-${scenario.name}-parent`,
            title: `[DELEGATION TRACE ${traceId}] child`,
            metadata: output.metadata,
          },
        },
      })
      await hook.event("session.idle", {
        properties: { sessionID: `idle-${scenario.name}-child` },
        directory,
      })
      await assert.rejects(
        () =>
          hook.event("tool.execute.before", {
            input: { tool: "task", sessionID: `idle-${scenario.name}-parent` },
            output: {
              args: {
                subagent_type: "reviewer",
                prompt: `[DELEGATION TRACE ${traceId}] retry`,
              },
            },
            directory,
          }),
        /already running/i,
      )
    } finally {
      rmSync(directory, { recursive: true, force: true })
    }
  }
})

test("terminal coordinator preserves first fatal and always cleans up", async () => {
  const firstFatal = new Error("first fatal")
  const laterFatal = new Error("later fatal")
  const calls = []
  let cleanupCalls = 0
  const hooks = [
    { id: "noncritical", priority: 1, async event() {} },
    { id: "blocked", priority: 2, async event() {} },
    { id: "throwing", priority: 3, async event() {} },
  ]
  await assert.rejects(
    () =>
      dispatchDelegationTerminalHooks({
        hooks,
        dispatch: async (hook) => {
          calls.push(hook.id)
          if (hook.id === "noncritical") {
            return { ok: false, critical: false, blocked: false, error: new Error("ignored") }
          }
          if (hook.id === "blocked") {
            return { ok: false, critical: false, blocked: true, error: firstFatal }
          }
          throw laterFatal
        },
        cleanup: () => {
          cleanupCalls += 1
        },
      }),
    (error) => error === firstFatal,
  )
  assert.deepEqual(calls, ["noncritical", "blocked", "throwing"])
  assert.equal(cleanupCalls, 1)
})
