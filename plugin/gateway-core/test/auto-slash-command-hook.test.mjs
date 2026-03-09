import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { createAutoSlashCommandHook } from "../dist/hooks/auto-slash-command/index.js"

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

test("auto-slash-command uses assist-mode LLM for ambiguous doctor intent", async () => {
  const hook = createAutoSlashCommandHook({
    directory: process.cwd(),
    enabled: true,
    decisionRuntime: {
      config: {
        enabled: true,
        mode: "assist",
        command: "opencode",
        model: "openai/gpt-5.1-codex-mini",
        timeoutMs: 1000,
        maxPromptChars: 200,
        maxContextChars: 200,
        enableCache: true,
        cacheTtlMs: 10000,
        maxCacheEntries: 8,
      },
      decide: async () => ({
        mode: "assist",
        accepted: true,
        char: "D",
        raw: "D",
        durationMs: 1,
        model: "openai/gpt-5.1-codex-mini",
        templateId: "auto-slash-v1",
        meaning: "route_doctor",
      }),
    },
  })

  const output = {
    parts: [{ type: "text", text: "can you inspect the environment health and tell me what's wrong" }],
  }
  await hook.event("chat.message", {
    properties: {
      sessionID: "session-auto-slash-7",
      prompt: "can you inspect the environment health and tell me what's wrong",
    },
    output,
    directory: process.cwd(),
  })

  assert.equal(String(output.parts[0].text).includes("/doctor"), true)
})

test("auto-slash-command skips LLM rewrite for high-risk install prompt", async () => {
  const hook = createAutoSlashCommandHook({
    directory: process.cwd(),
    enabled: true,
    decisionRuntime: {
      config: {
        enabled: true,
        mode: "assist",
        command: "opencode",
        model: "openai/gpt-5.1-codex-mini",
        timeoutMs: 1000,
        maxPromptChars: 200,
        maxContextChars: 200,
        enableCache: true,
        cacheTtlMs: 10000,
        maxCacheEntries: 8,
      },
      decide: async () => {
        throw new Error("should not be called")
      },
    },
  })

  const output = {
    parts: [{ type: "text", text: "please install and configure devtools for me" }],
  }
  await hook.event("chat.message", {
    properties: {
      sessionID: "session-auto-slash-8",
      prompt: "please install and configure devtools for me",
    },
    output,
    directory: process.cwd(),
  })

  assert.equal(output.parts[0].text, "please install and configure devtools for me")
})

test("auto-slash-command shadow mode records but does not rewrite ambiguous prompt", async () => {
  const hook = createAutoSlashCommandHook({
    directory: process.cwd(),
    enabled: true,
    decisionRuntime: {
      config: {
        enabled: true,
        mode: "shadow",
        command: "opencode",
        model: "openai/gpt-5.1-codex-mini",
        timeoutMs: 1000,
        maxPromptChars: 200,
        maxContextChars: 200,
        enableCache: true,
        cacheTtlMs: 10000,
        maxCacheEntries: 8,
      },
      decide: async () => ({
        mode: "shadow",
        accepted: true,
        char: "D",
        raw: "D",
        durationMs: 1,
        model: "openai/gpt-5.1-codex-mini",
        templateId: "auto-slash-v1",
        meaning: "route_doctor",
      }),
    },
  })
  const output = {
    parts: [{ type: "text", text: "can you inspect the environment health and tell me what's wrong" }],
  }
  await hook.event("chat.message", {
    properties: {
      sessionID: "session-auto-slash-shadow-1",
      prompt: "can you inspect the environment health and tell me what's wrong",
    },
    output,
    directory: process.cwd(),
  })
  assert.equal(output.parts[0].text, "can you inspect the environment health and tell me what's wrong")
})
