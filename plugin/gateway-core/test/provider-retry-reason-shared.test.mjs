import assert from "node:assert/strict"
import test from "node:test"

import {
  classifyProviderRetryReason,
  isContextOverflowNonRetryable,
  isProviderHeaderTimeout,
} from "../dist/hooks/shared/provider-retry-reason.js"

test("classifyProviderRetryReason recognizes free usage exhaustion", () => {
  const result = classifyProviderRetryReason("FreeUsageLimitError: free usage exceeded")
  assert.equal(result?.code, "free_usage_exhausted")
  assert.match(String(result?.message), /add credits/i)
})

test("classifyProviderRetryReason recognizes structured rate-limit and overload signals", () => {
  assert.equal(classifyProviderRetryReason('{"type":"error","error":{"type":"too_many_requests"}}')?.code, "too_many_requests")
  assert.equal(classifyProviderRetryReason('rate_limit_exceeded')?.code, "rate_limited")
  assert.equal(classifyProviderRetryReason('provider is overloaded')?.code, "provider_overloaded")
  assert.equal(
    classifyProviderRetryReason('{"type":"error","error":{"type":"service_unavailable_error","code":"server_is_overloaded","message":"Our servers are currently overloaded. Please try again later."}}')?.code,
    "provider_overloaded",
  )
  assert.equal(classifyProviderRetryReason("Service unavailable, try again later")?.code, undefined)
  assert.equal(classifyProviderRetryReason("Local queue overloaded while indexing docs")?.code, undefined)
})


test("isContextOverflowNonRetryable detects context-overflow signatures", () => {
  assert.equal(isContextOverflowNonRetryable("ContextOverflowError: prompt is too long"), true)
  assert.equal(isContextOverflowNonRetryable("normal rate limited"), false)
})


test("classifyProviderRetryReason recognizes provider header timeouts", () => {
  assert.equal(classifyProviderRetryReason("ProviderHeaderTimeoutError: Provider response headers timed out after 10000ms")?.code, "provider_header_timeout")
  assert.equal(isProviderHeaderTimeout("Provider response headers timed out after 10000ms"), true)
})
