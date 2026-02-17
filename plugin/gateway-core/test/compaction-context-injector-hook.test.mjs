import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("compaction-context-injector prepends context for summarize command", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-compaction-context-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["compaction-context-injector"],
          disabled: ["auto-slash-command"],
        },
        compactionContextInjector: {
          enabled: true,
        },
      },
    })

    const output = { parts: [{ type: "text", text: "summarize current session" }] }
    await plugin["command.execute.before"](
      {
        command: "summarize",
        arguments: "",
        sessionID: "session-compaction-context-1",
      },
      output,
    )

    assert.equal(output.parts.length > 1, true)
    assert.match(String(output.parts[0]?.text), /\[COMPACTION CONTEXT\]/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("compaction-context-injector skips non-compaction commands", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-compaction-context-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["compaction-context-injector"],
          disabled: ["auto-slash-command"],
        },
        compactionContextInjector: {
          enabled: true,
        },
      },
    })

    const output = { parts: [{ type: "text", text: "hello" }] }
    await plugin["command.execute.before"](
      {
        command: "doctor",
        arguments: "--json",
        sessionID: "session-compaction-context-2",
      },
      output,
    )

    assert.equal(output.parts[0]?.text, "hello")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("compaction-context-injector avoids duplicate marker injection", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-compaction-context-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["compaction-context-injector"],
          disabled: ["auto-slash-command"],
        },
        compactionContextInjector: {
          enabled: true,
        },
      },
    })

    const output = {
      parts: [{ type: "text", text: "[COMPACTION CONTEXT]\npre-existing" }],
    }
    await plugin["command.execute.before"](
      {
        command: "compact",
        arguments: "",
        sessionID: "session-compaction-context-3",
      },
      output,
    )

    assert.equal(output.parts.length, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("compaction-context-injector coexists with auto-slash in default hook flow", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-compaction-context-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        compactionContextInjector: {
          enabled: true,
        },
      },
    })

    const output = { parts: [] }
    await plugin["command.execute.before"](
      {
        command: "summarize",
        arguments: "",
        sessionID: "session-compaction-context-4",
      },
      output,
    )

    const combined = output.parts.map((part) => String(part.text ?? "")).join("\n\n")
    assert.match(combined, /\[COMPACTION CONTEXT\]/)
    assert.match(combined, /<auto-slash-command>[\s\S]*\/summarize[\s\S]*<\/auto-slash-command>/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("compaction context survives custom order before auto-slash", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-compaction-context-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["compaction-context-injector", "auto-slash-command"],
          disabled: [],
        },
        compactionContextInjector: {
          enabled: true,
        },
      },
    })

    const output = { parts: [] }
    await plugin["command.execute.before"](
      {
        command: "summarize",
        arguments: "",
        sessionID: "session-compaction-context-5",
      },
      output,
    )

    const combined = output.parts.map((part) => String(part.text ?? "")).join("\n\n")
    assert.match(combined, /\[COMPACTION CONTEXT\]/)
    assert.match(combined, /<auto-slash-command>[\s\S]*\/summarize[\s\S]*<\/auto-slash-command>/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
