import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("docs-drift-guard blocks commit when source changes lack docs updates", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-docs-drift-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["docs-drift-guard"],
          disabled: [],
        },
        docsDriftGuard: {
          enabled: true,
          sourcePatterns: ["src/**"],
          docsPatterns: ["docs/**", "README.md"],
          blockOnDrift: true,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "write", sessionID: "session-docs-drift" },
      { args: { filePath: "src/new.ts" } },
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-docs-drift" },
        { args: { command: 'git commit -m "feat"' } },
      ),
      /docs-drift-guard/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("docs-drift-guard allows commit when docs are touched", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-docs-drift-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["docs-drift-guard"],
          disabled: [],
        },
        docsDriftGuard: {
          enabled: true,
          sourcePatterns: ["src/**"],
          docsPatterns: ["docs/**", "README.md"],
          blockOnDrift: true,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "write", sessionID: "session-docs-ok" },
      { args: { filePath: "src/new.ts" } },
    )
    await plugin["tool.execute.before"](
      { tool: "write", sessionID: "session-docs-ok" },
      { args: { filePath: "docs/new.md" } },
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-docs-ok" },
      { args: { command: 'git commit -m "feat"' } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
