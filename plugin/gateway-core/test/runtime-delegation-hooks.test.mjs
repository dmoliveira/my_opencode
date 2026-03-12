import assert from "node:assert/strict"
import { dirname, join } from "node:path"
import test from "node:test"
import { fileURLToPath } from "node:url"

import { createAgentDeniedToolEnforcerHook } from "../dist/hooks/agent-denied-tool-enforcer/index.js"
import { createAgentDiscoverabilityInjectorHook } from "../dist/hooks/agent-discoverability-injector/index.js"
import { createAgentModelResolverHook } from "../dist/hooks/agent-model-resolver/index.js"
import { createDelegationOutcomeLearnerHook } from "../dist/hooks/delegation-outcome-learner/index.js"
import { createHookSemanticBridgeHook } from "../dist/hooks/hook-semantic-bridge/index.js"
import { createSubagentTelemetryTimelineHook } from "../dist/hooks/subagent-telemetry-timeline/index.js"
import { createSubagentLifecycleSupervisorHook } from "../dist/hooks/subagent-lifecycle-supervisor/index.js"
import { createDelegationConcurrencyGuardHook } from "../dist/hooks/delegation-concurrency-guard/index.js"
import { resolveHookOrder } from "../dist/hooks/registry.js"
import { getRecentDelegationOutcomes } from "../dist/hooks/shared/delegation-runtime-state.js"

const REPO_DIRECTORY = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..")

function createRuntimeDelegationHooks() {
  return [
    createDelegationConcurrencyGuardHook({
      directory: REPO_DIRECTORY,
      enabled: true,
      maxTotalConcurrent: 5,
      maxExpensiveConcurrent: 2,
      maxDeepConcurrent: 5,
      maxCriticalConcurrent: 1,
      staleReservationMs: 60000,
    }),
    createSubagentLifecycleSupervisorHook({
      directory: REPO_DIRECTORY,
      enabled: true,
      maxRetriesPerSession: 3,
      staleRunningMs: 60000,
      blockOnExhausted: true,
    }),
    createSubagentTelemetryTimelineHook({
      directory: REPO_DIRECTORY,
      enabled: true,
      maxTimelineEntries: 100,
      persistState: false,
      stateFile: ".opencode/test-runtime-state.json",
      stateMaxEntries: 100,
    }),
  ]
}

async function dispatchRuntimeDelegationHooks(hooks, type, payload) {
  for (const hook of hooks) {
    await hook.event(type, payload)
  }
}

test("delegation confidence gate overrides low-confidence explicit subagent", async () => {
  const hook = createAgentModelResolverHook({
    directory: REPO_DIRECTORY,
    enabled: true,
    defaultOverrideDelta: 1,
    defaultIntentThreshold: 1,
    agentPolicyOverrides: {},
  })
  const output = {
    args: {
      subagent_type: "explore",
      prompt: "Gather official docs and upstream reference for framework API behavior.",
      description: "Need external evidence.",
    },
  }
  await hook.event("tool.execute.before", {
    input: { tool: "task", sessionID: "session-confidence-1" },
    output,
  })
  assert.equal(output.args.subagent_type, "librarian")
  assert.match(output.args.prompt, /\[DELEGATION ROUTER(?:\s+[^\]]+)?\]/)
})

test("agent discoverability injector appends catalog hint only after routing rewrite", async () => {
  const resolver = createAgentModelResolverHook({
    directory: REPO_DIRECTORY,
    enabled: true,
    defaultOverrideDelta: 1,
    defaultIntentThreshold: 1,
    agentPolicyOverrides: {},
  })
  const discoverability = createAgentDiscoverabilityInjectorHook({
    directory: REPO_DIRECTORY,
    enabled: true,
    cooldownMs: 60000,
  })
  const output = {
    args: {
      prompt: "Find implementation location for auth token refresh flow.",
      description: "Map codebase patterns quickly.",
    },
  }
  const payload = {
    input: { tool: "task", sessionID: "session-discoverability-1" },
    output,
  }
  await resolver.event("tool.execute.before", payload)
  await discoverability.event("tool.execute.before", payload)
  assert.match(output.args.prompt, /\[DELEGATION ROUTER(?:\s+[^\]]+)?\]/)
  assert.match(output.args.prompt, /\/agent-catalog explain explore/)
})

