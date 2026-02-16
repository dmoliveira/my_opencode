import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("secret-commit-guard blocks git commit flow when staged diff includes secret", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-secret-commit-"))
  try {
    execSync("git init -b feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "config.txt"), "token=sk-abcdefghijklmnopqrstuvwxyz123456\n", "utf-8")
    execSync("git add config.txt", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["secret-commit-guard"],
          disabled: [],
        },
        secretCommitGuard: {
          enabled: true,
          patterns: ["sk-[A-Za-z0-9]{20,}"],
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-secret-commit" },
        { args: { command: 'git commit -m "add file"' } },
      ),
      /Staged diff appears to contain secrets/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("secret-commit-guard allows commit flow when staged diff has no secret", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-secret-commit-"))
  try {
    execSync("git init -b feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "config.txt"), "safe-value=hello\n", "utf-8")
    execSync("git add config.txt", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["secret-commit-guard"],
          disabled: [],
        },
        secretCommitGuard: {
          enabled: true,
          patterns: ["sk-[A-Za-z0-9]{20,}"],
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-secret-commit" },
      { args: { command: 'git commit -m "safe"' } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
