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
          sessionID: "session-recovery-1",
          error: { message: "temporary network timeout" },
        },
      },
    })
    assert.equal(promptCalls, 1)
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
