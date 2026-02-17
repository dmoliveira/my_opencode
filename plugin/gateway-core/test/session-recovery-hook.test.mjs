import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("session-recovery resumes recoverable session errors", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-recovery-"))
  try {
    let promptCalls = 0
    let lastPromptBody = null
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["session-recovery"],
          disabled: [],
        },
        sessionRecovery: {
          enabled: true,
          autoResume: true,
        },
      },
      client: {
        session: {
          async messages() {
            return {
              data: [
                {
                  info: {
                    role: "user",
                    agent: "build",
                    model: { providerID: "openai", modelID: "gpt-5.3-codex" },
                  },
                },
              ],
            }
          },
          async promptAsync(args) {
            promptCalls += 1
            lastPromptBody = args.body
          },
        },
      },
    })

    await plugin.event({
      event: {
        type: "session.error",
        properties: {
          sessionID: "session-recovery-1",
          error: { message: "temporary network timeout" },
        },
      },
    })
    assert.equal(promptCalls, 1)
    assert.equal(lastPromptBody?.agent, "build")
    assert.equal(lastPromptBody?.model?.providerID, "openai")
    assert.equal(lastPromptBody?.model?.modelID, "gpt-5.3-codex")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-recovery skips non-recoverable errors", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-recovery-"))
  try {
    let promptCalls = 0
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["session-recovery"],
          disabled: [],
        },
        sessionRecovery: {
          enabled: true,
          autoResume: true,
        },
      },
      client: {
        session: {
          async promptAsync() {
            promptCalls += 1
          },
        },
      },
    })

    await plugin.event({
      event: {
        type: "session.error",
        properties: {
          sessionID: "session-recovery-2",
          error: { message: "validation failed due to malformed payload" },
        },
      },
    })
    assert.equal(promptCalls, 0)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-recovery resumes recoverable errors without message history API", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-recovery-"))
  try {
    let promptCalls = 0
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["session-recovery"],
          disabled: [],
        },
        sessionRecovery: {
          enabled: true,
          autoResume: true,
        },
      },
      client: {
        session: {
          async promptAsync() {
            promptCalls += 1
          },
        },
      },
    })

    await plugin.event({
      event: {
        type: "session.error",
        properties: {
          sessionID: "session-recovery-3",
          error: { message: "temporary network timeout" },
        },
      },
    })
    assert.equal(promptCalls, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-recovery handles prompt injection failure without throwing", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-recovery-"))
  try {
    let promptCalls = 0
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["session-recovery"],
          disabled: [],
        },
        sessionRecovery: {
          enabled: true,
          autoResume: true,
        },
      },
      client: {
        session: {
          async promptAsync() {
            promptCalls += 1
            throw new Error("prompt failed")
          },
        },
      },
    })

    await plugin.event({
      event: {
        type: "session.error",
        properties: {
          sessionID: "session-recovery-4",
          error: { message: "temporary network timeout" },
        },
      },
    })
    assert.equal(promptCalls, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
