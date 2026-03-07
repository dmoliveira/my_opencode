import assert from "node:assert/strict"
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

function createPlugin(directory) {
  return GatewayCorePlugin({
    directory,
    config: {
      hooks: {
        enabled: true,
        order: ["agent-denied-tool-enforcer"],
        disabled: [],
      },
    },
  })
}

function seedExploreSpec(directory) {
  const specsDir = join(directory, "agent", "specs")
  mkdirSync(specsDir, { recursive: true })
  writeFileSync(
    join(specsDir, "explore.json"),
    JSON.stringify({
      name: "explore",
      metadata: {
        default_category: "quick",
        allowed_tools: ["read", "glob", "grep"],
        denied_tools: ["bash", "write", "edit", "task", "webfetch", "todowrite", "todoread"],
      },
    }),
    "utf-8",
  )
}

test("agent-denied-tool-enforcer blocks mutating delegation intents for read-only subagents", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-denied-tool-enforcer-"))
  try {
    seedExploreSpec(directory)
    const plugin = createPlugin(directory)
    const output = {
      args: {
        subagent_type: "explore",
        description: "Please create a commit and open a PR with these updates.",
        prompt: "Then merge the PR and push to origin.",
      },
    }

    await assert.rejects(
      plugin["tool.execute.before"]({ tool: "task", sessionID: "session-mutation" }, output),
      /mutating work .*read-only/i,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("agent-denied-tool-enforcer allows read-only discovery prompts", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-denied-tool-enforcer-"))
  try {
    seedExploreSpec(directory)
    const plugin = createPlugin(directory)
    const output = {
      args: {
        subagent_type: "explore",
        description: "Find where notification settings are implemented.",
        prompt: "Read only, return file paths and line references.",
      },
    }

    await plugin["tool.execute.before"]({ tool: "task", sessionID: "session-readonly" }, output)
    assert.equal(output.args.subagent_type, "explore")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
