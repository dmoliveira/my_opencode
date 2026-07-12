import assert from "node:assert/strict"
import { mkdtempSync, rmSync, mkdirSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("directory-agents-injector injects a sanitized AGENTS.md label into system context", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-directory-injectors-"))
  const nested = join(directory, "a", "b")
  mkdirSync(nested, { recursive: true })
  writeFileSync(join(directory, "AGENTS.md"), "# Agents\nUse br ready before coding.\n", "utf-8")
  try {
    const plugin = GatewayCorePlugin({ directory: nested, config: { hooks: { enabled: true, order: ["directory-agents-injector"], disabled: [] }, directoryAgentsInjector: { enabled: true, maxChars: 4000 } } })
    const output = { system: ["base system"] }
    await plugin["experimental.chat.system.transform"]({ sessionID: "session-dir-1" }, output)
    assert.equal(output.system[0], "base system")
    assert.match(String(output.system[1]), /Local instructions loaded from: AGENTS.md/)
    assert.doesNotMatch(String(output.system[1]), new RegExp(directory.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))
  } finally { rmSync(directory, { recursive: true, force: true }) }
})

test("directory-readme-injector does not duplicate README context in tool output", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-directory-injectors-"))
  writeFileSync(join(directory, "README.md"), "# Readme\nProject usage notes.\n", "utf-8")
  try {
    const plugin = GatewayCorePlugin({ directory, config: { hooks: { enabled: true, order: ["directory-readme-injector"], disabled: [] }, directoryReadmeInjector: { enabled: true, maxChars: 4000 } } })
    const toolOutput = { output: "result" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-dir-2" }, toolOutput)
    assert.equal(toolOutput.output, "result")
    const output = { system: ["base system"] }
    await plugin["experimental.chat.system.transform"]({ sessionID: "session-dir-2" }, output)
    assert.match(String(output.system[1]), /Local README context loaded from: README.md/)
  } finally { rmSync(directory, { recursive: true, force: true }) }
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

    const output = { system: [] }
    await plugin["experimental.chat.system.transform"]({ sessionID: "session-dir-3" }, output)
    assert.ok(output.system[0].includes("README.md excerpt:"))
    assert.ok(output.system[0].includes("[Content truncated due to context window limit]"))
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

    const output = { system: [] }
    await plugin["experimental.chat.system.transform"]({ sessionID: "session-dir-4" }, output)
    assert.ok(output.system[0].includes("AGENTS.md guidance excerpt:"))
    assert.ok(output.system[0].includes("[Content truncated due to context window limit]"))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("directory injectors add AGENTS and README guidance on system transform", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-directory-injectors-"))
  const nested = join(directory, "pkg", "src")
  mkdirSync(nested, { recursive: true })
  writeFileSync(join(directory, "AGENTS.md"), "# Agents\nFollow the local task policy.\n", "utf-8")
  writeFileSync(join(directory, "README.md"), "# Readme\nSurface package context before coding.\n", "utf-8")
  try {
    const plugin = GatewayCorePlugin({
      directory: nested,
      config: {
        hooks: {
          enabled: true,
          order: ["directory-agents-injector", "directory-readme-injector"],
          disabled: [],
        },
        directoryAgentsInjector: { enabled: true, maxChars: 4000 },
        directoryReadmeInjector: { enabled: true, maxChars: 4000 },
      },
    })

    const output = { system: [] }
    await plugin["experimental.chat.system.transform"]({ sessionID: "session-dir-system-1" }, output)

    assert.equal(output.system.length, 2)
    assert.match(String(output.system[0]), /Local instructions loaded from:/)
    assert.match(String(output.system[0]), /Follow the local task policy\./)
    assert.match(String(output.system[1]), /Local README context loaded from:/)
    assert.match(String(output.system[1]), /Surface package context before coding\./)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("stable directory context stays before runtime session context", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-directory-injectors-"))
  try {
    writeFileSync(join(directory, "AGENTS.md"), "Use stable instructions.", "utf-8")
    writeFileSync(join(directory, "README.md"), "Use stable project context.", "utf-8")
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["session-runtime-system-context", "directory-agents-injector", "directory-readme-injector"], disabled: [] },
        conciseMode: { enabled: false, defaultMode: "off" },
        directoryAgentsInjector: { enabled: true, maxChars: 4000 },
        directoryReadmeInjector: { enabled: true, maxChars: 4000 },
        sessionRuntimeSystemContext: { enabled: true, injectSessionIdContext: true, injectSessionIdWhenConciseModeOnly: false },
      },
    })
    const output = { system: ["base system"] }
    await plugin["experimental.chat.system.transform"]({ sessionID: "session-cache-order" }, output)
    assert.equal(output.system[0], "base system")
    assert.match(String(output.system[1]), /Local instructions loaded from: AGENTS.md/)
    assert.match(String(output.system[2]), /Local README context loaded from: README.md/)
    assert.match(String(output.system[3]), /runtime_session_context: session-cache-order/)
  } finally { rmSync(directory, { recursive: true, force: true }) }
})
