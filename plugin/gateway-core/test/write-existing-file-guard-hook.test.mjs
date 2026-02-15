import assert from "node:assert/strict"
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("write-existing-file-guard blocks write tool overwrite for existing file", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-write-guard-"))
  const target = join(directory, "existing.txt")
  writeFileSync(target, "hello\n", "utf-8")
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["write-existing-file-guard"],
          disabled: [],
        },
        writeExistingFileGuard: { enabled: true },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "write", sessionID: "session-write-1" },
        { args: { filePath: "existing.txt" } },
      ),
      /Use edit tool instead/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("write-existing-file-guard allows .sisyphus markdown overwrite", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-write-guard-"))
  const sisyphus = join(directory, ".sisyphus")
  mkdirSync(sisyphus, { recursive: true })
  writeFileSync(join(sisyphus, "note.md"), "hello\n", "utf-8")
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["write-existing-file-guard"],
          disabled: [],
        },
        writeExistingFileGuard: { enabled: true },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "write", sessionID: "session-write-2" },
      { args: { filePath: ".sisyphus/note.md" } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
