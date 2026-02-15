import assert from "node:assert/strict"
import { mkdtempSync, rmSync, mkdirSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("directory-agents-injector appends nearest AGENTS.md context hint", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-directory-injectors-"))
  const nested = join(directory, "a", "b")
  mkdirSync(nested, { recursive: true })
  writeFileSync(join(directory, "AGENTS.md"), "# Agents\n", "utf-8")
  try {
    const plugin = GatewayCorePlugin({
      directory: nested,
      config: {
        hooks: {
          enabled: true,
          order: ["directory-agents-injector"],
          disabled: [],
        },
        directoryAgentsInjector: { enabled: true },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-dir-1" },
      { args: { command: "ls" } },
    )
    const output = { output: "result" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-dir-1" }, output)
    assert.ok(output.output.includes("Local instructions loaded from:"))
    assert.ok(output.output.includes("AGENTS.md"))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("directory-readme-injector appends nearest README.md context hint", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-directory-injectors-"))
  const nested = join(directory, "src", "module")
  mkdirSync(nested, { recursive: true })
  writeFileSync(join(directory, "README.md"), "# Readme\n", "utf-8")
  try {
    const plugin = GatewayCorePlugin({
      directory: nested,
      config: {
        hooks: {
          enabled: true,
          order: ["directory-readme-injector"],
          disabled: [],
        },
        directoryReadmeInjector: { enabled: true },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-dir-2" },
      { args: { command: "ls" } },
    )
    const output = { output: "result" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-dir-2" }, output)
    assert.ok(output.output.includes("Local README context loaded from:"))
    assert.ok(output.output.includes("README.md"))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