test("delegation outcome learner adapts risky category after repeated failures", async () => {
  const timelineHook = createSubagentTelemetryTimelineHook({
    directory: REPO_DIRECTORY,
    enabled: true,
    maxTimelineEntries: 100,
    persistState: false,
    stateFile: ".opencode/test-runtime-state.json",
    stateMaxEntries: 100,
  })
  const learnerHook = createDelegationOutcomeLearnerHook({
    directory: REPO_DIRECTORY,
    enabled: true,
    windowMs: 120000,
    minSamples: 2,
    highFailureRate: 0.5,
    agentPolicyOverrides: {},
  })

  const firstOutput = { args: { subagent_type: "reviewer", category: "critical", prompt: "first" } }
  await timelineHook.event("tool.execute.before", {
    input: { tool: "task", sessionID: "session-learn-1" },
    output: firstOutput,
  })
  await timelineHook.event("tool.execute.after", {
    input: { tool: "task", sessionID: "session-learn-1" },
    output: { metadata: firstOutput.metadata, output: "[ERROR] Failed delegation" },
  })

  const secondOutput = { args: { subagent_type: "reviewer", category: "critical", prompt: "second" } }
  await timelineHook.event("tool.execute.before", {
    input: { tool: "task", sessionID: "session-learn-2" },
    output: secondOutput,
  })
  await timelineHook.event("tool.execute.after", {
    input: { tool: "task", sessionID: "session-learn-2" },
    output: { metadata: secondOutput.metadata, output: "[ERROR] Failed delegation" },
  })

  const output = {
    args: {
      subagent_type: "reviewer",
      category: "critical",
      prompt: "third",
      description: "third description",
    },
  }
  await learnerHook.event("tool.execute.before", {
    input: { tool: "task", sessionID: "session-learn-3" },
    output,
  })
  assert.equal(output.args.category, "balanced")
  assert.match(output.args.prompt, /\[DELEGATION LEARNER\]/)
})

test("tool surface enforcer v2 blocks denied tool and suggests allowed tool", async () => {
  const hook = createAgentDeniedToolEnforcerHook({ directory: REPO_DIRECTORY, enabled: true })
  await assert.rejects(
    () =>
      hook.event("tool.execute.before", {
        input: { tool: "task", sessionID: "session-tool-enforcer-1" },
        output: {
          args: {
            subagent_type: "explore",
            prompt: "Use functions.bash to run git status.",
            description: "Need quick check",
          },
        },
      }),
    /Use allowed tool 'read' instead/i,
  )
})

test("hook semantic bridge maps upstream semantics to local runtime", async () => {
  const hook = createHookSemanticBridgeHook({ directory: REPO_DIRECTORY, enabled: true })
  const output = {
    args: {
      prompt: "Use sisyphus and start-work hook semantics for this task.",
      description: "Need runtime-fallback behavior.",
    },
  }
  await hook.event("tool.execute.before", {
    input: { tool: "task", sessionID: "session-bridge-1" },
    output,
  })
  assert.match(output.args.prompt, /\[HOOK SEMANTIC BRIDGE\]/)
  assert.match(output.args.prompt, /sisyphus->orchestrator/)
})

test("discoverability injector respects cooldown window", async () => {
  const discoverability = createAgentDiscoverabilityInjectorHook({
    directory: REPO_DIRECTORY,
    enabled: true,
    cooldownMs: 3600000,
  })
  const payload = {
    input: { tool: "task", sessionID: "session-discoverability-cooldown" },
    output: {
      args: {
        subagent_type: "explore",
        prompt: "[DELEGATION ROUTER] inferred route",
        description: "first",
      },
    },
  }
  await discoverability.event("tool.execute.before", payload)
  const first = String(payload.output.args.prompt)
  await discoverability.event("tool.execute.before", payload)
  const second = String(payload.output.args.prompt)
  assert.equal((first.match(/\/agent-catalog/g) ?? []).length, 1)
  assert.equal((second.match(/\/agent-catalog/g) ?? []).length, 1)
})


