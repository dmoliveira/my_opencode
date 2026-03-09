import assert from "node:assert/strict"
import test from "node:test"

import {
  buildSingleCharDecisionPrompt,
  createLlmDecisionRuntime,
  parseSingleCharDecision,
  truncateDecisionText,
} from "../dist/hooks/shared/llm-decision-runtime.js"

test("parseSingleCharDecision accepts only allowed single characters", () => {
  assert.equal(parseSingleCharDecision(" y ", ["Y", "N"]), "Y")
  assert.equal(parseSingleCharDecision("YES", ["Y", "N"]), "")
  assert.equal(parseSingleCharDecision("Q", ["Y", "N"]), "")
})

test("buildSingleCharDecisionPrompt encodes answer-only contract", () => {
  const prompt = buildSingleCharDecisionPrompt({
    instruction: "Return Y for yes, N for no.",
    context: "Continue the loop?",
    allowedChars: ["Y", "N"],
  })
  assert.match(prompt, /Return exactly one character from Y,N\./)
  assert.match(prompt, /No words, punctuation, or explanation\./)
})

test("truncateDecisionText marks oversized content", () => {
  const value = truncateDecisionText("abcdefghij", 8)
  assert.match(value, /\[truncated\]$/)
})

test("llm decision runtime accepts valid JSON text output", async () => {
  const runtime = createLlmDecisionRuntime({
    directory: process.cwd(),
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
    runner: async () => ({
      stdout: '{"type":"text","part":{"text":"Y"}}\n',
      stderr: "",
    }),
  })
  const result = await runtime.decide({
    hookId: "test-hook",
    sessionId: "session-1",
    templateId: "continue-v1",
    instruction: "Continue loop?",
    context: "Pending tasks remain.",
    allowedChars: ["Y", "N"],
    decisionMeaning: { Y: "continue", N: "stop" },
  })
  assert.equal(result.accepted, true)
  assert.equal(result.char, "Y")
  assert.equal(result.meaning, "continue")
})

test("llm decision runtime rejects invalid multi-character output", async () => {
  const runtime = createLlmDecisionRuntime({
    directory: process.cwd(),
    config: {
      enabled: true,
      mode: "shadow",
      command: "opencode",
      model: "openai/gpt-5.1-codex-mini",
      timeoutMs: 1000,
      maxPromptChars: 200,
      maxContextChars: 200,
      enableCache: false,
      cacheTtlMs: 10000,
      maxCacheEntries: 8,
    },
    runner: async () => ({
      stdout: '{"type":"text","part":{"text":"YES"}}\n',
      stderr: "",
    }),
  })
  const result = await runtime.decide({
    hookId: "test-hook",
    sessionId: "session-2",
    templateId: "continue-v1",
    instruction: "Continue loop?",
    context: "Pending tasks remain.",
    allowedChars: ["Y", "N"],
  })
  assert.equal(result.accepted, false)
  assert.equal(result.skippedReason, "invalid_response")
})

test("llm decision runtime caches accepted decisions", async () => {
  let calls = 0
  const runtime = createLlmDecisionRuntime({
    directory: process.cwd(),
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
    runner: async () => {
      calls += 1
      return { stdout: '{"type":"text","part":{"text":"Y"}}\n', stderr: "" }
    },
  })
  const request = {
    hookId: "test-hook",
    sessionId: "session-cache",
    templateId: "continue-v1",
    instruction: "Continue loop?",
    context: "Pending tasks remain.",
    allowedChars: ["Y", "N"],
    decisionMeaning: { Y: "continue", N: "stop" },
    cacheKey: "continue-loop:pending",
  }
  const first = await runtime.decide(request)
  const second = await runtime.decide(request)
  assert.equal(first.accepted, true)
  assert.equal(second.accepted, true)
  assert.equal(second.cached, true)
  assert.equal(second.meaning, "continue")
  assert.equal(calls, 1)
})

test("llm decision runtime prunes cache to max entries", async () => {
  let calls = 0
  const runtime = createLlmDecisionRuntime({
    directory: process.cwd(),
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
      maxCacheEntries: 1,
    },
    runner: async () => {
      calls += 1
      return { stdout: '{"type":"text","part":{"text":"Y"}}\n', stderr: "" }
    },
  })
  const base = {
    hookId: "test-hook",
    sessionId: "session-cache-prune",
    templateId: "continue-v1",
    instruction: "Continue loop?",
    context: "Pending tasks remain.",
    allowedChars: ["Y", "N"],
    decisionMeaning: { Y: "continue", N: "stop" },
  }
  await runtime.decide({ ...base, cacheKey: "first" })
  await runtime.decide({ ...base, cacheKey: "second" })
  await runtime.decide({ ...base, cacheKey: "first" })
  assert.equal(calls, 3)
})
