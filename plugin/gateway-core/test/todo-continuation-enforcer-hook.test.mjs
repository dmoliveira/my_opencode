import assert from "node:assert/strict"
import { mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import { createTodoContinuationEnforcerHook } from "../dist/hooks/todo-continuation-enforcer/index.js"
import { saveGatewayState } from "../dist/state/storage.js"

function mockDecisionRuntime(char, mode = "assist") {
  const calls = []
  return {
    calls,
    config: { mode },
    async decide(request) {
      calls.push(request)
      return {
        mode,
        accepted: true,
        char,
        raw: char,
        durationMs: 1,
        model: "test-model",
        templateId: request.templateId,
        meaning:
          char === "C"
            ? "continue_now"
            : char === "U"
              ? "unclear"
              : "no_pending",
      }
    },
  }
}

function readGatewayAuditEvents(directory) {
  const auditPath = join(directory, ".opencode", "gateway-events.jsonl")
  return readFileSync(auditPath, "utf-8")
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line))
}

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

test("todo-continuation-enforcer refreshes message probe after a later chat turn", async () => {
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
              data: messageCalls === 1
                ? [{ info: { role: "assistant" }, parts: [{ type: "text", text: "no todo marker here" }] }]
                : [{ info: { role: "assistant" }, parts: [{ type: "text", text: "pending work\n<CONTINUE-LOOP>" }] }],
            }
          },
          async promptAsync() {},
        },
      },
    })

    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-todo-refresh" },
    })
    await hook.event("chat.message", {
      directory,
      properties: { sessionID: "session-todo-refresh", prompt: "please keep going" },
    })
    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-todo-refresh" },
    })

    assert.ok(messageCalls >= 2)
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

