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

    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-compaction-1" }, { output: "ok" })
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

test("preemptive-compaction only compacts once per session until cleanup", async () => {
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
                      input: 185000,
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

    await plugin.event({
      event: {
        type: "session.deleted",
        properties: { info: { id: "session-compaction-2" } },
      },
    })
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-compaction-2" }, { output: "ok" })
    assert.equal(summarizeCalls, 2)
  } finally {
    if (previousFlag === undefined) {
      delete process.env.ANTHROPIC_1M_CONTEXT
    } else {
      process.env.ANTHROPIC_1M_CONTEXT = previousFlag
    }
    rmSync(directory, { recursive: true, force: true })
  }
})
