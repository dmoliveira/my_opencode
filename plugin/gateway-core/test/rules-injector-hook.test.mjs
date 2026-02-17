import assert from "node:assert/strict"
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

function setupPlugin(directory) {
  return GatewayCorePlugin({
    directory,
    config: {
      hooks: {
        enabled: true,
        order: ["rules-injector"],
        disabled: ["global-process-pressure"],
      },
      rulesInjector: {
        enabled: true,
      },
    },
  })
}

test("rules-injector applies matching instructions for file-aware tools", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-rules-injector-"))
  try {
    mkdirSync(join(directory, ".github", "instructions"), { recursive: true })
    writeFileSync(
      join(directory, ".github", "instructions", "typescript.instructions.md"),
      [
        "---",
        "applyTo: src/**/*.ts",
        "---",
        "Prefer descriptive TypeScript names.",
      ].join("\n"),
      "utf-8",
    )

    const plugin = setupPlugin(directory)
    await plugin["tool.execute.before"]({ tool: "read", sessionID: "session-rules-1" }, { args: {} })
    const output = {
      output: "read output",
      metadata: { filePath: "src/main.ts" },
    }
    await plugin["tool.execute.after"]({ tool: "read", sessionID: "session-rules-1" }, output)

    assert.match(String(output.output), /\[Rule: .*typescript.instructions.md\]/)
    assert.match(String(output.output), /Prefer descriptive TypeScript names\./)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("rules-injector applies copilot instructions as always-apply rules", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-rules-injector-"))
  try {
    mkdirSync(join(directory, ".github"), { recursive: true })
    writeFileSync(
      join(directory, ".github", "copilot-instructions.md"),
      "Always summarize risky edits before finishing.",
      "utf-8",
    )

    const plugin = setupPlugin(directory)
    await plugin["tool.execute.before"]({ tool: "write", sessionID: "session-rules-2" }, { args: {} })
    const output = {
      output: "write output",
      metadata: { filePath: "docs/readme.md" },
    }
    await plugin["tool.execute.after"]({ tool: "write", sessionID: "session-rules-2" }, output)

    assert.match(String(output.output), /copilot-instructions\.md/)
    assert.match(String(output.output), /Always summarize risky edits before finishing\./)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("rules-injector can infer file path from output title", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-rules-injector-"))
  try {
    mkdirSync(join(directory, ".github", "instructions"), { recursive: true })
    writeFileSync(
      join(directory, ".github", "instructions", "python.instructions.md"),
      [
        "---",
        "applyTo: src/**/*.py",
        "---",
        "Keep Python helpers side-effect free.",
      ].join("\n"),
      "utf-8",
    )

    const plugin = setupPlugin(directory)
    await plugin["tool.execute.before"]({ tool: "read", sessionID: "session-rules-3" }, { args: {} })
    const output = {
      output: "read output",
      title: "Read src/worker.py",
    }
    await plugin["tool.execute.after"]({ tool: "read", sessionID: "session-rules-3" }, output)

    assert.match(String(output.output), /Keep Python helpers side-effect free\./)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("rules-injector dedupes within a session and resets on compaction", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-rules-injector-"))
  try {
    mkdirSync(join(directory, ".github", "instructions"), { recursive: true })
    writeFileSync(
      join(directory, ".github", "instructions", "dedupe.instructions.md"),
      [
        "---",
        "applyTo: src/**/*.ts",
        "---",
        "Inject this only once per session unless compacted.",
      ].join("\n"),
      "utf-8",
    )

    const plugin = setupPlugin(directory)
    const output1 = { output: "first", metadata: { filePath: "src/app.ts" } }
    await plugin["tool.execute.before"]({ tool: "read", sessionID: "session-rules-4" }, { args: {} })
    await plugin["tool.execute.after"]({ tool: "read", sessionID: "session-rules-4" }, output1)
    assert.match(String(output1.output), /Inject this only once per session unless compacted\./)

    const output2 = { output: "second", metadata: { filePath: "src/app.ts" } }
    await plugin["tool.execute.before"]({ tool: "read", sessionID: "session-rules-4" }, { args: {} })
    await plugin["tool.execute.after"]({ tool: "read", sessionID: "session-rules-4" }, output2)
    assert.doesNotMatch(String(output2.output), /Inject this only once per session unless compacted\./)

    await plugin.event({ event: { type: "session.compacted", properties: { info: { id: "session-rules-4" } } } })
    const output3 = { output: "third", metadata: { filePath: "src/app.ts" } }
    await plugin["tool.execute.before"]({ tool: "read", sessionID: "session-rules-4" }, { args: {} })
    await plugin["tool.execute.after"]({ tool: "read", sessionID: "session-rules-4" }, output3)
    assert.match(String(output3.output), /Inject this only once per session unless compacted\./)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("rules-injector ignores non-file tools", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-rules-injector-"))
  try {
    mkdirSync(join(directory, ".github", "instructions"), { recursive: true })
    writeFileSync(
      join(directory, ".github", "instructions", "bash.instructions.md"),
      [
        "---",
        "applyTo: src/**/*.sh",
        "---",
        "Do not inject for bash tool in file-aware mode.",
      ].join("\n"),
      "utf-8",
    )

    const plugin = setupPlugin(directory)
    await plugin["tool.execute.before"]({ tool: "bash", sessionID: "session-rules-5" }, { args: {} })
    const output = {
      output: "bash output",
      metadata: { filePath: "src/script.sh" },
    }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-rules-5" }, output)

    assert.doesNotMatch(String(output.output), /Do not inject for bash tool in file-aware mode\./)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("rules-injector supports applyTo inline array and yaml list forms", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-rules-injector-"))
  try {
    mkdirSync(join(directory, ".github", "instructions"), { recursive: true })
    writeFileSync(
      join(directory, ".github", "instructions", "array.instructions.md"),
      [
        "---",
        "applyTo: [\"src/**/*.ts\", \"src/**/*.tsx\"]",
        "---",
        "Array-based applyTo matched.",
      ].join("\n"),
      "utf-8",
    )
    writeFileSync(
      join(directory, ".github", "instructions", "list.instructions.md"),
      [
        "---",
        "applyTo:",
        "  - src/**/*.ts",
        "---",
        "List-based applyTo matched.",
      ].join("\n"),
      "utf-8",
    )

    const plugin = setupPlugin(directory)
    await plugin["tool.execute.before"]({ tool: "read", sessionID: "session-rules-6" }, { args: {} })
    const output = {
      output: "read output",
      metadata: { filePath: "src/feature.ts" },
    }
    await plugin["tool.execute.after"]({ tool: "read", sessionID: "session-rules-6" }, output)

    assert.match(String(output.output), /Array-based applyTo matched\./)
    assert.match(String(output.output), /List-based applyTo matched\./)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("rules-injector clears pending tool state after non-string output", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-rules-injector-"))
  try {
    mkdirSync(join(directory, ".github", "instructions"), { recursive: true })
    writeFileSync(
      join(directory, ".github", "instructions", "stale.instructions.md"),
      [
        "---",
        "applyTo: src/**/*.ts",
        "---",
        "No stale state carry-over.",
      ].join("\n"),
      "utf-8",
    )

    const plugin = setupPlugin(directory)

    await plugin["tool.execute.before"]({ tool: "read", sessionID: "session-rules-7" }, { args: {} })
    await plugin["tool.execute.after"]({ tool: "read", sessionID: "session-rules-7" }, { output: { value: 1 } })

    await plugin["tool.execute.before"]({ tool: "bash", sessionID: "session-rules-7" }, { args: {} })
    const output = {
      output: "bash output",
      metadata: { filePath: "src/feature.ts" },
    }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-rules-7" }, output)

    assert.doesNotMatch(String(output.output), /No stale state carry-over\./)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("rules-injector handles brace globs in inline applyTo arrays", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-rules-injector-"))
  try {
    mkdirSync(join(directory, ".github", "instructions"), { recursive: true })
    writeFileSync(
      join(directory, ".github", "instructions", "brace.instructions.md"),
      [
        "---",
        "applyTo: [\"src/**/*.{ts,tsx}\"]",
        "---",
        "Brace glob matched.",
      ].join("\n"),
      "utf-8",
    )

    const plugin = setupPlugin(directory)
    await plugin["tool.execute.before"]({ tool: "read", sessionID: "session-rules-8" }, { args: {} })
    const output = {
      output: "read output",
      metadata: { filePath: "src/components/view.tsx" },
    }
    await plugin["tool.execute.after"]({ tool: "read", sessionID: "session-rules-8" }, output)

    assert.match(String(output.output), /Brace glob matched\./)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