test("subagent telemetry timeline records child run id metadata on normal path", async () => {
  const timelineHook = createSubagentTelemetryTimelineHook({
    directory: REPO_DIRECTORY,
    enabled: true,
    maxTimelineEntries: 100,
    persistState: false,
    stateFile: ".opencode/test-runtime-state.json",
    stateMaxEntries: 100,
  })

  const beforeOutput = {
    args: { subagent_type: "explore", category: "balanced", prompt: "telemetry child run" },
  }
  await timelineHook.event("tool.execute.before", {
    input: { tool: "task", sessionID: "session-telemetry-child-run" },
    output: beforeOutput,
  })

  const childRunId = beforeOutput.metadata?.gateway?.delegation?.childRunId
  assert.match(String(childRunId), /^subagent-run\//)

  await timelineHook.event("tool.execute.after", {
    input: { tool: "task", sessionID: "session-telemetry-child-run" },
    output: { metadata: beforeOutput.metadata, output: "done" },
  })

  const record = getRecentDelegationOutcomes(60000)
    .filter((item) => item.sessionId === "session-telemetry-child-run")
    .at(-1)
  assert.ok(record)
  assert.equal(record.childRunId, childRunId)
})


test("subagent telemetry timeline refreshes stale child run id metadata when trace changes", async () => {
  const timelineHook = createSubagentTelemetryTimelineHook({
    directory: REPO_DIRECTORY,
    enabled: true,
    maxTimelineEntries: 100,
    persistState: false,
    stateFile: ".opencode/test-runtime-state.json",
    stateMaxEntries: 100,
  })

  const beforeOutput = {
    args: {
      subagent_type: "explore",
      category: "balanced",
      prompt: "[DELEGATION TRACE trace-fresh] telemetry stale metadata",
    },
    metadata: {
      gateway: {
        delegation: {
          childRunId: "subagent-run/trace-stale",
          traceId: "trace-stale",
        },
      },
    },
  }
  await timelineHook.event("tool.execute.before", {
    input: { tool: "task", sessionID: "session-telemetry-stale-child-run" },
    output: beforeOutput,
  })

  const childRunId = beforeOutput.metadata?.gateway?.delegation?.childRunId
  assert.equal(childRunId, "subagent-run/trace-fresh")

  await timelineHook.event("tool.execute.after", {
    input: { tool: "task", sessionID: "session-telemetry-stale-child-run" },
    output: { metadata: beforeOutput.metadata, output: "done" },
  })

  const record = getRecentDelegationOutcomes(60000)
    .filter((item) => item.sessionId === "session-telemetry-stale-child-run")
    .at(-1)
  assert.ok(record)
  assert.equal(record.childRunId, childRunId)
  assert.equal(record.traceId, "trace-fresh")
})

test("subagent telemetry timeline refreshes child run id when legacy metadata omits trace id", async () => {
  const timelineHook = createSubagentTelemetryTimelineHook({
    directory: REPO_DIRECTORY,
    enabled: true,
    maxTimelineEntries: 100,
    persistState: false,
    stateFile: ".opencode/test-runtime-state.json",
    stateMaxEntries: 100,
  })

  const beforeOutput = {
    args: {
      subagent_type: "explore",
      category: "balanced",
      prompt: "[DELEGATION TRACE trace-legacy-refresh] telemetry legacy metadata",
    },
    metadata: {
      gateway: {
        delegation: {
          childRunId: "subagent-run/trace-legacy-stale",
        },
      },
    },
  }
  await timelineHook.event("tool.execute.before", {
    input: { tool: "task", sessionID: "session-telemetry-legacy-child-run" },
    output: beforeOutput,
  })

  const childRunId = beforeOutput.metadata?.gateway?.delegation?.childRunId
  assert.equal(childRunId, "subagent-run/trace-legacy-refresh")
  assert.equal(beforeOutput.metadata?.gateway?.delegation?.traceId, "trace-legacy-refresh")
})

test("subagent telemetry timeline normalizes malformed child run id to canonical trace-based identity", async () => {
  const timelineHook = createSubagentTelemetryTimelineHook({
    directory: REPO_DIRECTORY,
    enabled: true,
    maxTimelineEntries: 100,
    persistState: false,
    stateFile: ".opencode/test-runtime-state.json",
    stateMaxEntries: 100,
  })

  const beforeOutput = {
    args: {
      subagent_type: "explore",
      category: "balanced",
      prompt: "[DELEGATION TRACE trace-normalize-child-run] telemetry malformed child run",
    },
    metadata: {
      gateway: {
        delegation: {
          childRunId: "legacy-run-id",
          traceId: "trace-normalize-child-run",
        },
      },
    },
  }
  await timelineHook.event("tool.execute.before", {
    input: { tool: "task", sessionID: "session-telemetry-normalize-child-run" },
    output: beforeOutput,
  })

  assert.equal(
    beforeOutput.metadata?.gateway?.delegation?.childRunId,
    "subagent-run/trace-normalize-child-run",
  )
  assert.equal(beforeOutput.metadata?.gateway?.delegation?.traceId, "trace-normalize-child-run")
})

test("subagent telemetry timeline records outcome from child-run-only after metadata", async () => {
  const timelineHook = createSubagentTelemetryTimelineHook({
    directory: REPO_DIRECTORY,
    enabled: true,
    maxTimelineEntries: 100,
    persistState: false,
    stateFile: ".opencode/test-runtime-state.json",
    stateMaxEntries: 100,
  })

  const beforeOutput = {
    args: { subagent_type: "explore", category: "balanced", prompt: "telemetry child-run-only after" },
  }
  await timelineHook.event("tool.execute.before", {
    input: { tool: "task", sessionID: "session-telemetry-child-run-after" },
    output: beforeOutput,
  })

  const childRunId = beforeOutput.metadata?.gateway?.delegation?.childRunId
  await timelineHook.event("tool.execute.after", {
    input: { tool: "task", sessionID: "session-telemetry-child-run-after" },
    output: {
      metadata: {
        gateway: {
          delegation: {
            childRunId,
          },
        },
      },
      output: "done",
    },
  })

  const record = getRecentDelegationOutcomes(60000)
    .filter((item) => item.sessionId === "session-telemetry-child-run-after")
    .at(-1)
  assert.ok(record)
  assert.equal(record.childRunId, childRunId)
  assert.equal(record.traceId, String(childRunId).replace(/^subagent-run\//, ""))
})

test("subagent telemetry timeline skips outcome when after-event identity is missing", async () => {
  const timelineHook = createSubagentTelemetryTimelineHook({
    directory: REPO_DIRECTORY,
    enabled: true,
    maxTimelineEntries: 100,
    persistState: false,
    stateFile: ".opencode/test-runtime-state.json",
    stateMaxEntries: 100,
  })

  await timelineHook.event("tool.execute.before", {
    input: { tool: "task", sessionID: "session-telemetry-missing-identity" },
    output: { args: { subagent_type: "explore", category: "balanced", prompt: "telemetry missing identity" } },
  })

  await timelineHook.event("tool.execute.after", {
    input: { tool: "task", sessionID: "session-telemetry-missing-identity" },
    output: {
      output: "done\n\n[agent-context-shaper] delegation context\n- subagent: explore\n- recommended_category: balanced",
    },
  })

  const records = getRecentDelegationOutcomes(60000).filter(
    (item) => item.sessionId === "session-telemetry-missing-identity",
  )
  assert.equal(records.length, 0)
})

for (const scenario of [
  {
    count: 2,
    sessionID: "session-stress-two-subagents",
    completionOrder: [1, 0],
    agents: [
      { subagent_type: "explore", category: "quick", prompt: "stress alpha" },
      { subagent_type: "strategic-planner", category: "deep", prompt: "stress beta" },
    ],
    followUp: { subagent_type: "explore", category: "quick", prompt: "stress follow-up two" },
  },
  {
    count: 3,
    sessionID: "session-stress-three-subagents",
    completionOrder: [1, 2, 0],
    agents: [
      { subagent_type: "explore", category: "quick", prompt: "stress alpha" },
      { subagent_type: "librarian", category: "balanced", prompt: "stress gamma" },
      { subagent_type: "verifier", category: "quick", prompt: "stress delta" },
    ],
    followUp: { subagent_type: "librarian", category: "balanced", prompt: "stress follow-up three" },
  },
  {
    count: 4,
    sessionID: "session-stress-four-subagents",
    completionOrder: [2, 0, 3, 1],
    agents: [
      { subagent_type: "explore", category: "quick", prompt: "stress alpha" },
      { subagent_type: "strategic-planner", category: "deep", prompt: "stress beta" },
      { subagent_type: "librarian", category: "balanced", prompt: "stress gamma" },
      { subagent_type: "verifier", category: "quick", prompt: "stress delta" },
    ],
    followUp: { subagent_type: "verifier", category: "quick", prompt: "stress follow-up four" },
  },
  {
    count: 5,
    sessionID: "session-stress-five-subagents",
    completionOrder: [2, 4, 1, 3, 0],
    agents: [
      { subagent_type: "explore", category: "quick", prompt: "stress alpha" },
      { subagent_type: "strategic-planner", category: "deep", prompt: "stress beta" },
      { subagent_type: "librarian", category: "balanced", prompt: "stress gamma" },
      { subagent_type: "verifier", category: "quick", prompt: "stress delta" },
      { subagent_type: "reviewer", category: "critical", prompt: "stress epsilon" },
    ],
    followUp: { subagent_type: "reviewer", category: "critical", prompt: "stress follow-up five" },
  },
]) {
  test(`runtime delegation hooks sustain ${scenario.count} same-session subagents with varied completion order`, async () => {
    const hooks = createRuntimeDelegationHooks()
    const delegations = scenario.agents.map((args) => ({ args }))

    for (const output of delegations) {
      await dispatchRuntimeDelegationHooks(hooks, "tool.execute.before", {
        input: { tool: "task", sessionID: scenario.sessionID },
        output,
      })
    }

    for (const index of scenario.completionOrder) {
      await dispatchRuntimeDelegationHooks(hooks, "tool.execute.after", {
        input: { tool: "task", sessionID: scenario.sessionID },
        output: {
          metadata: delegations[index].metadata,
          output: "done",
        },
      })
    }

    const records = getRecentDelegationOutcomes(60000).filter(
      (item) => item.sessionId === scenario.sessionID,
    )
    assert.equal(records.length, scenario.count)
    assert.deepEqual(
      records.map((item) => item.subagentType).sort(),
      scenario.agents.map((item) => item.subagent_type).sort(),
    )
    assert.equal(new Set(records.map((item) => item.childRunId)).size, scenario.count)
    assert.ok(records.every((item) => item.status === "completed"))

    await dispatchRuntimeDelegationHooks(hooks, "tool.execute.before", {
      input: { tool: "task", sessionID: scenario.sessionID },
      output: { args: scenario.followUp },
    })
  })
}

test("default hook ordering runs concurrency guard before lifecycle and telemetry state hooks", async () => {
  const hooks = resolveHookOrder(
    [
      createSubagentLifecycleSupervisorHook({
        directory: REPO_DIRECTORY,
        enabled: true,
        maxRetriesPerSession: 3,
        staleRunningMs: 60000,
        blockOnExhausted: true,
      }),
      createSubagentTelemetryTimelineHook({
        directory: REPO_DIRECTORY,
        enabled: true,
        maxTimelineEntries: 10,
        persistState: false,
        stateFile: ".opencode/test-runtime-state.json",
        stateMaxEntries: 10,
      }),
      createDelegationConcurrencyGuardHook({
        directory: REPO_DIRECTORY,
        enabled: true,
        maxTotalConcurrent: 1,
        maxExpensiveConcurrent: 1,
        maxDeepConcurrent: 1,
        maxCriticalConcurrent: 1,
        staleReservationMs: 60000,
      }),
    ],
    [],
    [],
  )
  const ids = hooks.map((hook) => hook.id)
  assert.deepEqual(ids, [
    "delegation-concurrency-guard",
    "subagent-lifecycle-supervisor",
    "subagent-telemetry-timeline",
  ])
})
