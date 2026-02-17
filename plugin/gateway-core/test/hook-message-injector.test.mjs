import assert from "node:assert/strict"
import test from "node:test"

import { injectHookMessage } from "../dist/hooks/hook-message-injector/index.js"

test("injectHookMessage returns false when prompt injection fails", async () => {
  const result = await injectHookMessage({
    session: {
      async promptAsync() {
        throw new Error("prompt failed")
      },
    },
    sessionId: "session-failure",
    content: "continue",
    directory: "/tmp",
  })

  assert.equal(result, false)
})

test("injectHookMessage works without messages history API", async () => {
  let promptCalls = 0
  const result = await injectHookMessage({
    session: {
      async promptAsync() {
        promptCalls += 1
      },
    },
    sessionId: "session-minimal",
    content: "continue",
    directory: "/tmp",
  })

  assert.equal(result, true)
  assert.equal(promptCalls, 1)
})
