import assert from "node:assert/strict"
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { setTimeout as delay } from "node:timers/promises"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { createDelegationConcurrencyGuardHook } from "../dist/hooks/delegation-concurrency-guard/index.js"

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


test("default before-hook failure rolls back reviewer reservation state", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-delegation-concurrency-"))
  try {
    const specsDir = join(directory, "agent", "specs")
    mkdirSync(specsDir, { recursive: true })
    writeFileSync(
      join(specsDir, "reviewer.json"),
      JSON.stringify({
        name: "reviewer",
        metadata: {
          default_category: "critical",
          cost_tier: "expensive",
          allowed_tools: ["read", "glob", "grep", "list"],
          denied_tools: ["bash", "write", "edit", "task", "webfetch", "todowrite", "todoread"],
        },
      }),
      "utf-8",
    )

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: [
            "delegation-concurrency-guard",
            "subagent-lifecycle-supervisor",
            "subagent-telemetry-timeline",
            "agent-denied-tool-enforcer",
          ],
          disabled: [],
        },
        delegationConcurrencyGuard: {
          enabled: true,
          maxTotalConcurrent: 4,
          maxExpensiveConcurrent: 1,
          maxDeepConcurrent: 2,
          maxCriticalConcurrent: 1,
        },
        subagentLifecycleSupervisor: {
          enabled: true,
          maxRetriesPerSession: 3,
          staleRunningMs: 60000,
          blockOnExhausted: true,
        },
        subagentTelemetryTimeline: {
          enabled: true,
          maxTimelineEntries: 20,
          persistState: false,
          stateFile: ".opencode/test-runtime-state.json",
          stateMaxEntries: 20,
        },
      },
    })

    await assert.rejects(
      () =>
        plugin["tool.execute.before"](
          { tool: "task", sessionID: "session-concurrency-before-error" },
          {
            args: {
              subagent_type: "reviewer",
              prompt: "Use functions.bash to run git status.",
              description: "Trigger read-only subagent denial.",
            },
          },
        ),
      /denied tools/i,
    )

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-concurrency-before-error" },
      {
        args: {
          subagent_type: "reviewer",
          prompt: "Review the touched diff for correctness.",
          description: "Safe follow-up reviewer run.",
        },
      },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("delegation-concurrency-guard records fallback-match and stale-prune audit reasons", async () => {
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  const fallbackDirectory = mkdtempSync(join(tmpdir(), "gateway-delegation-concurrency-"))
  const staleDirectory = mkdtempSync(join(tmpdir(), "gateway-delegation-concurrency-"))
  try {
    const fallbackPlugin = GatewayCorePlugin({
      directory: fallbackDirectory,
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
          staleReservationMs: 1,
        },
      },
    })

    await fallbackPlugin["tool.execute.before"](
      { tool: "task", sessionID: "session-concurrency-fallback-audit" },
      { args: { subagent_type: "explore", prompt: "first" } },
    )
    await fallbackPlugin["tool.execute.before"](
      { tool: "task", sessionID: "session-concurrency-fallback-audit" },
      { args: { subagent_type: "strategic-planner", prompt: "second" } },
    )
    await fallbackPlugin["tool.execute.after"](
      { tool: "task", sessionID: "session-concurrency-fallback-audit" },
      {
        output: `done

[agent-context-shaper] delegation context
- subagent: strategic-planner
- recommended_category: deep`,
      },
    )

    const stalePlugin = GatewayCorePlugin({
      directory: staleDirectory,
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
          staleReservationMs: 0,
        },
        subagentLifecycleSupervisor: {
          enabled: true,
          maxRetriesPerSession: 3,
          staleRunningMs: 1,
          blockOnExhausted: true,
        },
      },
    })

    await stalePlugin["tool.execute.before"](
      { tool: "task", sessionID: "session-concurrency-stale-audit" },
      { args: { subagent_type: "explore", prompt: "third" } },
    )
    await stalePlugin["tool.execute.before"](
      { tool: "task", sessionID: "session-concurrency-stale-audit" },
      { args: { subagent_type: "strategic-planner", prompt: "fourth" } },
    )
    await stalePlugin["tool.execute.after"](
      { tool: "task", sessionID: "session-concurrency-stale-audit" },
      { output: "done" },
    )
    await delay(5)
    await stalePlugin["tool.execute.before"](
      { tool: "task", sessionID: "session-concurrency-stale-audit" },
      { args: { subagent_type: "reviewer", prompt: "fifth" } },
    )

    const fallbackEvents = readFileSync(join(fallbackDirectory, ".opencode", "gateway-events.jsonl"), "utf-8")
      .split(/\n+/)
      .filter(Boolean)
      .map((line) => JSON.parse(line))
    const staleEvents = readFileSync(join(staleDirectory, ".opencode", "gateway-events.jsonl"), "utf-8")
      .split(/\n+/)
      .filter(Boolean)
      .map((line) => JSON.parse(line))
    assert.ok(
      fallbackEvents.some((entry) => entry.reason_code === "delegation_concurrency_subagent_fallback_matched"),
    )
    assert.ok(staleEvents.some((entry) => entry.reason_code === "delegation_concurrency_stale_pruned"))
  } finally {
    rmSync(fallbackDirectory, { recursive: true, force: true })
    rmSync(staleDirectory, { recursive: true, force: true })
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    }
  }
})

test("delegation-concurrency-guard writes after-event fallback audit to the payload directory", async () => {
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  const rootDirectory = mkdtempSync(join(tmpdir(), "gateway-delegation-concurrency-root-"))
  const eventDirectory = mkdtempSync(join(tmpdir(), "gateway-delegation-concurrency-events-"))
  try {
    const hook = createDelegationConcurrencyGuardHook({
      directory: rootDirectory,
      enabled: true,
      maxTotalConcurrent: 2,
      maxExpensiveConcurrent: 2,
      maxDeepConcurrent: 2,
      maxCriticalConcurrent: 1,
      staleReservationMs: 60000,
    })

    await hook.event("tool.execute.before", {
      input: { tool: "task", sessionID: "session-concurrency-event-dir" },
      output: { args: { subagent_type: "explore", prompt: "first" } },
      directory: eventDirectory,
    })
    await hook.event("tool.execute.before", {
      input: { tool: "task", sessionID: "session-concurrency-event-dir" },
      output: { args: { subagent_type: "strategic-planner", prompt: "second" } },
      directory: eventDirectory,
    })
    await hook.event("tool.execute.after", {
      input: { tool: "task", sessionID: "session-concurrency-event-dir" },
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
    assert.ok(events.some((entry) => entry.reason_code === "delegation_concurrency_subagent_fallback_matched"))
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
