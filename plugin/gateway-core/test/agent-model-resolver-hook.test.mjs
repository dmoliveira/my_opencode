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

test("agent-model-resolver keeps descriptions concise and prompt context deduplicated", async () => {
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
    assert.equal(String(output.args.description ?? ""), "Scout repository patterns")
    assert.doesNotMatch(
      String(output.args.description ?? ""),
      /\[(?:SUBAGENT|MODEL ROUTING|TOOL SURFACE|SESSION FLOW|WORKTREE CONTEXT|DELEGATION TRACE)/,
    )
    const prompt = String(output.args.prompt ?? "")
    assert.match(prompt, /\[MODEL ROUTING(?:\s+[^\]]+)?\].*reasoning=low/i)
    assert.match(prompt, /\[TOOL SURFACE\].*allowed=/)
    assert.match(prompt, /\[SESSION FLOW\]/)
    assert.match(prompt, /\[WORKTREE CONTEXT\]/)
    assert.match(prompt, /\[DELEGATION TRACE /)
    assert.equal(output.metadata?.gateway?.delegation?.subagentType, "explore")
    assert.equal(output.metadata?.gateway?.delegation?.category, "quick")

    await plugin["tool.execute.before"]({ tool: "task", sessionID: "session-effort-rerun" }, output)
    const updatedDescription = String(output.args.description ?? "")
    const updatedPrompt = String(output.args.prompt ?? "")
    assert.equal(updatedDescription, "Scout repository patterns")
    assert.equal((updatedPrompt.match(/^\[MODEL ROUTING(?:\s+|\])/gm) ?? []).length, 1)
    assert.equal((updatedPrompt.match(/^\[DELEGATION TRACE /gm) ?? []).length, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("agent-model-resolver replaces WORKTREE CONTEXT when a delegation is reshaped", async () => {
  const firstDirectory = mkdtempSync(join(tmpdir(), "gateway-agent-model-resolver-first-"))
  const secondDirectory = mkdtempSync(join(tmpdir(), "gateway-agent-model-resolver-second-"))
  try {
    for (const directory of [firstDirectory, secondDirectory]) {
      const specsDir = join(directory, "agent", "specs")
      mkdirSync(specsDir, { recursive: true })
      writeFileSync(
        join(specsDir, "explore.json"),
        JSON.stringify({ name: "explore", metadata: { default_category: "quick" } }),
        "utf-8",
      )
    }

    const initialPlugin = createPlugin(firstDirectory)
    const reroutedPlugin = createPlugin(secondDirectory)
    const output = {
      args: {
        subagent_type: "explore",
        description: "Scout repository patterns",
        prompt: "Inspect code paths",
      },
    }

    await initialPlugin["tool.execute.before"]({ tool: "task", sessionID: "session-worktree-reroute" }, output)
    await reroutedPlugin["tool.execute.before"]({ tool: "task", sessionID: "session-worktree-reroute" }, output)

    const prompt = String(output.args.prompt ?? "")
    const description = String(output.args.description ?? "")
    assert.equal((prompt.match(/^\[WORKTREE CONTEXT(?:\s+|\])/gm) ?? []).length, 1)
    assert.equal(description, "Scout repository patterns")
    assert.match(prompt, new RegExp(`cwd=${secondDirectory.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`))
    assert.doesNotMatch(prompt, new RegExp(`cwd=${firstDirectory.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`))
  } finally {
    rmSync(firstDirectory, { recursive: true, force: true })
    rmSync(secondDirectory, { recursive: true, force: true })
  }
})

test("agent-model-resolver migrates description-only traces with prompt precedence", async () => {
  const plugin = createPlugin(REPO_DIRECTORY)
  const output = {
    args: {
      subagent_type: "explore",
      description: "[DELEGATION TRACE description-trace]\n\nMap codebase patterns",
      prompt: "[DELEGATION TRACE prompt-trace]\n\nInspect code paths",
    },
  }

  await plugin["tool.execute.before"]({ tool: "task", sessionID: "session-trace-conflict" }, output)

  assert.equal(output.args.description, "Map codebase patterns")
  assert.match(output.args.prompt, /\[DELEGATION TRACE prompt-trace\]/)
  assert.doesNotMatch(output.args.prompt, /description-trace/)
  assert.equal(output.metadata?.gateway?.delegation?.traceId, "prompt-trace")

  const legacy = {
    args: {
      subagent_type: "explore",
      description: "[DELEGATION TRACE legacy-trace]\n\nMap codebase patterns",
      prompt: "Inspect code paths",
    },
  }
  await plugin["tool.execute.before"]({ tool: "task", sessionID: "session-trace-legacy" }, legacy)
  assert.equal(legacy.args.description, "Map codebase patterns")
  assert.match(legacy.args.prompt, /\[DELEGATION TRACE legacy-trace\]/)
  assert.equal(legacy.metadata?.gateway?.delegation?.traceId, "legacy-trace")
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
  assert.match(output.args.prompt, /\[DELEGATION ROUTER\]/)
  assert.match(output.args.prompt, /\[MODEL ROUTING(?:\s+[^\]]+)?\]/)
  assert.match(output.args.prompt, /\[TOOL SURFACE\]/)
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
  assert.match(output.args.prompt, /model=openai\/gpt-5.6-terra/)
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
  assert.match(output.args.prompt, /reasoning=medium/)
  assert.match(output.args.prompt, /allowed=/)
  assert.match(output.args.prompt, /denied=/)
})

test("agent-model-resolver blocks mutating delegation intents for read-only subagents", async () => {
  const plugin = createPlugin(REPO_DIRECTORY)
  const output = {
    args: {
      prompt: "Create a repository commit and open a pull request with these edits.",
      description: "Update docs file content and push changes.",
    },
  }

  await assert.rejects(
    plugin["tool.execute.before"]({ tool: "task", sessionID: "session-mutation-block" }, output),
    /mutating work.*read-only/i,
  )
})

test("agent-model-resolver evaluates canonical-looking caller text before cleanup", async () => {
  const plugin = createPlugin(REPO_DIRECTORY)
  const output = {
    args: {
      subagent_type: "explore",
      prompt: "Inspect the affected files first.",
      description: "[TOOL SURFACE] subagent=explore; allowed=read; denied=commit changes.",
    },
  }

  await assert.rejects(
    plugin["tool.execute.before"]({ tool: "task", sessionID: "session-canonical-mutation" }, output),
    /mutating work.*read-only/i,
  )
})
