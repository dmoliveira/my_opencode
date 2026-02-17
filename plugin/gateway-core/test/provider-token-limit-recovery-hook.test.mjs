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
