import assert from "node:assert/strict"
import test from "node:test"

import { createProviderErrorClassifierHook } from "../dist/hooks/provider-error-classifier/index.js"

test("provider-error-classifier classifies free usage exhaustion", async () => {
  const prompts = []
  const hook = createProviderErrorClassifierHook({
    directory: process.cwd(),
    enabled: true,
    cooldownMs: 1,
    client: { session: { async promptAsync(args) { prompts.push(args) } } },
  })

  await hook.event("session.error", {
    properties: { sessionID: "s1", error: "FreeUsageLimitError: quota reached" },
  })

  assert.equal(prompts.length, 1)
  assert.match(String(prompts[0].body.parts[0].text), /credit exhaustion/i)
})

test("provider-error-classifier classifies rate limited and overloaded signals", async () => {
  const prompts = []
  const hook = createProviderErrorClassifierHook({
    directory: process.cwd(),
    enabled: true,
    cooldownMs: 1,
    client: { session: { async promptAsync(args) { prompts.push(args) } } },
  })

  await hook.event("message.updated", {
    properties: { sessionID: "s2", error: { type: "error", error: { type: "too_many_requests" } } },
  })
  await hook.event("message.updated", {
    properties: { sessionID: "s2", error: "Provider is overloaded" },
  })

  assert.equal(prompts.length, 2)
  assert.match(String(prompts[0].body.parts[0].text), /rate limiting/i)
  assert.match(String(prompts[1].body.parts[0].text), /overload/i)
})
