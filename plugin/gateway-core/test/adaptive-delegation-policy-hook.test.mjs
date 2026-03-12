import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { createSubagentTelemetryTimelineHook } from "../dist/hooks/subagent-telemetry-timeline/index.js"
import { getRecentDelegationOutcomes } from "../dist/hooks/shared/delegation-runtime-state.js"

test("adaptive-delegation-policy blocks critical category during cooldown", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-adaptive-delegation-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["subagent-telemetry-timeline", "adaptive-delegation-policy"],
          disabled: [],
        },
        subagentTelemetryTimeline: {
          enabled: true,
          maxTimelineEntries: 100,
        },
        adaptiveDelegationPolicy: {
          enabled: true,
          windowMs: 120000,
          minSamples: 2,
          highFailureRate: 0.5,
          cooldownMs: 120000,
          blockExpensiveDuringCooldown: true,
        },
        pressureEscalationGuard: {
          enabled: false,
        },
        tasksTodowriteDisabler: {
          enabled: false,
        },
      },
    })

    const firstOutput = { args: { subagent_type: "reviewer", category: "critical", prompt: "first" } }
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-adapt-1" },
      firstOutput,
    )
    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-adapt-1" },
      { metadata: firstOutput.metadata, output: "[ERROR] Failed delegation" },
    )

    const secondOutput = { args: { subagent_type: "reviewer", category: "critical", prompt: "second" } }
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-adapt-2" },
      secondOutput,
    )
    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-adapt-2" },
      { metadata: secondOutput.metadata, output: "[ERROR] Failed delegation" },
    )

    await assert.rejects(
      () =>
        plugin["tool.execute.before"](
          { tool: "task", sessionID: "session-adapt-3" },
          { args: { subagent_type: "reviewer", category: "critical", prompt: "third" } },
        ),
      /adaptive cooldown active/i,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("subagent telemetry timeline reads structured task failure output", async () => {
  const hook = createSubagentTelemetryTimelineHook({
    directory: process.cwd(),
    enabled: true,
    maxTimelineEntries: 100,
    persistState: false,
    stateFile: ".opencode/test-runtime-state.json",
    stateMaxEntries: 100,
  })

  const beforeOutput = {
    args: { subagent_type: "reviewer", category: "critical", prompt: "first" },
  }
  await hook.event("tool.execute.before", {
    input: { tool: "task", sessionID: "session-adapt-s1" },
    output: beforeOutput,
  })
  await hook.event("tool.execute.after", {
    input: { tool: "task", sessionID: "session-adapt-s1" },
    output: {
      metadata: beforeOutput.metadata,
      output: { stdout: "[ERROR] Failed delegation", stderr: "warning text" },
    },
  })

  const record = getRecentDelegationOutcomes(60000)
    .filter((item) => item.sessionId === "session-adapt-s1")
    .at(-1)
  assert.ok(record)
  assert.equal(record.status, "failed")
  assert.equal(record.subagentType, "reviewer")
})
