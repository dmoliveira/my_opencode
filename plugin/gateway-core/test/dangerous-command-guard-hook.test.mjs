import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("dangerous-command-guard blocks destructive bash commands", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-dangerous-command-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["dangerous-command-guard"], disabled: [] },
        dangerousCommandGuard: {
          enabled: true,
          blockedPatterns: ["rm -rf"],
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-dangerous" },
        { args: { command: "rm -rf node_modules" } },
      ),
      /Blocked dangerous bash command/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("dangerous-command-guard includes actionable remediation for blocked git clean", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-dangerous-command-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["dangerous-command-guard"], disabled: [] },
        dangerousCommandGuard: {
          enabled: true,
          blockedPatterns: ["git\\s+clean\\s+-fdx"],
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-clean-dangerous" },
        { args: { command: "git clean -fdx" } },
      ),
      /git clean -ndx/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("dangerous-command-guard includes actionable remediation for blocked force push", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-dangerous-command-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["dangerous-command-guard"], disabled: [] },
        dangerousCommandGuard: {
          enabled: true,
          blockedPatterns: ["git\\s+push\\s+--force"],
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-force-push-dangerous" },
        { args: { command: "git push --force origin main" } },
      ),
      /use a normal `git push`/i,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("dangerous-command-guard allows safe bash commands", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-dangerous-command-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["dangerous-command-guard"], disabled: [] },
        dangerousCommandGuard: {
          enabled: true,
          blockedPatterns: ["rm -rf"],
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-safe" },
      { args: { command: "ls -la" } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
