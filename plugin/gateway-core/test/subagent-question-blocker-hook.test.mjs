import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("subagent-question-blocker blocks question tool for subagent-like session", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-subagent-question-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["subagent-question-blocker"],
          disabled: [],
        },
        subagentQuestionBlocker: {
          enabled: true,
          sessionPatterns: ["task-"],
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "question", sessionID: "task-123" },
        { args: {} },
      ),
      /disabled for subagent sessions/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("subagent-question-blocker allows question tool for normal session", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-subagent-question-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["subagent-question-blocker"],
          disabled: [],
        },
        subagentQuestionBlocker: {
          enabled: true,
          sessionPatterns: ["task-"],
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "question", sessionID: "session-123" },
      { args: {} },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
