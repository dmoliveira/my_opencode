import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("hook-test-parity-guard blocks commit when hook source changes lack hook tests", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-hook-parity-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["hook-test-parity-guard"],
          disabled: [],
        },
        hookTestParityGuard: {
          enabled: true,
          sourcePatterns: ["plugin/gateway-core/src/hooks/**/*.ts"],
          testPatterns: ["plugin/gateway-core/test/*-hook.test.mjs"],
          blockOnMismatch: true,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "write", sessionID: "session-parity" },
      { args: { filePath: "plugin/gateway-core/src/hooks/new-hook/index.ts" } },
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-parity" },
        { args: { command: 'git commit -m "feat"' } },
      ),
      /hook-test-parity-guard/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("hook-test-parity-guard allows commit when hook tests are touched", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-hook-parity-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["hook-test-parity-guard"],
          disabled: [],
        },
        hookTestParityGuard: {
          enabled: true,
          sourcePatterns: ["plugin/gateway-core/src/hooks/**/*.ts"],
          testPatterns: ["plugin/gateway-core/test/*-hook.test.mjs"],
          blockOnMismatch: true,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "write", sessionID: "session-parity-ok" },
      { args: { filePath: "plugin/gateway-core/src/hooks/new-hook/index.ts" } },
    )
    await plugin["tool.execute.before"](
      { tool: "write", sessionID: "session-parity-ok" },
      { args: { filePath: "plugin/gateway-core/test/new-hook-hook.test.mjs" } },
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-parity-ok" },
      { args: { command: 'git commit -m "feat"' } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
