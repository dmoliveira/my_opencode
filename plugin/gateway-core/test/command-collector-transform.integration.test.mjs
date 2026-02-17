import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("integration: tool command registers collector context then transform injects synthetic part", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-integration-flow-"))
  try {
    const plugin = GatewayCorePlugin({ directory })
    const sessionID = "session-integration-tool"

    await plugin["tool.execute.before"](
      { tool: "command", sessionID },
      {
        args: {
          command:
            'python3 "$HOME/.config/opencode/my_opencode/scripts/autopilot_command.py" go --goal "ship integration" --json',
        },
      }
    )

    const output = {
      messages: [{ info: { role: "user", id: "m1", sessionID }, parts: [{ type: "text", text: "Continue task" }] }],
    }
    await plugin["experimental.chat.messages.transform"]({ sessionID }, output)

    const parts = output.messages[0]?.parts ?? []
    assert.equal(parts[0]?.synthetic, true)
    assert.match(String(parts[0]?.text), /Autopilot objective activated\./)
    assert.equal(parts[1]?.text, "Continue task")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("integration: command.execute.before path registers collector context then transform injects", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-integration-flow-"))
  try {
    const plugin = GatewayCorePlugin({ directory })
    const sessionID = "session-integration-command"

    await plugin["command.execute.before"](
      {
        command: "autopilot-go",
        arguments: '--goal "ship command flow"',
        sessionID,
      },
      {}
    )

    const output = {
      messages: [{ info: { role: "user", id: "m1", sessionID }, parts: [{ type: "text", text: "Continue command flow" }] }],
    }
    await plugin["experimental.chat.messages.transform"]({ sessionID }, output)

    const parts = output.messages[0]?.parts ?? []
    assert.equal(parts[0]?.synthetic, true)
    assert.match(String(parts[0]?.text), /ship command flow/)
    assert.equal(parts[1]?.text, "Continue command flow")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("integration: non-start command does not register collector context for transform", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-integration-flow-"))
  try {
    const plugin = GatewayCorePlugin({ directory })
    const sessionID = "session-integration-negative"

    await plugin["tool.execute.before"](
      { tool: "slashcommand", sessionID },
      { args: { command: "/autopilot status --json" } }
    )

    const output = {
      messages: [{ info: { role: "user", id: "m1", sessionID }, parts: [{ type: "text", text: "Status check" }] }],
    }
    await plugin["experimental.chat.messages.transform"]({ sessionID }, output)

    const parts = output.messages[0]?.parts ?? []
    assert.equal(parts[0]?.synthetic, undefined)
    assert.equal(parts[0]?.text, "Status check")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("integration: transform consumes collector context only once", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-integration-flow-"))
  try {
    const plugin = GatewayCorePlugin({ directory })
    const sessionID = "session-integration-consume"

    await plugin["command.execute.before"](
      {
        command: "autopilot-go",
        arguments: '--goal "consume once"',
        sessionID,
      },
      {}
    )

    const first = {
      messages: [{ info: { role: "user", id: "m1", sessionID }, parts: [{ type: "text", text: "First" }] }],
    }
    await plugin["experimental.chat.messages.transform"]({ sessionID }, first)
    assert.equal(first.messages[0]?.parts?.[0]?.synthetic, true)

    const second = {
      messages: [{ info: { role: "user", id: "m2", sessionID }, parts: [{ type: "text", text: "Second" }] }],
    }
    await plugin["experimental.chat.messages.transform"]({ sessionID }, second)

    assert.equal(second.messages[0]?.parts?.[0]?.synthetic, undefined)
    assert.equal(second.messages[0]?.parts?.[0]?.text, "Second")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
