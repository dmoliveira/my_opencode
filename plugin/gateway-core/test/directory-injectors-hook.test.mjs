import assert from "node:assert/strict"
import { mkdtempSync, rmSync, mkdirSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("directory-agents-injector appends nearest AGENTS.md guidance excerpt", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-directory-injectors-"))
  const nested = join(directory, "a", "b")
  mkdirSync(nested, { recursive: true })
  writeFileSync(join(directory, "AGENTS.md"), "# Agents\nUse br ready before coding.\n", "utf-8")
  try {
    const plugin = GatewayCorePlugin({
      directory: nested,
      config: {
        hooks: {
          enabled: true,
          order: ["directory-agents-injector"],
          disabled: [],
        },
        directoryAgentsInjector: { enabled: true, maxChars: 4000 },
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
    assert.ok(output.output.includes("AGENTS.md guidance excerpt:"))
    assert.ok(output.output.includes("Use br ready before coding."))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("directory-readme-injector appends nearest README.md guidance excerpt", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-directory-injectors-"))
  const nested = join(directory, "src", "module")
  mkdirSync(nested, { recursive: true })
  writeFileSync(join(directory, "README.md"), "# Readme\nProject usage notes.\n", "utf-8")
  try {
    const plugin = GatewayCorePlugin({
      directory: nested,
      config: {
        hooks: {
          enabled: true,
          order: ["directory-readme-injector"],
          disabled: [],
        },
        directoryReadmeInjector: { enabled: true, maxChars: 4000 },
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
    assert.ok(output.output.includes("README.md excerpt:"))
    assert.ok(output.output.includes("Project usage notes."))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("directory-readme-injector truncates injected README guidance safely", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-directory-injectors-"))
  const nested = join(directory, "docs", "nested")
  mkdirSync(nested, { recursive: true })
  writeFileSync(join(directory, "README.md"), `# Readme\n${"A".repeat(300)}\n`, "utf-8")
  try {
    const plugin = GatewayCorePlugin({
      directory: nested,
      config: {
        hooks: {
          enabled: true,
          order: ["directory-readme-injector"],
          disabled: [],
        },
        directoryReadmeInjector: { enabled: true, maxChars: 80 },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-dir-3" },
      { args: { command: "ls" } },
    )
    const output = { output: "result" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-dir-3" }, output)
    assert.ok(output.output.includes("README.md excerpt:"))
    assert.ok(output.output.includes("[Content truncated due to context window limit]"))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("directory-agents-injector truncates injected AGENTS guidance safely", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-directory-injectors-"))
  const nested = join(directory, "team", "workflow")
  mkdirSync(nested, { recursive: true })
  writeFileSync(join(directory, "AGENTS.md"), `# Agents\n${"B".repeat(300)}\n`, "utf-8")
  try {
    const plugin = GatewayCorePlugin({
      directory: nested,
      config: {
        hooks: {
          enabled: true,
          order: ["directory-agents-injector"],
          disabled: [],
        },
        directoryAgentsInjector: { enabled: true, maxChars: 80 },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-dir-4" },
      { args: { command: "ls" } },
    )
    const output = { output: "result" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-dir-4" }, output)
    assert.ok(output.output.includes("AGENTS.md guidance excerpt:"))
    assert.ok(output.output.includes("[Content truncated due to context window limit]"))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
