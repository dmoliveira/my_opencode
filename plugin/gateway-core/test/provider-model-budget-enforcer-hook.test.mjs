import assert from "node:assert/strict"
import { mkdtempSync, readFileSync, rmSync } from "node:fs"
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

test("provider-model-budget-enforcer honors explicit category override and deep model mapping", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-provider-budget-"))
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
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
          maxEstimatedTokensPerWindow: 5000,
          maxPerModelDelegationsPerWindow: 10,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-budget-4" },
      {
        args: {
          subagent_type: "explore",
          category: "deep",
          prompt: "run deep architecture review",
        },
      },
    )

    const auditPath = join(directory, ".opencode", "gateway-events.jsonl")
    const events = readFileSync(auditPath, "utf-8")
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => JSON.parse(line))
    const reservation = events.find(
      (event) => event.reason_code === "provider_model_budget_reserved",
    )

    assert.equal(reservation?.category, "deep")
    assert.equal(reservation?.model, "openai/gpt-5.4-codex")
  } finally {
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    }
    rmSync(directory, { recursive: true, force: true })
  }
})
