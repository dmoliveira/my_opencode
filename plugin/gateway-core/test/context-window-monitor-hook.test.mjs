import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("context-window-monitor appends warning when Anthropic usage is high", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-context-window-"))
  const previousFlag = process.env.ANTHROPIC_1M_CONTEXT
  delete process.env.ANTHROPIC_1M_CONTEXT
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["context-window-monitor"],
          disabled: [],
        },
        contextWindowMonitor: {
          enabled: true,
          warningThreshold: 0.7,
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
                    providerID: "anthropic",
                    tokens: {
                      input: 180000,
                      cache: { read: 0 },
                    },
                  },
                },
              ],
            }
          },
        },
      },
    })

    const output = { output: "tool result" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-context-1" }, output)
    assert.ok(output.output.includes("Context Status"))
    assert.ok(output.output.includes("Context Guard"))
    assert.ok(output.output.includes("[Context Guard]"))
  } finally {
    if (previousFlag === undefined) {
      delete process.env.ANTHROPIC_1M_CONTEXT
    } else {
      process.env.ANTHROPIC_1M_CONTEXT = previousFlag
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

test("context-window-monitor minimal verbosity keeps marker-only notice", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-context-window-"))
  const previousFlag = process.env.ANTHROPIC_1M_CONTEXT
  delete process.env.ANTHROPIC_1M_CONTEXT
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["context-window-monitor"],
          disabled: [],
        },
        contextWindowMonitor: {
          enabled: true,
          warningThreshold: 0.7,
          guardVerbosity: "minimal",
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
                    providerID: "anthropic",
                    tokens: {
                      input: 180000,
                      cache: { read: 0 },
                    },
                  },
                },
              ],
            }
          },
        },
      },
    })

    const output = { output: "tool result" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-context-minimal" }, output)
    assert.ok(output.output.includes("Context Guard"))
    assert.equal(output.output.includes("Context Status"), false)
  } finally {
    if (previousFlag === undefined) {
      delete process.env.ANTHROPIC_1M_CONTEXT
    } else {
      process.env.ANTHROPIC_1M_CONTEXT = previousFlag
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

test("context-window-monitor warns again after cooldown and token growth", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-context-window-"))
  const previousFlag = process.env.ANTHROPIC_1M_CONTEXT
  delete process.env.ANTHROPIC_1M_CONTEXT
  try {
    let messageCalls = 0
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["context-window-monitor"],
          disabled: [],
        },
        contextWindowMonitor: {
          enabled: true,
          warningThreshold: 0.7,
          reminderCooldownToolCalls: 2,
          minTokenDeltaForReminder: 5000,
        },
      },
      client: {
        session: {
          async messages() {
            messageCalls += 1
            const tokensByCall = [190000, 193000, 196000, 197000, 203000]
            const input = tokensByCall[Math.min(messageCalls - 1, tokensByCall.length - 1)]
            return {
              data: [
                {
                  info: {
                    role: "assistant",
                    providerID: "anthropic",
                    tokens: {
                      input,
                      cache: { read: 0 },
                    },
                  },
                },
              ],
            }
          },
        },
      },
    })

    const first = { output: "first" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-context-2" }, first)
    assert.ok(first.output.includes("Context Status"))

    const second = { output: "second" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-context-2" }, second)
    assert.equal(second.output, "second")

    const third = { output: "third" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-context-2" }, third)
    assert.ok(third.output.includes("Context Status"))

    await plugin.event({
      event: {
        type: "session.deleted",
        properties: { info: { id: "session-context-2" } },
      },
    })

    const fourth = { output: "fourth" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-context-2" }, fourth)
    assert.ok(fourth.output.includes("Context Status"))
  } finally {
    if (previousFlag === undefined) {
      delete process.env.ANTHROPIC_1M_CONTEXT
    } else {
      process.env.ANTHROPIC_1M_CONTEXT = previousFlag
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

test("context-window-monitor skips reminder when token delta stays below threshold", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-context-window-"))
  const previousFlag = process.env.ANTHROPIC_1M_CONTEXT
  delete process.env.ANTHROPIC_1M_CONTEXT
  try {
    let messageCalls = 0
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["context-window-monitor"],
          disabled: [],
        },
        contextWindowMonitor: {
          enabled: true,
          warningThreshold: 0.7,
          reminderCooldownToolCalls: 1,
          minTokenDeltaForReminder: 20000,
        },
      },
      client: {
        session: {
          async messages() {
            messageCalls += 1
            const tokensByCall = [190000, 195000]
            const input = tokensByCall[Math.min(messageCalls - 1, tokensByCall.length - 1)]
            return {
              data: [
                {
                  info: {
                    role: "assistant",
                    providerID: "anthropic",
                    tokens: {
                      input,
                      cache: { read: 0 },
                    },
                  },
                },
              ],
            }
          },
        },
      },
    })

    const first = { output: "first" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-context-3" }, first)
    assert.ok(first.output.includes("Context Status"))

    const second = { output: "second" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-context-3" }, second)
    assert.equal(second.output, "second")
  } finally {
    if (previousFlag === undefined) {
      delete process.env.ANTHROPIC_1M_CONTEXT
    } else {
      process.env.ANTHROPIC_1M_CONTEXT = previousFlag
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

test("context-window-monitor prunes old session state when max entries is reached", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-context-window-"))
  const previousFlag = process.env.ANTHROPIC_1M_CONTEXT
  delete process.env.ANTHROPIC_1M_CONTEXT
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["context-window-monitor"],
          disabled: [],
        },
        contextWindowMonitor: {
          enabled: true,
          warningThreshold: 0.7,
          reminderCooldownToolCalls: 99,
          minTokenDeltaForReminder: 999999,
          maxSessionStateEntries: 1,
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
                    providerID: "anthropic",
                    tokens: { input: 180000, cache: { read: 0 } },
                  },
                },
              ],
            }
          },
        },
      },
    })

    const a1 = { output: "a1" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-context-prune-a" }, a1)
    assert.ok(a1.output.includes("Context Guard"))

    const b1 = { output: "b1" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-context-prune-b" }, b1)
    assert.ok(b1.output.includes("Context Guard"))

    const a2 = { output: "a2" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-context-prune-a" }, a2)
    assert.ok(a2.output.includes("Context Guard"))
  } finally {
    if (previousFlag === undefined) {
      delete process.env.ANTHROPIC_1M_CONTEXT
    } else {
      process.env.ANTHROPIC_1M_CONTEXT = previousFlag
    }
    rmSync(directory, { recursive: true, force: true })
  }
})
