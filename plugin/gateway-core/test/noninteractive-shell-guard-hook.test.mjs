import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("noninteractive-shell-guard blocks interactive and prompt-prone shell commands", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-noninteractive-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["noninteractive-shell-guard"],
          disabled: ["dependency-risk-guard"],
        },
        noninteractiveShellGuard: {
          enabled: true,
          blockedPatterns: ["\\bgit\\s+add\\s+-p\\b"],
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-noninteractive" },
        { args: { command: "git add -p" } },
      ),
      /noninteractive-shell-guard/,
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-noninteractive" },
        { args: { command: "npm install" } },
      ),
      /npm install --yes/,
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-noninteractive" },
      { args: { command: "npm install --yes" } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
