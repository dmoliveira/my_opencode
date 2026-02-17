import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import { createTodoContinuationEnforcerHook } from "../dist/hooks/todo-continuation-enforcer/index.js"
import { saveGatewayState } from "../dist/state/storage.js"

test("todo-continuation-enforcer injects on idle when pending marker exists", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-todo-continuation-"))
  try {
    let promptCalls = 0
    const hook = createTodoContinuationEnforcerHook({
      directory,
      enabled: true,
      cooldownMs: 30000,
      maxConsecutiveFailures: 5,
      client: {
        session: {
          async messages() {
            return {
              data: [
                {
                  info: { role: "assistant" },
                  parts: [{ type: "text", text: "pending work\n<CONTINUE-LOOP>" }],
                },
              ],
            }
          },
          async promptAsync() {
            promptCalls += 1
          },
        },
      },
    })

    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-todo-1" },
    })

    assert.equal(promptCalls, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("todo-continuation-enforcer honors cooldown across repeated idles", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-todo-continuation-"))
  try {
    let promptCalls = 0
    const hook = createTodoContinuationEnforcerHook({
      directory,
      enabled: true,
      cooldownMs: 30000,
      maxConsecutiveFailures: 5,
      client: {
        session: {
          async messages() {
            return {
              data: [
                {
                  info: { role: "assistant" },
                  parts: [{ type: "text", text: "pending work\n<CONTINUE-LOOP>" }],
                },
              ],
            }
          },
          async promptAsync() {
            promptCalls += 1
          },
        },
      },
    })

    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-todo-2" },
    })
    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-todo-2" },
    })

    assert.equal(promptCalls, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("todo-continuation-enforcer avoids repeated message polling after no-marker probe", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-todo-continuation-"))
  try {
    let messageCalls = 0
    const hook = createTodoContinuationEnforcerHook({
      directory,
      enabled: true,
      cooldownMs: 30000,
      maxConsecutiveFailures: 5,
      client: {
        session: {
          async messages() {
            messageCalls += 1
            return {
              data: [
                {
                  info: { role: "assistant" },
                  parts: [{ type: "text", text: "no todo marker here" }],
                },
              ],
            }
          },
          async promptAsync() {
            throw new Error("promptAsync should not be called")
          },
        },
      },
    })

    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-todo-2b" },
    })
    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-todo-2b" },
    })

    assert.equal(messageCalls, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("todo-continuation-enforcer skips when active loop is running", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-todo-continuation-"))
  try {
    saveGatewayState(directory, {
      activeLoop: {
        active: true,
        sessionId: "session-todo-3",
        objective: "active loop",
        completionMode: "promise",
        completionPromise: "DONE",
        iteration: 1,
        maxIterations: 0,
        startedAt: new Date().toISOString(),
      },
      lastUpdatedAt: new Date().toISOString(),
      source: "test-fixture",
    })

    let promptCalls = 0
    const hook = createTodoContinuationEnforcerHook({
      directory,
      enabled: true,
      cooldownMs: 30000,
      maxConsecutiveFailures: 5,
      client: {
        session: {
          async messages() {
            return {
              data: [
                {
                  info: { role: "assistant" },
                  parts: [{ type: "text", text: "pending work\n<CONTINUE-LOOP>" }],
                },
              ],
            }
          },
          async promptAsync() {
            promptCalls += 1
          },
        },
      },
    })

    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-todo-3" },
    })

    assert.equal(promptCalls, 0)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("todo-continuation-enforcer tracks task output marker before idle", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-todo-continuation-"))
  try {
    let promptCalls = 0
    const hook = createTodoContinuationEnforcerHook({
      directory,
      enabled: true,
      cooldownMs: 30000,
      maxConsecutiveFailures: 5,
      client: {
        session: {
          async messages() {
            throw new Error("messages should not be called when marker is tracked")
          },
          async promptAsync() {
            promptCalls += 1
          },
        },
      },
    })

    await hook.event("tool.execute.after", {
      directory,
      input: { tool: "task", sessionID: "session-todo-4" },
      output: { output: "work remains\n<CONTINUE-LOOP>" },
    })
    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-todo-4" },
    })

    assert.equal(promptCalls, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("todo-continuation-enforcer handles probe failures without throwing", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-todo-continuation-"))
  try {
    let promptCalls = 0
    const hook = createTodoContinuationEnforcerHook({
      directory,
      enabled: true,
      cooldownMs: 30000,
      maxConsecutiveFailures: 5,
      client: {
        session: {
          async messages() {
            throw new Error("transient probe failure")
          },
          async promptAsync() {
            promptCalls += 1
          },
        },
      },
    })

    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-todo-5" },
    })

    assert.equal(promptCalls, 0)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
