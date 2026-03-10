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

test("todo-continuation-enforcer does not auto-continue soft next-steps cues without continue intent", async () => {
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
      input: { tool: "task", sessionID: "session-todo-6" },
      output: {
        output:
          "Task is finished. Natural next steps:\n1. Run focused tests\nIf you want, I can do this next.",
      },
    })
    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-todo-6" },
    })

    assert.equal(promptCalls, 0)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("todo-continuation-enforcer auto-continues soft next-steps cues when continue intent is armed", async () => {
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

    await hook.event("chat.message", {
      directory,
      properties: { sessionID: "session-todo-7", prompt: "yes, let's do it" },
    })
    await hook.event("tool.execute.after", {
      directory,
      input: { tool: "task", sessionID: "session-todo-7" },
      output: {
        output:
          "Task is finished. Natural next steps:\n1. Run focused tests\nIf you want, I can do this next.",
      },
    })
    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-todo-7" },
    })

    assert.equal(promptCalls, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("todo-continuation-enforcer disarms continuation after explicit stop intent", async () => {
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

    await hook.event("chat.message", {
      directory,
      properties: { sessionID: "session-todo-8", prompt: "yes, let's do it" },
    })
    await hook.event("tool.execute.after", {
      directory,
      input: { tool: "task", sessionID: "session-todo-8" },
      output: { output: "work remains\n<CONTINUE-LOOP>" },
    })
    await hook.event("chat.message", {
      directory,
      properties: { sessionID: "session-todo-8", prompt: "stop for now" },
    })
    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-todo-8" },
    })

    assert.equal(promptCalls, 0)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("todo-continuation-enforcer ignores negated continue intent", async () => {
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

    await hook.event("chat.message", {
      directory,
      properties: { sessionID: "session-todo-9", prompt: "please do not continue yet" },
    })
    await hook.event("tool.execute.after", {
      directory,
      input: { tool: "task", sessionID: "session-todo-9" },
      output: {
        output:
          "Task is finished. Natural next steps:\n1. Run focused tests\nIf you want, I can do this next.",
      },
    })
    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-todo-9" },
    })

    assert.equal(promptCalls, 0)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("todo-continuation-enforcer injects on epic progress summary with remaining items", async () => {
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
                  parts: [{ type: "text", text: "Epic 4 in progress. Completed 3/7 tasks. Next items: 4. add tests 5. rerun build. Remaining tasks exist." }],
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
      properties: { sessionID: "session-todo-10" },
    })

    assert.equal(promptCalls, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("todo-continuation-enforcer does not inject on progress summary without pending cues", async () => {
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
                  parts: [{ type: "text", text: "Epic 4 complete. All 7 tasks are done. Summary: tests passed and build succeeded." }],
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
      properties: { sessionID: "session-todo-11" },
    })

    assert.equal(promptCalls, 0)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("todo-continuation-enforcer clears pending state when a later task output reports completion", async () => {
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
      input: { tool: "task", sessionID: "session-todo-12" },
      output: { output: "Task 3/7 complete. Remaining tasks exist.\n<CONTINUE-LOOP>" },
    })
    await hook.event("tool.execute.after", {
      directory,
      input: { tool: "task", sessionID: "session-todo-12" },
      output: { output: "Task 7/7 complete. All tasks are done." },
    })
    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-todo-12" },
    })

    assert.equal(promptCalls, 0)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("todo-continuation-enforcer injects on remaining epic and continue loop phrasing", async () => {
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
                  parts: [{ type: "text", text: "Next remaining epic - E6 parity scoreboard and drift checks. Continue Loop." }],
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
      properties: { sessionID: "session-todo-13" },
    })

    assert.equal(promptCalls, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("todo-continuation-enforcer treats next safe steps as soft cue when continue intent is armed", async () => {
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

    await hook.event("chat.message", {
      directory,
      properties: { sessionID: "session-todo-14", prompt: "continue" },
    })
    await hook.event("tool.execute.after", {
      directory,
      input: { tool: "task", sessionID: "session-todo-14" },
      output: { output: "Task complete for now. Next safe steps: rerun lint and validate drift. If you want, I can continue." },
    })
    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-todo-14" },
    })

    assert.equal(promptCalls, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("todo-continuation-enforcer does not inject on informational in-progress summary", async () => {
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
                  parts: [{ type: "text", text: "Epic 4 is in progress. Waiting on telemetry collection before any next action." }],
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
      properties: { sessionID: "session-todo-15" },
    })

    assert.equal(promptCalls, 0)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("todo-continuation-enforcer does not inject on remaining epic when user asked to wait", async () => {
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
                  parts: [{ type: "text", text: "Next remaining epic - E6 parity scoreboard and drift checks. Waiting for telemetry; do not continue yet." }],
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

    await hook.event("chat.message", {
      directory,
      properties: { sessionID: "session-todo-16", prompt: "please do not continue yet" },
    })
    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-todo-16" },
    })

    assert.equal(promptCalls, 0)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
