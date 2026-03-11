import assert from "node:assert/strict"
import test from "node:test"

import { createProviderTokenLimitRecoveryHook } from "../dist/hooks/provider-token-limit-recovery/index.js"

test("provider-token-limit-recovery triggers summarize on token-limit session.error", async () => {
  let summarizeCalls = 0
  let promptCalls = 0
  const hook = createProviderTokenLimitRecoveryHook({
    directory: process.cwd(),
    enabled: true,
    cooldownMs: 60000,
    client: {
      session: {
        async messages() {
          return {
            data: [
              {
                info: {
                  role: "assistant",
                  providerID: "anthropic",
                  modelID: "claude-sonnet-4-5",
                },
              },
            ],
          }
        },
        async summarize() {
          summarizeCalls += 1
        },
        async promptAsync() {
          promptCalls += 1
        },
      },
    },
  })

  await hook.event("session.error", {
    properties: { info: { id: "session-token-limit-1" } },
    error: "maximum context window exceeded",
  })

  assert.equal(summarizeCalls, 1)
  assert.equal(promptCalls, 1)
})

test("provider-token-limit-recovery ignores non-token-limit errors", async () => {
  let summarizeCalls = 0
  const hook = createProviderTokenLimitRecoveryHook({
    directory: process.cwd(),
    enabled: true,
    cooldownMs: 60000,
    client: {
      session: {
        async messages() {
          return { data: [] }
        },
        async summarize() {
          summarizeCalls += 1
        },
        async promptAsync() {
          return
        },
      },
    },
  })

  await hook.event("session.error", {
    properties: { info: { id: "session-token-limit-2" } },
    error: "network timeout",
  })

  assert.equal(summarizeCalls, 0)
})

test("provider-token-limit-recovery skips prompt injection while assistant turn is incomplete", async () => {
  let summarizeCalls = 0
  let promptCalls = 0
  const hook = createProviderTokenLimitRecoveryHook({
    directory: process.cwd(),
    enabled: true,
    cooldownMs: 60000,
    client: {
      session: {
        async messages() {
          return {
            data: [
              {
                info: {
                  role: "assistant",
                  providerID: "anthropic",
                  modelID: "claude-sonnet-4-5",
                  time: {},
                },
              },
            ],
          }
        },
        async summarize() {
          summarizeCalls += 1
        },
        async promptAsync() {
          promptCalls += 1
        },
      },
    },
  })

  await hook.event("session.error", {
    properties: { info: { id: "session-token-limit-incomplete" } },
    error: "maximum context window exceeded",
  })

  assert.equal(summarizeCalls, 1)
  assert.equal(promptCalls, 0)
})

test("provider-token-limit-recovery does not report success when injection fails", async () => {
  let summarizeCalls = 0
  let promptCalls = 0
  const hook = createProviderTokenLimitRecoveryHook({
    directory: process.cwd(),
    enabled: true,
    cooldownMs: 60000,
    client: {
      session: {
        async messages() {
          return {
            data: [
              {
                info: {
                  role: "assistant",
                  providerID: "anthropic",
                  modelID: "claude-sonnet-4-5",
                },
              },
            ],
          }
        },
        async summarize() {
          summarizeCalls += 1
        },
        async promptAsync() {
          promptCalls += 1
          throw new Error("prompt failed")
        },
      },
    },
  })

  await hook.event("session.error", {
    properties: { info: { id: "session-token-limit-inject-fail" } },
    error: "maximum context window exceeded",
  })

  assert.equal(summarizeCalls, 1)
  assert.equal(promptCalls, 1)
})

test("provider-token-limit-recovery falls back to injection when history probe fails", async () => {
  let summarizeCalls = 0
  let promptCalls = 0
  const hook = createProviderTokenLimitRecoveryHook({
    directory: process.cwd(),
    enabled: true,
    cooldownMs: 60000,
    client: {
      session: {
        async messages() {
          throw new Error("history unavailable")
        },
        async summarize() {
          summarizeCalls += 1
        },
        async promptAsync() {
          promptCalls += 1
        },
      },
    },
  })

  await hook.event("session.error", {
    properties: { info: { id: "session-token-limit-probe-fail" } },
    error: "maximum context window exceeded",
  })

  assert.equal(summarizeCalls, 1)
  assert.equal(promptCalls, 1)
})
