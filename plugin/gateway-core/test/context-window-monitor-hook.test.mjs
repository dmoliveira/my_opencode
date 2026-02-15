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
  } finally {
    if (previousFlag === undefined) {
      delete process.env.ANTHROPIC_1M_CONTEXT
    } else {
      process.env.ANTHROPIC_1M_CONTEXT = previousFlag
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

test("context-window-monitor warns only once until session deletion", async () => {
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
                      input: 190000,
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

    await plugin.event({
      event: {
        type: "session.deleted",
        properties: { info: { id: "session-context-2" } },
      },
    })

    const third = { output: "third" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-context-2" }, third)
    assert.ok(third.output.includes("Context Status"))
  } finally {
    if (previousFlag === undefined) {
      delete process.env.ANTHROPIC_1M_CONTEXT
    } else {
      process.env.ANTHROPIC_1M_CONTEXT = previousFlag
    }
    rmSync(directory, { recursive: true, force: true })
  }
})
