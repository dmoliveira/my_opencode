import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("done-proof-enforcer rewrites DONE promise when validation markers are missing", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-done-proof-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["done-proof-enforcer"], disabled: [] },
        doneProofEnforcer: {
          enabled: true,
          requiredMarkers: ["validation", "test", "lint"],
        },
      },
    })
    const output = { output: "all complete\n<promise>DONE</promise>" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-proof" }, output)
    assert.ok(output.output.includes("PENDING_VALIDATION"))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
