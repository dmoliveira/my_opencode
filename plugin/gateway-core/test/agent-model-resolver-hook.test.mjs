import assert from "node:assert/strict"
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
        disabled: [],
      },
    },
  })
}

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
  assert.match(output.args.prompt, /\[MODEL ROUTING\]/)
  assert.match(output.args.prompt, /\[TOOL SURFACE\]/)
  assert.match(output.args.prompt, /\/agent-catalog explain explore/)
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
