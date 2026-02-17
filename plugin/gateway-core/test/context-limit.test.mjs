import assert from "node:assert/strict"
import test from "node:test"

import { resolveContextLimit } from "../dist/hooks/shared/context-limit.js"

test("resolveContextLimit prefers anthropic runtime limits", () => {
  const previous = process.env.ANTHROPIC_1M_CONTEXT
  process.env.ANTHROPIC_1M_CONTEXT = "true"
  try {
    const limit = resolveContextLimit({
      providerID: "anthropic",
      modelID: "claude-sonnet",
      defaultContextLimitTokens: 128000,
    })
    assert.equal(limit, 1000000)
  } finally {
    if (previous === undefined) {
      delete process.env.ANTHROPIC_1M_CONTEXT
    } else {
      process.env.ANTHROPIC_1M_CONTEXT = previous
    }
  }
})

test("resolveContextLimit uses model hints for non-anthropic providers", () => {
  const limit128k = resolveContextLimit({
    providerID: "openai",
    modelID: "gpt-4.1-128k",
    defaultContextLimitTokens: 128000,
  })
  assert.equal(limit128k, 128000)

  const limitFallback = resolveContextLimit({
    providerID: "openai",
    modelID: "gpt-unknown",
    defaultContextLimitTokens: 128000,
  })
  assert.equal(limitFallback, 128000)
})
