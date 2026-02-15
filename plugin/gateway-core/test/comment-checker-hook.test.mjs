import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("comment-checker warns about low-value comments in edit output", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-comment-checker-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["comment-checker"], disabled: [] },
        commentChecker: { enabled: true },
      },
    })
    const output = { output: "// this function simply returns x\nreturn x" }
    await plugin["tool.execute.after"]({ tool: "edit", sessionID: "session-comment" }, output)
    assert.ok(output.output.includes("Potential low-value comment detected"))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
