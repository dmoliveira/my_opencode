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


test("provider-error-classifier skips context-overflow non-retryable errors", async () => {
  const prompts = []
  const hook = createProviderErrorClassifierHook({
    directory: process.cwd(),
    enabled: true,
    cooldownMs: 1,
    client: { session: { async promptAsync(args) { prompts.push(args) } } },
  })

  await hook.event("session.error", {
    properties: { sessionID: "s4", error: "ContextOverflowError: maximum context reached" },
  })

  assert.equal(prompts.length, 0)
})

test("provider-error-classifier uses LLM fallback for ambiguous provider wording", async () => {
  const prompts = []
  const hook = createProviderErrorClassifierHook({
    directory: process.cwd(),
    enabled: true,
    cooldownMs: 1,
    client: { session: { async promptAsync(args) { prompts.push(args) } } },
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
        char: "O",
        raw: "O",
        durationMs: 1,
        model: "openai/gpt-5.1-codex-mini",
        templateId: "provider-error-classifier-v1",
        meaning: "provider_overloaded",
      }),
    },
  })

  await hook.event("session.error", {
    properties: { sessionID: "s5", error: "Service temporarily saturated, please retry later" },
  })

  assert.equal(prompts.length, 1)
  assert.match(String(prompts[0].body.parts[0].text), /overload/i)
  assert.match(String(prompts[0].body.parts[0].text), /llm:provider_overloaded/i)
})

test("provider-error-classifier skips events with no error content (prevents runaway spawning)", async () => {
  let decideCalls = 0
  const prompts = []
  const hook = createProviderErrorClassifierHook({
    directory: process.cwd(),
    enabled: true,
    cooldownMs: 1,
    client: { session: { async promptAsync(args) { prompts.push(args) } } },
    decisionRuntime: {
      config: {
        enabled: true,
        mode: "assist",
        command: "opencode",
        model: "openai/gpt-5.1-codex-mini",
        timeoutMs: 1000,
        maxPromptChars: 200,
        maxContextChars: 200,
        enableCache: false,
        cacheTtlMs: 10000,
        maxCacheEntries: 8,
      },
      decide: async () => {
        decideCalls++
        return { mode: "assist", accepted: false, char: "", raw: "", durationMs: 1, model: "openai/gpt-5.1-codex-mini", templateId: "provider-error-classifier-v1" }
      },
    },
  })

  // All error fields absent — previously generated '""\n""\n""' noise, triggering LLM
  await hook.event("session.error", { properties: { sessionID: "s6" } })
  await hook.event("message.updated", { properties: { sessionID: "s6" } })
  // Empty string error field
  await hook.event("session.error", { properties: { sessionID: "s6", error: "" } })

  assert.equal(decideCalls, 0, "LLM decision runtime must not be invoked for empty error payloads")
  assert.equal(prompts.length, 0)
})

test("provider-error-classifier injects TUI hint when LLM decision is max_concurrency_reached", async () => {
  const prompts = []
  const hook = createProviderErrorClassifierHook({
    directory: process.cwd(),
    enabled: true,
    cooldownMs: 60000,
    client: { session: { async promptAsync(args) { prompts.push(args) } } },
    decisionRuntime: {
      config: {
        enabled: true,
        mode: "assist",
        command: "opencode",
        model: "openai/gpt-5.1-codex-mini",
        timeoutMs: 1000,
        maxPromptChars: 200,
        maxContextChars: 200,
        enableCache: false,
        cacheTtlMs: 10000,
        maxCacheEntries: 8,
      },
      decide: async () => ({
        mode: "assist",
        accepted: false,
        char: "",
        raw: "",
        durationMs: 1,
        model: "openai/gpt-5.1-codex-mini",
        templateId: "provider-error-classifier-v1",
        skippedReason: "max_concurrency_reached",
      }),
    },
  })

  await hook.event("session.error", {
    properties: { sessionID: "s7", error: "Unusual provider error with unknown wording" },
  })

  assert.equal(prompts.length, 1)
  assert.match(String(prompts[0].body.parts[0].text), /\[provider ERROR CLASSIFIER\]/i)
  assert.match(String(prompts[0].body.parts[0].text), /subprocess already in progress/i)
})

test("provider-error-classifier injects TUI hint when LLM decision is runtime_cooldown", async () => {
  const prompts = []
  const hook = createProviderErrorClassifierHook({
    directory: process.cwd(),
    enabled: true,
    cooldownMs: 60000,
    client: { session: { async promptAsync(args) { prompts.push(args) } } },
    decisionRuntime: {
      config: {
        enabled: true,
        mode: "assist",
        command: "opencode",
        model: "openai/gpt-5.1-codex-mini",
        timeoutMs: 1000,
        maxPromptChars: 200,
        maxContextChars: 200,
        enableCache: false,
        cacheTtlMs: 10000,
        maxCacheEntries: 8,
      },
      decide: async () => ({
        mode: "assist",
        accepted: false,
        char: "",
        raw: "",
        durationMs: 1,
        model: "openai/gpt-5.1-codex-mini",
        templateId: "provider-error-classifier-v1",
        skippedReason: "runtime_cooldown",
      }),
    },
  })

  await hook.event("session.error", {
    properties: { sessionID: "s8", error: "Unusual provider error with unknown wording" },
  })

  assert.equal(prompts.length, 1)
  assert.match(String(prompts[0].body.parts[0].text), /\[provider ERROR CLASSIFIER\]/i)
  assert.match(String(prompts[0].body.parts[0].text), /cooldown/i)
})

test("provider-error-classifier deduplicates runtime skip notices within cooldown window", async () => {
  const prompts = []
  let callCount = 0
  const hook = createProviderErrorClassifierHook({
    directory: process.cwd(),
    enabled: true,
    cooldownMs: 60000,
    client: { session: { async promptAsync(args) { prompts.push(args) } } },
    decisionRuntime: {
      config: {
        enabled: true,
        mode: "assist",
        command: "opencode",
        model: "openai/gpt-5.1-codex-mini",
        timeoutMs: 1000,
        maxPromptChars: 200,
        maxContextChars: 200,
        enableCache: false,
        cacheTtlMs: 10000,
        maxCacheEntries: 8,
      },
      decide: async () => {
        callCount++
        return {
          mode: "assist",
          accepted: false,
          char: "",
          raw: "",
          durationMs: 1,
          model: "openai/gpt-5.1-codex-mini",
          templateId: "provider-error-classifier-v1",
          skippedReason: "max_concurrency_reached",
        }
      },
    },
  })

  // Fire three events — all get skip notices from decide(), but only the first should inject
  await hook.event("session.error", { properties: { sessionID: "s9", error: "provider error alpha" } })
  await hook.event("session.error", { properties: { sessionID: "s9", error: "provider error beta" } })
  await hook.event("session.error", { properties: { sessionID: "s9", error: "provider error gamma" } })

  assert.equal(callCount, 3, "decide() should be called for each event")
  assert.equal(prompts.length, 1, "Only one skip notice should be injected within the cooldown window")
})
