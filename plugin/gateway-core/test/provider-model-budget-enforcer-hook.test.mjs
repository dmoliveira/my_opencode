import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("provider-model-budget-enforcer blocks delegations above per-window count", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-provider-budget-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["provider-model-budget-enforcer"],
          disabled: [],
        },
        providerModelBudgetEnforcer: {
          enabled: true,
          windowMs: 120000,
          maxDelegationsPerWindow: 1,
          maxEstimatedTokensPerWindow: 5000,
          maxPerModelDelegationsPerWindow: 2,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-budget-1" },
      { args: { subagent_type: "explore", prompt: "quick check" } },
    )

    await assert.rejects(
      () =>
        plugin["tool.execute.before"](
          { tool: "task", sessionID: "session-budget-2" },
          { args: { subagent_type: "explore", prompt: "quick check two" } },
        ),
      /maxDelegationsPerWindow/i,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("provider-model-budget-enforcer blocks delegations above token budget", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-provider-budget-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["provider-model-budget-enforcer"],
          disabled: [],
        },
        providerModelBudgetEnforcer: {
          enabled: true,
          windowMs: 120000,
          maxDelegationsPerWindow: 10,
          maxEstimatedTokensPerWindow: 100,
          maxPerModelDelegationsPerWindow: 10,
        },
      },
    })

    const hugePrompt = "x".repeat(5000)
    await assert.rejects(
      () =>
        plugin["tool.execute.before"](
          { tool: "task", sessionID: "session-budget-3" },
          { args: { subagent_type: "reviewer", prompt: hugePrompt } },
        ),
      /maxEstimatedTokensPerWindow/i,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
