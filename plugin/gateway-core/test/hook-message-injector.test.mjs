import assert from "node:assert/strict"
import test from "node:test"

import {
  buildHookMessageBody,
  injectHookMessage,
  resolveHookMessageIdentity,
} from "../dist/hooks/hook-message-injector/index.js"

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

test("resolveHookMessageIdentity extracts agent and model from recent user/system message", async () => {
  const identity = await resolveHookMessageIdentity({
    session: {
      async messages() {
        return {
          data: [
            { info: { role: "assistant", agent: "ignored" } },
            {
              info: {
                role: "user",
                agent: "build",
                model: { providerID: "openai", modelID: "gpt-5.3-codex", variant: "fast" },
              },
            },
          ],
        }
      },
      async promptAsync() {},
    },
    sessionId: "session-identity",
    directory: "/tmp",
  })

  assert.equal(identity.agent, "build")
  assert.equal(identity.model?.providerID, "openai")
  assert.equal(identity.model?.modelID, "gpt-5.3-codex")
  assert.equal(identity.model?.variant, "fast")
})

test("resolveHookMessageIdentity collects split agent/model metadata across messages", async () => {
  const identity = await resolveHookMessageIdentity({
    session: {
      async messages() {
        return {
          data: [
            {
              info: {
                role: "system",
                model: { providerID: "openai", modelID: "gpt-5.3-codex" },
              },
            },
            {
              info: {
                role: "user",
                agent: "build",
              },
            },
          ],
        }
      },
      async promptAsync() {},
    },
    sessionId: "session-identity-split",
    directory: "/tmp",
  })

  assert.equal(identity.agent, "build")
  assert.equal(identity.model?.providerID, "openai")
  assert.equal(identity.model?.modelID, "gpt-5.3-codex")
})

test("buildHookMessageBody includes metadata only when present", () => {
  const body = buildHookMessageBody("continue work", {
    agent: "build",
    model: { providerID: "openai", modelID: "gpt-5.3-codex" },
  })
  assert.equal(body.agent, "build")
  assert.equal(body.model?.providerID, "openai")
  assert.equal(body.parts[0]?.text, "continue work")

  const bodyWithoutIdentity = buildHookMessageBody("continue work", {})
  assert.equal("agent" in bodyWithoutIdentity, false)
  assert.equal("model" in bodyWithoutIdentity, false)
  assert.equal(bodyWithoutIdentity.parts[0]?.text, "continue work")
})
