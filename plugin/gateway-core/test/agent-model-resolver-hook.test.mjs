import assert from "node:assert/strict"
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { dirname, join } from "node:path"
import test from "node:test"
import { fileURLToPath } from "node:url"

import GatewayCorePlugin from "../dist/index.js"

const REPO_DIRECTORY = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..")

function createPlugin(directory) {
  return GatewayCorePlugin({
    directory,
    config: {
      hooks: {
        enabled: true,
        order: ["agent-model-resolver"],
        disabled: ["agent-denied-tool-enforcer"],
      },
    },
  })
}

test("agent-model-resolver prepends timestamped headers for delegated task descriptions", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-agent-model-resolver-"))
  try {
    const specsDir = join(directory, "agent", "specs")
    mkdirSync(specsDir, { recursive: true })
    writeFileSync(
      join(specsDir, "explore.json"),
      JSON.stringify({ name: "explore", metadata: { default_category: "quick" } }),
      "utf-8",
    )

    const plugin = createPlugin(directory)
    const output = {
      args: {
        subagent_type: "explore",
        description: "Scout repository patterns",
        prompt: "Inspect code paths",
      },
    }
    await plugin["tool.execute.before"]({ tool: "task", sessionID: "session-effort" }, output)

    assert.equal(String(output.args.category ?? ""), "quick")
    assert.match(
      String(output.args.description ?? ""),
      /^\[SUBAGENT\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\].*explore.*\[scan\].*effort=low/m,
    )
    assert.match(
      String(output.args.description ?? ""),
      /\[MODEL ROUTING\s+\d{2}:\d{2}:\d{2}\].*reasoning=low/i,
    )
    assert.match(String(output.args.description ?? ""), /\[TOOL SURFACE\s+\d{2}:\d{2}:\d{2}\].*allowed=/)
    assert.match(String(output.args.prompt ?? ""), /\[MODEL ROUTING\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\]/)
    assert.doesNotMatch(String(output.args.description ?? ""), /^\[THINKING EFFORT\]/m)

    await plugin["tool.execute.before"]({ tool: "task", sessionID: "session-effort-rerun" }, output)
    const updatedDescription = String(output.args.description ?? "")
    assert.equal((updatedDescription.match(/^\[SUBAGENT\s+/gm) ?? []).length, 1)
    assert.equal((updatedDescription.match(/^\[MODEL ROUTING\s+/gm) ?? []).length, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("agent-model-resolver infers explore delegation and category", async () => {
  const plugin = createPlugin(REPO_DIRECTORY)
  const output = {
    args: {
      prompt: "Find implementation location for auth token refresh flow.",
      description: "Map codebase patterns quickly.",
    },
  }
  await plugin["tool.execute.before"]({ tool: "task", sessionID: "session-infer" }, output)

  assert.equal(output.args.subagent_type, "explore")
  assert.equal(output.args.category, "quick")
  assert.match(output.args.prompt, /\[DELEGATION ROUTER\s+\d{2}:\d{2}:\d{2}\]/)
  assert.match(output.args.prompt, /\[MODEL ROUTING\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\]/)
  assert.match(output.args.prompt, /\[TOOL SURFACE\s+\d{2}:\d{2}:\d{2}\]/)
})

test("agent-model-resolver sets default category for explicit subagent", async () => {
  const plugin = createPlugin(REPO_DIRECTORY)
  const output = {
    args: {
      subagent_type: "librarian",
      prompt: "Gather official docs for the framework behavior.",
      description: "Need external upstream references.",
    },
  }
  await plugin["tool.execute.before"]({ tool: "task", sessionID: "session-librarian" }, output)

  assert.equal(output.args.category, "balanced")
  assert.match(output.args.prompt, /model=openai\/gpt-5.3-codex/)
})

test("agent-model-resolver preserves explicit category and injects tool surface", async () => {
  const plugin = createPlugin(REPO_DIRECTORY)
  const output = {
    args: {
      subagent_type: "oracle",
      category: "critical",
      prompt: "Review architecture tradeoffs and security risk.",
    },
  }
  await plugin["tool.execute.before"]({ tool: "task", sessionID: "session-oracle" }, output)

  assert.equal(output.args.category, "critical")
  assert.match(output.args.prompt, /reasoning=xhigh/)
  assert.match(output.args.prompt, /allowed=/)
  assert.match(output.args.prompt, /denied=/)
})
