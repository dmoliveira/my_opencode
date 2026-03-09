import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { createDelegationFallbackOrchestratorHook } from "../dist/hooks/delegation-fallback-orchestrator/index.js"

test("delegation-fallback-orchestrator applies fallback only to matching failed delegation trace", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-fallback-orchestrator-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["delegation-fallback-orchestrator"],
          disabled: [],
        },
        delegationFallbackOrchestrator: {
          enabled: true,
        },
      },
    })

    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-fallback-1" },
      {
        args: {
          subagent_type: "reviewer",
          category: "critical",
          prompt: "[DELEGATION TRACE failed-trace] failed delegation",
        },
        output: "[ERROR] Invalid arguments",
      },
    )

    const unaffected = {
      args: {
        subagent_type: "reviewer",
        category: "critical",
        prompt: "[DELEGATION TRACE other-trace] unaffected delegation",
      },
    }
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-fallback-1" },
      unaffected,
    )
    assert.equal(unaffected.args.subagent_type, "reviewer")
    assert.equal(unaffected.args.category, "critical")

    const fallback = {
      args: {
        subagent_type: "reviewer",
        category: "critical",
        prompt: "[DELEGATION TRACE failed-trace] retry delegation",
      },
    }
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-fallback-1" },
      fallback,
    )
    assert.equal(fallback.args.category, "general")
    assert.match(String(fallback.args.prompt), /delegation-fallback-orchestrator/i)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("delegation-fallback-orchestrator uses LLM failure classification for ambiguous output", async () => {
  const hook = createDelegationFallbackOrchestratorHook({
    directory: process.cwd(),
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
      decide: async () => ({
        mode: "assist",
        accepted: true,
        char: "I",
        raw: "I",
        durationMs: 1,
        model: "openai/gpt-5.1-codex-mini",
        templateId: "delegation-failure-classifier-v1",
        meaning: "delegation_invalid_arguments",
      }),
    },
  })

  await hook.event("tool.execute.after", {
    input: { tool: "task", sessionID: "session-fallback-2" },
    output: {
      args: {
        subagent_type: "reviewer",
        category: "critical",
        prompt: "[DELEGATION TRACE ambiguous-trace] ambiguous delegation",
      },
      output: "The task delegation could not proceed because the request shape was not accepted by the runtime.",
    },
  })

  const retry = {
    args: {
      subagent_type: "reviewer",
      category: "critical",
      prompt: "[DELEGATION TRACE ambiguous-trace] retry delegation",
    },
  }
  await hook.event("tool.execute.before", {
    input: { tool: "task", sessionID: "session-fallback-2" },
    output: retry,
  })

  assert.equal(retry.args.category, "general")
  assert.equal(Object.hasOwn(retry.args, "subagent_type"), false)
})
