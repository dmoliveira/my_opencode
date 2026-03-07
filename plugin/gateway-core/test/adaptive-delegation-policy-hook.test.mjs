import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

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

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-adapt-1" },
      { args: { subagent_type: "reviewer", category: "critical", prompt: "first" } },
    )
    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-adapt-1" },
      { output: "[ERROR] Failed delegation" },
    )

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-adapt-2" },
      { args: { subagent_type: "reviewer", category: "critical", prompt: "second" } },
    )
    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-adapt-2" },
      { output: "[ERROR] Failed delegation" },
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
