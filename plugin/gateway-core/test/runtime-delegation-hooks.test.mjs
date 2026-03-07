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

const REPO_DIRECTORY = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..")

test("delegation confidence gate overrides low-confidence explicit subagent", async () => {
  const hook = createAgentModelResolverHook({ directory: REPO_DIRECTORY, enabled: true })
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
  assert.match(output.args.prompt, /\[DELEGATION ROUTER\]/)
})

test("agent discoverability injector appends catalog hint only after routing rewrite", async () => {
  const resolver = createAgentModelResolverHook({ directory: REPO_DIRECTORY, enabled: true })
  const discoverability = createAgentDiscoverabilityInjectorHook({
    directory: REPO_DIRECTORY,
    enabled: true,
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
  assert.match(output.args.prompt, /\[DELEGATION ROUTER\]/)
  assert.match(output.args.prompt, /\/agent-catalog explain explore/)
})

test("delegation outcome learner adapts risky category after repeated failures", async () => {
  const timelineHook = createSubagentTelemetryTimelineHook({
    directory: REPO_DIRECTORY,
    enabled: true,
    maxTimelineEntries: 100,
  })
  const learnerHook = createDelegationOutcomeLearnerHook({
    directory: REPO_DIRECTORY,
    enabled: true,
    windowMs: 120000,
    minSamples: 2,
    highFailureRate: 0.5,
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
