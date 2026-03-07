import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("delegation-fallback-orchestrator applies fallback only to matching failed delegation trace", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-fallback-orchestrator-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["delegation-fallback-orchestrator"],
          disabled: [],
        },
        delegationFallbackOrchestrator: {
          enabled: true,
        },
      },
    })

    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-fallback-1" },
      {
        args: {
          subagent_type: "reviewer",
          category: "critical",
          prompt: "[DELEGATION TRACE failed-trace] failed delegation",
        },
        output: "[ERROR] Invalid arguments",
      },
    )

    const unaffected = {
      args: {
        subagent_type: "reviewer",
        category: "critical",
        prompt: "[DELEGATION TRACE other-trace] unaffected delegation",
      },
    }
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-fallback-1" },
      unaffected,
    )
    assert.equal(unaffected.args.subagent_type, "reviewer")
    assert.equal(unaffected.args.category, "critical")

    const fallback = {
      args: {
        subagent_type: "reviewer",
        category: "critical",
        prompt: "[DELEGATION TRACE failed-trace] retry delegation",
      },
    }
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-fallback-1" },
      fallback,
    )
    assert.equal(fallback.args.category, "general")
    assert.match(String(fallback.args.prompt), /delegation-fallback-orchestrator/i)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
