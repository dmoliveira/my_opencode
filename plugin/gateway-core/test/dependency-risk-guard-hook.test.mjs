import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("dependency-risk-guard blocks lockfile edits", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-dependency-risk-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["dependency-risk-guard"], disabled: [] },
        dependencyRiskGuard: {
          enabled: true,
          lockfilePatterns: ["package-lock.json"],
        },
      },
    })
    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "write", sessionID: "session-deps" },
        { args: { filePath: "package-lock.json" } },
      ),
      /Lockfile\/dependency edits require explicit security validation/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
