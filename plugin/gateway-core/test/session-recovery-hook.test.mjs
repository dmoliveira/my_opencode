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

test("session-recovery skips injection while assistant turn is incomplete", async () => {
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
          async messages() {
            return {
              data: [
                {
                  info: {
                    role: "assistant",
                    time: {},
                  },
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

    await plugin.event({
      event: {
        type: "session.error",
        properties: {
          sessionID: "session-recovery-incomplete",
          error: { message: "temporary network timeout" },
        },
      },
    })
    assert.equal(promptCalls, 0)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-recovery falls back to injection when history probe fails", async () => {
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
          async messages() {
            throw new Error("history unavailable")
          },
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
          sessionID: "session-recovery-probe-fail",
          error: { message: "temporary network timeout" },
        },
      },
    })
    assert.equal(promptCalls, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-recovery injects parent continuation after delegated task abort", async () => {
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
                    role: "assistant",
                    time: { completed: Date.now() },
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

    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-recovery-task-abort" },
      {
        output: {
          output: {
            state: {
              status: "error",
              error: "Tool execution aborted",
              metadata: { sessionId: "child-session-aborted" },
            },
          },
        },
      }
    )

    assert.equal(promptCalls, 1)
    assert.equal(lastPromptBody?.parts?.[0]?.type, "text")
    assert.match(lastPromptBody?.parts?.[0]?.text ?? "", /delegated task aborted - continuing in parent turn/)
    assert.match(lastPromptBody?.parts?.[0]?.text ?? "", /child-session-aborted/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-recovery forces delegated abort injection even with incomplete parent turn", async () => {
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
          async messages() {
            return {
              data: [
                {
                  info: {
                    role: "assistant",
                    time: {},
                  },
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

    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-recovery-task-abort-incomplete" },
      {
        output: {
          output: {
            state: {
              status: "error",
              error: "Tool execution aborted",
              metadata: { sessionId: "child-session-incomplete" },
            },
          },
        },
      }
    )

    assert.equal(promptCalls, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-recovery rescues silent delegated abort on idle using message history", async () => {
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
                    role: "assistant",
                    error: { message: "The operation was aborted." },
                    time: {},
                  },
                  parts: [
                    {
                      type: "tool",
                      tool: "task",
                      state: {
                        status: "error",
                        error: "Tool execution aborted",
                        metadata: { sessionId: "child-session-idle-abort" },
                      },
                    },
                  ],
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
        type: "session.idle",
        directory,
        properties: {
          sessionID: "session-recovery-idle-abort",
        },
      },
    })

    assert.equal(promptCalls, 1)
    assert.match(
      lastPromptBody?.parts?.[0]?.text ?? "",
      /stuck delegated abort detected during idle - continuing in parent turn/,
    )
    assert.match(lastPromptBody?.parts?.[0]?.text ?? "", /child-session-idle-abort/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-recovery ignores idle rescue when aborted parent already has visible text", async () => {
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
          async messages() {
            return {
              data: [
                {
                  info: {
                    role: "assistant",
                    error: { message: "The operation was aborted." },
                    time: {},
                  },
                  parts: [
                    { type: "text", text: "I hit an abort but already explained it." },
                    {
                      type: "tool",
                      tool: "task",
                      state: {
                        status: "error",
                        error: "Tool execution aborted",
                        metadata: { sessionId: "child-session-visible-text" },
                      },
                    },
                  ],
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

    await plugin.event({
      event: {
        type: "session.idle",
        directory,
        properties: {
          sessionID: "session-recovery-idle-visible-text",
        },
      },
    })

    assert.equal(promptCalls, 0)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-recovery rescues stale running question tool on idle using message history", async () => {
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
                    role: "assistant",
                    time: {},
                  },
                  parts: [
                    {
                      type: "tool",
                      tool: "question",
                      state: {
                        status: "running",
                      },
                    },
                  ],
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
        type: "session.idle",
        directory,
        properties: {
          sessionID: "session-recovery-idle-question-stall",
        },
      },
    })

    assert.equal(promptCalls, 1)
    assert.match(
      lastPromptBody?.parts?.[0]?.text ?? "",
      /stuck question tool detected during idle - interactive prompt did not complete/i,
    )
    assert.match(
      lastPromptBody?.parts?.[0]?.text ?? "",
      /reply with your preference in a normal message/i,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-recovery ignores stale question rescue when latest message is user reply", async () => {
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
          async messages() {
            return {
              data: [
                {
                  info: {
                    role: "assistant",
                    time: {},
                  },
                  parts: [
                    {
                      type: "tool",
                      tool: "question",
                      state: {
                        status: "running",
                      },
                    },
                  ],
                },
                {
                  info: {
                    role: "user",
                  },
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

    await plugin.event({
      event: {
        type: "session.idle",
        directory,
        properties: {
          sessionID: "session-recovery-idle-question-user-replied",
        },
      },
    })

    assert.equal(promptCalls, 0)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-recovery ignores stale question rescue when question is not last tool part", async () => {
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
          async messages() {
            return {
              data: [
                {
                  info: {
                    role: "assistant",
                    time: {},
                  },
                  parts: [
                    {
                      type: "tool",
                      tool: "question",
                      state: {
                        status: "running",
                      },
                    },
                    {
                      type: "tool",
                      tool: "read",
                      state: {
                        status: "completed",
                      },
                    },
                  ],
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

    await plugin.event({
      event: {
        type: "session.idle",
        directory,
        properties: {
          sessionID: "session-recovery-idle-question-not-last-tool",
        },
      },
    })

    assert.equal(promptCalls, 0)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-recovery rescues stale running askuserquestion tool on idle using message history", async () => {
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
          async messages() {
            return {
              data: [
                {
                  info: {
                    role: "assistant",
                    time: {},
                  },
                  parts: [
                    {
                      type: "tool",
                      tool: "askuserquestion",
                      state: {
                        status: "running",
                      },
                    },
                  ],
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

    await plugin.event({
      event: {
        type: "session.idle",
        directory,
        properties: {
          sessionID: "session-recovery-idle-askuserquestion-stall",
        },
      },
    })

    assert.equal(promptCalls, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
