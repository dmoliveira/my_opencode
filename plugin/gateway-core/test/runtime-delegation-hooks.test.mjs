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

test("agent model resolver applies enforce-mode LLM route decision for explicit low-confidence route", async () => {
  const hook = createAgentModelResolverHook({
    directory: REPO_DIRECTORY,
    enabled: true,
    defaultOverrideDelta: 99,
    defaultIntentThreshold: 99,
    agentPolicyOverrides: {},
    decisionRuntime: {
      config: {
        enabled: true,
        mode: "enforce",
        command: "opencode",
        model: "openai/gpt-5.1-codex-mini",
        timeoutMs: 1000,
        maxPromptChars: 200,
        maxContextChars: 200,
      },
      decide: async () => ({
        mode: "enforce",
        accepted: true,
        char: "L",
        raw: "L",
        durationMs: 1,
        model: "openai/gpt-5.1-codex-mini",
        templateId: "delegation-route-v1",
      }),
    },
  })
  const output = {
    args: {
      subagent_type: "explore",
      prompt: "Gather official docs for the upstream API and summarize the library behavior.",
      description: "Need external references.",
    },
  }
  await hook.event("tool.execute.before", {
    input: { tool: "task", sessionID: "session-llm-route-1" },
    output,
  })
  assert.equal(output.args.subagent_type, "librarian")
})

test("agent model resolver uses assist-mode LLM to confirm inferred route without explicit subagent", async () => {
  const hook = createAgentModelResolverHook({
    directory: REPO_DIRECTORY,
    enabled: true,
    defaultOverrideDelta: 99,
    defaultIntentThreshold: 99,
    agentPolicyOverrides: {},
    decisionRuntime: {
      config: {
        enabled: true,
        mode: "assist",
        command: "opencode",
        model: "openai/gpt-5.1-codex-mini",
        timeoutMs: 1000,
        maxPromptChars: 200,
        maxContextChars: 200,
      },
      decide: async () => ({
        mode: "assist",
        accepted: true,
        char: "L",
        raw: "L",
        durationMs: 1,
        model: "openai/gpt-5.1-codex-mini",
        templateId: "delegation-route-v1",
      }),
    },
  })
  const output = {
    args: {
      prompt: "Gather official docs for the upstream API and summarize the library behavior.",
      description: "Need external references.",
    },
  }
  await hook.event("tool.execute.before", {
    input: { tool: "task", sessionID: "session-llm-route-2" },
    output,
  })
  assert.equal(output.args.subagent_type, "librarian")
})

test("agent model resolver preserves explicit-none context for inferred assist decisions", async () => {
  let capturedInstruction = ""
  let capturedContext = ""
  const hook = createAgentModelResolverHook({
    directory: REPO_DIRECTORY,
    enabled: true,
    defaultOverrideDelta: 99,
    defaultIntentThreshold: 99,
    agentPolicyOverrides: {},
    decisionRuntime: {
      config: {
        enabled: true,
        mode: "assist",
        command: "opencode",
        model: "openai/gpt-5.1-codex-mini",
        timeoutMs: 1000,
        maxPromptChars: 200,
        maxContextChars: 200,
      },
      decide: async (request) => {
        capturedInstruction = request.instruction
        capturedContext = request.context
        return {
          mode: "assist",
          accepted: true,
          char: "L",
          raw: "L",
          durationMs: 1,
          model: "openai/gpt-5.1-codex-mini",
          templateId: "delegation-route-v1",
        }
      },
    },
  })
  const output = {
    args: {
      prompt: "Gather official docs for the upstream API and summarize the library behavior.",
      description: "Need external references.",
    },
  }
  await hook.event("tool.execute.before", {
    input: { tool: "task", sessionID: "session-llm-route-2b" },
    output,
  })
  assert.equal(output.args.subagent_type, "librarian")
  assert.match(capturedContext, /explicit_subagent=none/)
  assert.doesNotMatch(capturedInstruction, /K=keep explicit choice/)
})

