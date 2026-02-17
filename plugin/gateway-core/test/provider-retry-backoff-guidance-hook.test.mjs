import assert from "node:assert/strict"
import test from "node:test"

import { createProviderRetryBackoffGuidanceHook } from "../dist/hooks/provider-retry-backoff-guidance/index.js"

test("provider-retry-backoff-guidance injects delay hint from retry-after-ms header", async () => {
  const prompts = []
  const hook = createProviderRetryBackoffGuidanceHook({
    directory: process.cwd(),
    enabled: true,
    cooldownMs: 1,
    client: {
      session: {
        async promptAsync(args) {
          prompts.push(args)
        },
      },
    },
  })

  await hook.event("session.error", {
    properties: { sessionID: "s1", error: { responseHeaders: { "retry-after-ms": "1500" } } },
  })

  assert.equal(prompts.length, 1)
  const text = String(prompts[0].body.parts[0].text)
  assert.match(text, /provider RETRY BACKOFF/i)
  assert.match(text, /1\.5s/)
})

test("provider-retry-backoff-guidance falls back to generic backoff hint", async () => {
  const prompts = []
  const hook = createProviderRetryBackoffGuidanceHook({
    directory: process.cwd(),
    enabled: true,
    cooldownMs: 1,
    client: {
      session: {
        async promptAsync(args) {
          prompts.push(args)
        },
      },
    },
  })

  await hook.event("message.updated", {
    properties: { sessionID: "s2", error: "Too many requests from provider" },
  })

  assert.equal(prompts.length, 1)
  const text = String(prompts[0].body.parts[0].text)
  assert.match(text, /exponential backoff/i)
})


test("provider-retry-backoff-guidance skips context-overflow non-retryable errors", async () => {
  const prompts = []
  const hook = createProviderRetryBackoffGuidanceHook({
    directory: process.cwd(),
    enabled: true,
    cooldownMs: 1,
    client: { session: { async promptAsync(args) { prompts.push(args) } } },
  })

  await hook.event("session.error", {
    properties: { sessionID: "s3", error: "ContextOverflowError: prompt is too long" },
  })

  assert.equal(prompts.length, 0)
})


test("provider-retry-backoff-guidance caps headerless exponential backoff delay at 30s", async () => {
  const prompts = []
  const hook = createProviderRetryBackoffGuidanceHook({
    directory: process.cwd(),
    enabled: true,
    cooldownMs: 1,
    client: {
      session: {
        async promptAsync(args) {
          prompts.push(args)
        },
      },
    },
  })

  for (let idx = 0; idx < 6; idx += 1) {
    await hook.event("message.updated", {
      properties: { sessionID: "s4", error: "Too many requests from provider" },
    })
    await new Promise((resolve) => setTimeout(resolve, 2))
  }

  const text = String(prompts.at(-1)?.body.parts[0].text ?? "")
  assert.match(text, /30\.0s/)
  assert.match(text, /cap 30s without retry headers/i)
})
