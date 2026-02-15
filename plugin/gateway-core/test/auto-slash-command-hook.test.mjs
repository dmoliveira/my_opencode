import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("auto-slash-command rewrites natural prompt to slash command", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-auto-slash-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["auto-slash-command"],
          disabled: [],
        },
        autoSlashCommand: {
          enabled: true,
        },
      },
    })

    const output = {
      parts: [{ type: "text", text: "please run doctor diagnostics" }],
    }
    await plugin["chat.message"](
      {
        sessionID: "session-auto-slash-1",
        prompt: "please run doctor diagnostics",
      },
      output,
    )

    assert.equal(output.parts[0].text, "/doctor")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("auto-slash-command leaves explicit slash prompts unchanged", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-auto-slash-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["auto-slash-command"],
          disabled: [],
        },
        autoSlashCommand: {
          enabled: true,
        },
      },
    })

    const output = {
      parts: [{ type: "text", text: "/doctor" }],
    }
    await plugin["chat.message"](
      {
        sessionID: "session-auto-slash-2",
        prompt: "/doctor",
      },
      output,
    )

    assert.equal(output.parts[0].text, "/doctor")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
