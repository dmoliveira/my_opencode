import assert from "node:assert/strict"
import test from "node:test"

import { classifyProviderRetryReason, isContextOverflowNonRetryable } from "../dist/hooks/shared/provider-retry-reason.js"

test("classifyProviderRetryReason recognizes free usage exhaustion", () => {
  const result = classifyProviderRetryReason("FreeUsageLimitError: free usage exceeded")
  assert.equal(result?.code, "free_usage_exhausted")
  assert.match(String(result?.message), /add credits/i)
})

test("classifyProviderRetryReason recognizes structured rate-limit and overload signals", () => {
  assert.equal(classifyProviderRetryReason('{"type":"error","error":{"type":"too_many_requests"}}')?.code, "too_many_requests")
  assert.equal(classifyProviderRetryReason('rate_limit_exceeded')?.code, "rate_limited")
  assert.equal(classifyProviderRetryReason('provider is overloaded')?.code, "provider_overloaded")
})


test("isContextOverflowNonRetryable detects context-overflow signatures", () => {
  assert.equal(isContextOverflowNonRetryable("ContextOverflowError: prompt is too long"), true)
  assert.equal(isContextOverflowNonRetryable("normal rate limited"), false)
})
