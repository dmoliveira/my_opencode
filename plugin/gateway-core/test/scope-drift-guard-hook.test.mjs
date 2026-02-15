import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("scope-drift-guard blocks edits outside configured path prefixes", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-scope-drift-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["scope-drift-guard"], disabled: [] },
        scopeDriftGuard: {
          enabled: true,
          allowedPaths: ["src/"],
          blockOnDrift: true,
        },
      },
    })
    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "write", sessionID: "session-scope" },
        { args: { filePath: "README.md" } },
      ),
      /outside allowed scope/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
