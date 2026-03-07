import assert from "node:assert/strict"
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("agent-model-resolver prepends thinking effort label for task descriptions", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-agent-model-resolver-"))
  try {
    const specsDir = join(directory, "agent", "specs")
    mkdirSync(specsDir, { recursive: true })
    writeFileSync(
      join(specsDir, "explore.json"),
      JSON.stringify({ name: "explore", metadata: { default_category: "quick" } }),
      "utf-8",
    )

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["agent-model-resolver"],
          disabled: [],
        },
      },
    })

    const output = {
      args: {
        subagent_type: "explore",
        description: "Scout repository patterns",
        prompt: "Inspect code paths",
      },
    }
    await plugin["tool.execute.before"]({ tool: "task", sessionID: "session-effort" }, output)

    assert.equal(String(output.args.category ?? ""), "quick")
    assert.match(
      String(output.args.description ?? ""),
      /^\[SUBAGENT\].*explore.*\[scan\].*effort=low/m,
    )
    assert.match(String(output.args.description ?? ""), /^\[THINKING EFFORT\] low/m)
    assert.match(String(output.args.description ?? ""), /\[MODEL ROUTING\].*reasoning=low/i)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