test("agent model resolver shadow or assist mode does not override explicit route", async () => {
  const hook = createAgentModelResolverHook({
    directory: REPO_DIRECTORY,
    enabled: true,
    defaultOverrideDelta: 99,
    defaultIntentThreshold: 99,
    agentPolicyOverrides: {},
    decisionRuntime: {
      config: {
        enabled: true,
        mode: "assist",
        command: "opencode",
        model: "openai/gpt-5.1-codex-mini",
        timeoutMs: 1000,
        maxPromptChars: 200,
        maxContextChars: 200,
      },
      decide: async () => ({
        mode: "assist",
        accepted: true,
        char: "L",
        raw: "L",
        durationMs: 1,
        model: "openai/gpt-5.1-codex-mini",
        templateId: "delegation-route-v1",
      }),
    },
  })
  const output = {
    args: {
      subagent_type: "explore",
      prompt: "Gather official docs for the upstream API and summarize the library behavior.",
      description: "Need external references.",
    },
  }
  await hook.event("tool.execute.before", {
    input: { tool: "task", sessionID: "session-llm-route-3" },
    output,
  })
  assert.equal(output.args.subagent_type, "explore")
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

  await timelineHook.event("tool.execute.before", {
    input: { tool: "task", sessionID: "session-learn-1" },
    output: { args: { subagent_type: "reviewer", category: "critical", prompt: "first" } },
  })
  await timelineHook.event("tool.execute.after", {
    input: { tool: "task", sessionID: "session-learn-1" },
    output: { output: "[ERROR] Failed delegation" },
  })

  await timelineHook.event("tool.execute.before", {
    input: { tool: "task", sessionID: "session-learn-2" },
    output: { args: { subagent_type: "reviewer", category: "critical", prompt: "second" } },
  })
  await timelineHook.event("tool.execute.after", {
    input: { tool: "task", sessionID: "session-learn-2" },
    output: { output: "[ERROR] Failed delegation" },
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

test("agent denied tool enforcer blocks LLM-classified mutating request in enforce mode", async () => {
  const hook = createAgentDeniedToolEnforcerHook({
    directory: REPO_DIRECTORY,
    enabled: true,
    decisionRuntime: {
      config: {
        enabled: true,
        mode: "enforce",
        command: "opencode",
        model: "openai/gpt-5.1-codex-mini",
        timeoutMs: 1000,
        maxPromptChars: 200,
        maxContextChars: 200,
        enableCache: true,
        cacheTtlMs: 10000,
      },
      decide: async (request) => ({
        mode: "enforce",
        accepted: true,
        char: request.templateId === "mutation-safety-v1" ? "M" : "A",
        raw: request.templateId === "mutation-safety-v1" ? "M" : "A",
        durationMs: 1,
        model: "openai/gpt-5.1-codex-mini",
        templateId: request.templateId,
        meaning: request.templateId === "mutation-safety-v1" ? "mutating_requested" : "allowed_or_no_issue",
      }),
    },
  })
  await assert.rejects(
    () =>
      hook.event("tool.execute.before", {
        input: { tool: "task", sessionID: "session-llm-mutation-1" },
        output: {
          args: {
            subagent_type: "explore",
            prompt: "Prepare the exact code changes and commit-ready edits for this bug.",
            description: "Need a read-only scout to decide next steps.",
          },
        },
      }),
    /LLM mutation classifier marked the request as mutating/i,
  )
})

test("agent denied tool enforcer blocks LLM-classified denied tool implication in enforce mode", async () => {
  const hook = createAgentDeniedToolEnforcerHook({
    directory: REPO_DIRECTORY,
    enabled: true,
    decisionRuntime: {
      config: {
        enabled: true,
        mode: "enforce",
        command: "opencode",
        model: "openai/gpt-5.1-codex-mini",
        timeoutMs: 1000,
        maxPromptChars: 200,
        maxContextChars: 200,
        enableCache: true,
        cacheTtlMs: 10000,
      },
      decide: async (request) => ({
        mode: "enforce",
        accepted: true,
        char: request.templateId === "denied-tool-intent-v1" ? "D" : "R",
        raw: request.templateId === "denied-tool-intent-v1" ? "D" : "R",
        durationMs: 1,
        model: "openai/gpt-5.1-codex-mini",
        templateId: request.templateId,
        meaning: request.templateId === "denied-tool-intent-v1" ? "denied_tool_implied" : "read_only_safe",
      }),
    },
  })
  await assert.rejects(
    () =>
      hook.event("tool.execute.before", {
        input: { tool: "task", sessionID: "session-llm-tool-1" },
        output: {
          args: {
            subagent_type: "explore",
            prompt: "Check the repo state by shelling out to inspect git directly.",
            description: "Need the quickest route.",
          },
        },
      }),
    /implying denied tooling/i,
  )
})

test("agent denied tool enforcer assist mode records LLM decisions without blocking", async () => {
  const hook = createAgentDeniedToolEnforcerHook({
    directory: REPO_DIRECTORY,
    enabled: true,
    decisionRuntime: {
      config: {
        enabled: true,
        mode: "assist",
        command: "opencode",
        model: "openai/gpt-5.1-codex-mini",
        timeoutMs: 1000,
        maxPromptChars: 200,
        maxContextChars: 200,
        enableCache: true,
        cacheTtlMs: 10000,
        maxCacheEntries: 8,
      },
      decide: async (request) => ({
        mode: "assist",
        accepted: true,
        char: request.templateId === "mutation-safety-v1" ? "M" : "D",
        raw: request.templateId === "mutation-safety-v1" ? "M" : "D",
        durationMs: 1,
        model: "openai/gpt-5.1-codex-mini",
        templateId: request.templateId,
        meaning:
          request.templateId === "mutation-safety-v1" ? "mutating_requested" : "denied_tool_implied",
      }),
    },
  })
  const payload = {
    input: { tool: "task", sessionID: "session-llm-assist-1" },
    output: {
      args: {
        subagent_type: "explore",
        prompt: "Prepare the exact code changes and check the repo state by shelling out directly.",
        description: "Need the quickest route.",
      },
    },
  }
  await hook.event("tool.execute.before", payload)
  assert.equal(payload.output.args.subagent_type, "explore")
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

test("runtime delegation hooks sustain five same-session subagents with varied completion order", async () => {
  const hooks = [
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

  async function dispatch(type, payload) {
    for (const hook of hooks) {
      await hook.event(type, payload)
    }
  }

  const sessionID = "session-stress-five-subagents"
  const delegations = [
    { subagent_type: "explore", category: "quick", prompt: "stress alpha" },
    { subagent_type: "strategic-planner", category: "deep", prompt: "stress beta" },
    { subagent_type: "librarian", category: "balanced", prompt: "stress gamma" },
    { subagent_type: "verifier", category: "quick", prompt: "stress delta" },
    { subagent_type: "reviewer", category: "critical", prompt: "stress epsilon" },
  ].map((args) => ({ args }))

  for (const output of delegations) {
    await dispatch("tool.execute.before", {
      input: { tool: "task", sessionID },
      output,
    })
  }

  for (const index of [2, 4, 1, 3, 0]) {
    await dispatch("tool.execute.after", {
      input: { tool: "task", sessionID },
      output: {
        metadata: delegations[index].metadata,
        output: "done",
      },
    })
  }

  const records = getRecentDelegationOutcomes(60000).filter((item) => item.sessionId === sessionID)
  assert.equal(records.length, 5)
  assert.deepEqual(
    records.map((item) => item.subagentType).sort(),
    ["explore", "librarian", "reviewer", "strategic-planner", "verifier"],
  )
  assert.equal(new Set(records.map((item) => item.childRunId)).size, 5)
  assert.ok(records.every((item) => item.status === "completed"))

  await dispatch("tool.execute.before", {
    input: { tool: "task", sessionID },
    output: { args: { subagent_type: "reviewer", category: "critical", prompt: "stress follow-up" } },
  })
})

test("runtime delegation hooks reconcile orphaned child session idle events", async () => {
  const hooks = [
    createDelegationConcurrencyGuardHook({
      directory: REPO_DIRECTORY,
      enabled: true,
      maxTotalConcurrent: 1,
      maxExpensiveConcurrent: 1,
      maxDeepConcurrent: 1,
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

  async function dispatch(type, payload) {
    for (const hook of hooks) {
      await hook.event(type, payload)
    }
  }

  const sessionID = "session-child-idle-reconcile"
  await dispatch("tool.execute.before", {
    input: { tool: "task", sessionID },
    output: {
      args: {
        subagent_type: "explore",
        category: "quick",
        prompt: "[DELEGATION TRACE child-idle-trace] inspect runtime",
      },
    },
  })

  await dispatch("session.created", {
    properties: {
      info: {
        id: "child-session-idle-1",
        parentID: sessionID,
        title: "[DELEGATION TRACE child-idle-trace] explore child",
      },
    },
  })
  await dispatch("session.idle", {
    properties: {
      sessionID: "child-session-idle-1",
    },
  })

  await dispatch("tool.execute.before", {
    input: { tool: "task", sessionID },
    output: {
      args: {
        subagent_type: "reviewer",
        category: "critical",
        prompt: "follow-up after idle reconciliation",
      },
    },
  })

  const record = getRecentDelegationOutcomes(60000)
    .filter((item) => item.sessionId === sessionID && item.traceId === "child-idle-trace")
    .at(-1)
  assert.ok(record)
  assert.equal(record.status, "completed")
})

test("runtime delegation hooks reconcile child assistant failure messages", async () => {
  const hooks = [
    createDelegationConcurrencyGuardHook({
      directory: REPO_DIRECTORY,
      enabled: true,
      maxTotalConcurrent: 1,
      maxExpensiveConcurrent: 1,
      maxDeepConcurrent: 1,
      maxCriticalConcurrent: 1,
      staleReservationMs: 60000,
    }),
    createSubagentLifecycleSupervisorHook({
      directory: REPO_DIRECTORY,
      enabled: true,
      maxRetriesPerSession: 1,
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

  async function dispatch(type, payload) {
    for (const hook of hooks) {
      await hook.event(type, payload)
    }
  }

  const sessionID = "session-child-message-failure"
  await dispatch("tool.execute.before", {
    input: { tool: "task", sessionID },
    output: {
      args: {
        subagent_type: "reviewer",
        category: "critical",
        prompt: "[DELEGATION TRACE child-failure-trace] review release risk",
      },
    },
  })

  await dispatch("session.created", {
    properties: {
      info: {
        id: "child-session-failure-1",
        parentID: sessionID,
        title: "[DELEGATION TRACE child-failure-trace] reviewer child",
      },
    },
  })
  await dispatch("message.updated", {
    properties: {
      info: {
        role: "assistant",
        sessionID: "child-session-failure-1",
        error: { name: "UnknownError", data: { message: "subagent crashed" } },
        time: { completed: Date.now() },
      },
    },
  })

  await assert.rejects(
    () =>
      dispatch("tool.execute.before", {
        input: { tool: "task", sessionID },
        output: {
          args: {
            subagent_type: "reviewer",
            category: "critical",
            prompt: "[DELEGATION TRACE child-failure-trace] retry same failed child",
          },
        },
      }),
    /retry budget exhausted/i,
  )
  await dispatch("tool.execute.before.error", {
    input: { tool: "task", sessionID },
    output: {
      args: {
        subagent_type: "reviewer",
        category: "critical",
        prompt: "[DELEGATION TRACE child-failure-trace] retry same failed child",
      },
    },
  })

  await dispatch("tool.execute.before", {
    input: { tool: "task", sessionID },
    output: {
      args: {
        subagent_type: "explore",
        category: "quick",
        prompt: "different follow-up after failure cleanup",
      },
    },
  })

  const record = getRecentDelegationOutcomes(60000)
    .filter((item) => item.sessionId === sessionID && item.traceId === "child-failure-trace")
    .at(-1)
  assert.ok(record)
  assert.equal(record.status, "failed")
})

test("runtime delegation hooks ignore child sessions without delegation trace markers", async () => {
  const hooks = [
    createDelegationConcurrencyGuardHook({
      directory: REPO_DIRECTORY,
      enabled: true,
      maxTotalConcurrent: 1,
      maxExpensiveConcurrent: 1,
      maxDeepConcurrent: 1,
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

  async function dispatch(type, payload) {
    for (const hook of hooks) {
      await hook.event(type, payload)
    }
  }

  const sessionID = "session-child-no-trace"
  await dispatch("tool.execute.before", {
    input: { tool: "task", sessionID },
    output: {
      args: {
        subagent_type: "explore",
        category: "quick",
        prompt: "[DELEGATION TRACE explicit-parent-trace] inspect runtime",
      },
    },
  })

  await dispatch("session.created", {
    properties: {
      info: {
        id: "child-session-no-trace-1",
        parentID: sessionID,
        title: "child session without trace marker",
      },
    },
  })
  await dispatch("session.idle", {
    properties: {
      sessionID: "child-session-no-trace-1",
    },
  })

  await assert.rejects(
    () =>
      dispatch("tool.execute.before", {
        input: { tool: "task", sessionID },
        output: {
          args: {
            subagent_type: "reviewer",
            category: "critical",
            prompt: "follow-up should still be blocked",
          },
        },
      }),
    /maxTotalConcurrent/i,
  )
})

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
