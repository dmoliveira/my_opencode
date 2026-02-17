import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

const TAG_OPEN = "<auto-slash-command>"
const TAG_CLOSE = "</auto-slash-command>"

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

    assert.match(String(output.parts[0].text), new RegExp(`${TAG_OPEN}[\\s\\S]*/doctor[\\s\\S]*${TAG_CLOSE}`))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("auto-slash-command wraps explicit slash prompts with tag markers", async () => {
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

    assert.match(String(output.parts[0].text), new RegExp(`${TAG_OPEN}[\\s\\S]*/doctor[\\s\\S]*${TAG_CLOSE}`))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("auto-slash-command handles command.execute.before payloads", async () => {
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
      parts: [],
    }

    await plugin["command.execute.before"](
      {
        sessionID: "session-auto-slash-3",
        command: "doctor",
        arguments: "--json",
      },
      output,
    )

    assert.ok(Array.isArray(output.parts))
    assert.equal(output.parts.length > 0, true)
    assert.match(
      String(output.parts[0]?.text),
      new RegExp(`${TAG_OPEN}[\\s\\S]*/doctor --json[\\s\\S]*${TAG_CLOSE}`),
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("auto-slash-command ignores excluded commands on command.execute.before", async () => {
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
      parts: [{ type: "text", text: "unchanged" }],
    }

    await plugin["command.execute.before"](
      {
        sessionID: "session-auto-slash-4",
        command: "ulw-loop",
        arguments: "run",
      },
      output,
    )

    assert.equal(output.parts[0].text, "unchanged")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("auto-slash-command does not rewrite high-risk install prompts", async () => {
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
      parts: [{ type: "text", text: "please install devtools for me" }],
    }
    await plugin["chat.message"](
      {
        sessionID: "session-auto-slash-5",
        prompt: "please install devtools for me",
      },
      output,
    )

    assert.equal(output.parts[0].text, "please install devtools for me")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("auto-slash-command does not fallback-map excluded explicit slash", async () => {
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
      parts: [{ type: "text", text: "/ulw-loop doctor diagnostics" }],
    }
    await plugin["chat.message"](
      {
        sessionID: "session-auto-slash-6",
        prompt: "/ulw-loop doctor diagnostics",
      },
      output,
    )

    assert.equal(output.parts[0].text, "/ulw-loop doctor diagnostics")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("auto-slash-command ignores embedded excluded explicit slash token", async () => {
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
      parts: [{ type: "text", text: "please run /ulw-loop doctor diagnostics" }],
    }
    await plugin["chat.message"](
      {
        sessionID: "session-auto-slash-7",
        prompt: "please run /ulw-loop doctor diagnostics",
      },
      output,
    )

    assert.equal(output.parts[0].text, "please run /ulw-loop doctor diagnostics")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