test("todo-continuation-enforcer uses LLM fallback for mixed-signal next-slice wording", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-todo-continuation-"))
  try {
    let promptCalls = 0
    const decisionRuntime = mockDecisionRuntime("C")
    const hook = createTodoContinuationEnforcerHook({
      directory,
      enabled: true,
      cooldownMs: 30000,
      maxConsecutiveFailures: 5,
      decisionRuntime,
      client: {
        session: {
          async messages() {
            throw new Error("messages should not be called when task output is tracked")
          },
          async promptAsync() {
            promptCalls += 1
          },
        },
      },
    })

    await hook.event("tool.execute.after", {
      directory,
      input: { tool: "task", sessionID: "session-todo-llm-1" },
      output: {
        output: `I checked before proceeding: the broader label support is already included in the current released state.

Current state
- v0.7.0 already contains the broader label rollout
- v0.7.1 adds JSON/output contract hardening

So there is nothing additional to release for labels right now.

Best next safe slice
1. README/spec full runtime alignment
2. then cut a docs/runtime-alignment release if the diff is meaningful

If you want, I'll continue directly with that docs alignment pass.`,
      },
    })
    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-todo-llm-1" },
    })

    assert.equal(promptCalls, 1)
    assert.equal(decisionRuntime.calls.length, 1)
    assert.equal(decisionRuntime.calls[0].templateId, "todo-continuation-decision-v1")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("todo-continuation-enforcer defers LLM continuation in shadow mode", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-todo-continuation-"))
  try {
    let promptCalls = 0
    const decisionRuntime = mockDecisionRuntime("C", "shadow")
    const hook = createTodoContinuationEnforcerHook({
      directory,
      enabled: true,
      cooldownMs: 30000,
      maxConsecutiveFailures: 5,
      decisionRuntime,
      client: {
        session: {
          async messages() {
            throw new Error("messages should not be called when task output is tracked")
          },
          async promptAsync() {
            promptCalls += 1
          },
        },
      },
    })

    await hook.event("tool.execute.after", {
      directory,
      input: { tool: "task", sessionID: "session-todo-llm-2" },
      output: {
        output: "Task complete for now. Best next safe slice: docs alignment. If you want, I'll continue directly with that pass.",
      },
    })
    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-todo-llm-2" },
    })

    assert.equal(promptCalls, 0)
    assert.equal(decisionRuntime.calls.length, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("todo-continuation-enforcer does not call LLM for generic future suggestions", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-todo-continuation-"))
  try {
    let promptCalls = 0
    const decisionRuntime = mockDecisionRuntime("C")
    const hook = createTodoContinuationEnforcerHook({
      directory,
      enabled: true,
      cooldownMs: 30000,
      maxConsecutiveFailures: 5,
      decisionRuntime,
      client: {
        session: {
          async messages() {
            throw new Error("messages should not be called when task output is tracked")
          },
          async promptAsync() {
            promptCalls += 1
          },
        },
      },
    })

    await hook.event("tool.execute.after", {
      directory,
      input: { tool: "task", sessionID: "session-todo-llm-3" },
      output: {
        output: "Task is complete. If you want, you may want to update the README later.",
      },
    })
    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-todo-llm-3" },
    })

    assert.equal(promptCalls, 0)
    assert.equal(decisionRuntime.calls.length, 0)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("todo-continuation-enforcer skips on invalid LLM decision response", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-todo-continuation-"))
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  try {
    let promptCalls = 0
    const hook = createTodoContinuationEnforcerHook({
      directory,
      enabled: true,
      cooldownMs: 30000,
      maxConsecutiveFailures: 5,
      decisionRuntime: {
        config: { mode: "assist" },
        async decide() {
          return {
            mode: "assist",
            accepted: false,
            char: "",
            raw: "maybe continue",
            durationMs: 1,
            model: "test-model",
            templateId: "todo-continuation-decision-v1",
            skippedReason: "invalid_response",
          }
        },
      },
      client: {
        session: {
          async messages() {
            throw new Error("messages should not be called when task output is tracked")
          },
          async promptAsync() {
            promptCalls += 1
          },
        },
      },
    })

    await hook.event("tool.execute.after", {
      directory,
      input: { tool: "task", sessionID: "session-todo-llm-invalid", traceId: "trace-invalid" },
      output: {
        output: "Task complete for now. Best next safe slice: docs alignment. If you want, I'll continue directly with that pass.",
      },
    })
    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-todo-llm-invalid" },
    })

    assert.equal(promptCalls, 0)
    const events = readGatewayAuditEvents(directory)
    const skipped = events.find((entry) => entry.reason_code === "llm_todo_continuation_decision_skipped")
    assert.ok(skipped)
    assert.equal(skipped.trace_id, "trace-invalid")
    assert.equal(skipped.llm_decision_reason, "invalid_response")
  } finally {
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

test("todo-continuation-enforcer tolerates LLM runtime failures", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-todo-continuation-"))
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  try {
    let promptCalls = 0
    const hook = createTodoContinuationEnforcerHook({
      directory,
      enabled: true,
      cooldownMs: 30000,
      maxConsecutiveFailures: 5,
      decisionRuntime: {
        config: { mode: "assist" },
        async decide() {
          throw new Error("decision runtime unavailable")
        },
      },
      client: {
        session: {
          async messages() {
            throw new Error("messages should not be called when task output is tracked")
          },
          async promptAsync() {
            promptCalls += 1
          },
        },
      },
    })

    await hook.event("tool.execute.after", {
      directory,
      input: { tool: "task", sessionID: "session-todo-llm-error", trace_id: "trace-error" },
      output: {
        output: "There is nothing additional to release right now. Best next safe slice: align README and spec. If you want, I'll continue directly with that docs alignment pass.",
      },
    })
    await hook.event("session.idle", {
      directory,
      properties: { sessionID: "session-todo-llm-error" },
    })

    assert.equal(promptCalls, 0)
    const events = readGatewayAuditEvents(directory)
    const failed = events.find((entry) => entry.reason_code === "llm_todo_continuation_decision_failed")
    assert.ok(failed)
    assert.equal(failed.trace_id, "trace-error")
    assert.match(String(failed.error ?? ""), /decision runtime unavailable/)
  } finally {
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    }
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

test("todo-continuation-enforcer defers injection while latest assistant turn is incomplete", async () => {
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
                  info: { role: "assistant", time: {} },
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
      properties: { sessionID: "session-todo-incomplete" },
    })

    assert.equal(promptCalls, 0)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
