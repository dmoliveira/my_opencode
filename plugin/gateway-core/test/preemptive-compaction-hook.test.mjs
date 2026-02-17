import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("preemptive-compaction triggers summarize on high usage", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-preemptive-compaction-"))
  const previousFlag = process.env.ANTHROPIC_1M_CONTEXT
  delete process.env.ANTHROPIC_1M_CONTEXT
  try {
    let summarizeCalls = 0
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["preemptive-compaction"],
          disabled: [],
        },
        preemptiveCompaction: {
          enabled: true,
          warningThreshold: 0.78,
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
                    modelID: "claude-3-7-sonnet",
                    tokens: {
                      input: 180000,
                      cache: { read: 0 },
                    },
                  },
                },
              ],
            }
          },
          async summarize() {
            summarizeCalls += 1
          },
        },
      },
    })

    const output = { output: "ok" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-compaction-1" }, output)
    assert.equal(summarizeCalls, 1)
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

test("preemptive-compaction minimal verbosity keeps concise marker", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-preemptive-compaction-"))
  const previousFlag = process.env.ANTHROPIC_1M_CONTEXT
  delete process.env.ANTHROPIC_1M_CONTEXT
  try {
    let summarizeCalls = 0
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["preemptive-compaction"],
          disabled: [],
        },
        preemptiveCompaction: {
          enabled: true,
          warningThreshold: 0.78,
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
                    modelID: "claude-3-7-sonnet",
                    tokens: {
                      input: 180000,
                      cache: { read: 0 },
                    },
                  },
                },
              ],
            }
          },
          async summarize() {
            summarizeCalls += 1
          },
        },
      },
    })

    const output = { output: "ok" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-compaction-minimal" }, output)
    assert.equal(summarizeCalls, 1)
    assert.ok(output.output.includes("Preemptive compaction triggered."))
    assert.equal(output.output.includes("reduce context pressure"), false)
  } finally {
    if (previousFlag === undefined) {
      delete process.env.ANTHROPIC_1M_CONTEXT
    } else {
      process.env.ANTHROPIC_1M_CONTEXT = previousFlag
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

test("preemptive-compaction re-compacts after cooldown and token growth", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-preemptive-compaction-"))
  const previousFlag = process.env.ANTHROPIC_1M_CONTEXT
  delete process.env.ANTHROPIC_1M_CONTEXT
  try {
    let summarizeCalls = 0
    let messageCalls = 0
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["preemptive-compaction"],
          disabled: [],
        },
        preemptiveCompaction: {
          enabled: true,
          warningThreshold: 0.78,
          compactionCooldownToolCalls: 2,
          minTokenDeltaForCompaction: 5000,
        },
      },
      client: {
        session: {
          async messages() {
            messageCalls += 1
            const tokensByCall = [185000, 189000, 195000, 196000, 205000]
            const input = tokensByCall[Math.min(messageCalls - 1, tokensByCall.length - 1)]
            return {
              data: [
                {
                  info: {
                    role: "assistant",
                    providerID: "anthropic",
                    modelID: "claude-3-7-sonnet",
                    tokens: {
                      input,
                      cache: { read: 0 },
                    },
                  },
                },
              ],
            }
          },
          async summarize() {
            summarizeCalls += 1
          },
        },
      },
    })

    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-compaction-2" }, { output: "ok" })
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-compaction-2" }, { output: "ok" })
    assert.equal(summarizeCalls, 1)

    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-compaction-2" }, { output: "ok" })
    assert.equal(summarizeCalls, 2)

    await plugin.event({
      event: {
        type: "session.deleted",
        properties: { info: { id: "session-compaction-2" } },
      },
    })
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-compaction-2" }, { output: "ok" })
    assert.equal(summarizeCalls, 3)
  } finally {
    if (previousFlag === undefined) {
      delete process.env.ANTHROPIC_1M_CONTEXT
    } else {
      process.env.ANTHROPIC_1M_CONTEXT = previousFlag
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

test("preemptive-compaction skips repeat when token delta stays below threshold", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-preemptive-compaction-"))
  const previousFlag = process.env.ANTHROPIC_1M_CONTEXT
  delete process.env.ANTHROPIC_1M_CONTEXT
  try {
    let summarizeCalls = 0
    let messageCalls = 0
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["preemptive-compaction"],
          disabled: [],
        },
        preemptiveCompaction: {
          enabled: true,
          warningThreshold: 0.78,
          compactionCooldownToolCalls: 1,
          minTokenDeltaForCompaction: 20000,
        },
      },
      client: {
        session: {
          async messages() {
            messageCalls += 1
            const tokensByCall = [185000, 190000]
            const input = tokensByCall[Math.min(messageCalls - 1, tokensByCall.length - 1)]
            return {
              data: [
                {
                  info: {
                    role: "assistant",
                    providerID: "anthropic",
                    modelID: "claude-3-7-sonnet",
                    tokens: {
                      input,
                      cache: { read: 0 },
                    },
                  },
                },
              ],
            }
          },
          async summarize() {
            summarizeCalls += 1
          },
        },
      },
    })

    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-compaction-3" }, { output: "ok" })
    assert.equal(summarizeCalls, 1)
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-compaction-3" }, { output: "ok" })
    assert.equal(summarizeCalls, 1)
  } finally {
    if (previousFlag === undefined) {
      delete process.env.ANTHROPIC_1M_CONTEXT
    } else {
      process.env.ANTHROPIC_1M_CONTEXT = previousFlag
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

test("preemptive-compaction prunes old session state when max entries is reached", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-preemptive-compaction-"))
  const previousFlag = process.env.ANTHROPIC_1M_CONTEXT
  delete process.env.ANTHROPIC_1M_CONTEXT
  try {
    let summarizeCalls = 0
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["preemptive-compaction"],
          disabled: [],
        },
        preemptiveCompaction: {
          enabled: true,
          warningThreshold: 0.78,
          compactionCooldownToolCalls: 99,
          minTokenDeltaForCompaction: 999999,
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
                    modelID: "claude-3-7-sonnet",
                    tokens: { input: 180000, cache: { read: 0 } },
                  },
                },
              ],
            }
          },
          async summarize() {
            summarizeCalls += 1
          },
        },
      },
    })

    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-compaction-prune-a" }, { output: "a1" })
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-compaction-prune-b" }, { output: "b1" })
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-compaction-prune-a" }, { output: "a2" })
    assert.equal(summarizeCalls, 3)
  } finally {
    if (previousFlag === undefined) {
      delete process.env.ANTHROPIC_1M_CONTEXT
    } else {
      process.env.ANTHROPIC_1M_CONTEXT = previousFlag
    }
    rmSync(directory, { recursive: true, force: true })
  }
})
