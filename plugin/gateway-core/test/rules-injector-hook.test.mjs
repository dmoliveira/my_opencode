import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("rules-injector appends runtime rule for bash tool output", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-rules-injector-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["rules-injector"],
          disabled: [],
        },
        rulesInjector: {
          enabled: true,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-rules-1" },
      { args: { command: "ls" } },
    )
    const output = { output: "command output" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-rules-1" }, output)
    assert.ok(output.output.includes("Rule: use non-interactive flags"))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
