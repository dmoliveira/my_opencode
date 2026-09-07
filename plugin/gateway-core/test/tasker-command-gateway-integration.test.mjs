import assert from "node:assert/strict"
import test from "node:test"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import GatewayCorePlugin from "../dist/index.js"

function chatParams(sessionID, agent) {
  return {
    sessionID,
    agent,
    model: { providerID: "openai", modelID: "gpt-5.6-sol" },
    provider: { id: "openai" },
    message: {},
  }
}

function chatOutput() {
  return { temperature: 0.2, topP: 1, topK: 0, maxOutputTokens: undefined, options: {} }
}

async function before(plugin, sessionID, command, agent) {
  return plugin["tool.execute.before"](
    { tool: "bash", sessionID, ...(agent ? { agent } : {}) },
    { args: { command } },
  )
}

test("keeps the command boundary when hooks are disabled or reordered", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-tasker-integration-"))
  try {
    const plugin = GatewayCorePlugin({ directory }, {
      hooks: { enabled: false, disabled: ["tasker-command-gateway"], order: ["think-mode"] },
    })
    await plugin["chat.params"](chatParams("tasker-disabled-hooks", "tasker"), chatOutput())
    await assert.rejects(
      before(plugin, "tasker-disabled-hooks", "oc current; echo unsafe"),
      /tasker_command_boundary_blocked/,
    )
    const reordered = GatewayCorePlugin(
      { directory },
      {
        hooks: {
          enabled: true,
          disabled: ["tasker-command-gateway"],
          order: ["think-mode"],
        },
      },
    )
    await reordered["chat.params"](
      chatParams("tasker-reordered-hooks", "tasker"),
      chatOutput(),
    )
    await assert.rejects(
      before(reordered, "tasker-reordered-hooks", "oc current; echo unsafe"),
      /tasker_command_boundary_blocked/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("resolves identity from authoritative session messages and cleans deleted sessions", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-tasker-identity-"))
  try {
    let messageReads = 0
    const plugin = GatewayCorePlugin({
      directory,
      client: {
        session: {
          async messages() {
            messageReads += 1
            return messageReads === 1 ? { data: [{ info: { role: "assistant", agent: "tasker" } }] } : { data: [] }
          },
        },
      },
    }, { hooks: { enabled: false } })
    await before(plugin, "tasker-from-history", "oc current")
    await plugin.event({ event: { type: "session.deleted", properties: { id: "tasker-from-history" } } })
    await assert.rejects(
      before(plugin, "tasker-from-history", "oc current", "tasker"),
      /tasker_identity_unknown/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("leaves a proven non-tasker session unchanged", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-non-tasker-"))
  try {
    const plugin = GatewayCorePlugin({ directory }, { hooks: { enabled: false } })
    await plugin["chat.params"](chatParams("reviewer-session", "reviewer"), chatOutput())
    await before(plugin, "reviewer-session", "echo unsafe")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("binds writes to the sandbox declared by the planning prompt", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-tasker-sandbox-"))
  try {
    const plugin = GatewayCorePlugin({ directory }, { hooks: { enabled: false } })
    await plugin["chat.params"](chatParams("tasker-sandbox", "tasker"), chatOutput())
    await plugin["chat.message"]({
      sessionID: "tasker-sandbox",
      prompt: "Use scope 'sandbox', worktree '/tmp/worktree', and branch 'sandbox/tasker'.",
    })
    await plugin["chat.message"]({
      sessionID: "tasker-sandbox",
      prompt: "Use scope 'other', worktree '/tmp/other', and branch 'other'.",
    })
    await before(
      plugin,
      "tasker-sandbox",
      'oc add task "planned" --scope sandbox --worktree /tmp/worktree --branch sandbox/tasker',
    )
    await assert.rejects(
      before(
        plugin,
        "tasker-sandbox",
        'oc add task "foreign" --scope other --worktree /tmp/worktree --branch sandbox/tasker',
      ),
      /tasker_command_boundary_blocked/,
    )
    await before(plugin, "tasker-sandbox", "oc find planned --type task --scope sandbox")
    await plugin["tool.execute.after"](
      {
        tool: "bash",
        sessionID: "tasker-sandbox",
        agent: "tasker",
        args: { command: "oc find planned --type task --scope sandbox" },
      },
      {
        output: '{"items":[{"id":"task_119","scope_key":"sandbox","title":"mentions task_999"}]}',
      },
    )
    await before(plugin, "tasker-sandbox", "oc set task_119 status doing")
    await assert.rejects(
      before(plugin, "tasker-sandbox", "oc set task_999 status doing"),
      /tasker_command_boundary_blocked/,
    )
    await assert.rejects(
      before(plugin, "tasker-sandbox", "oc find foreign --type task --scope other"),
      /tasker_command_boundary_blocked/,
    )
    await before(plugin, "tasker-sandbox", "oc find other --type task --scope sandbox")
    await plugin["tool.execute.after"](
      {
        tool: "bash",
        sessionID: "tasker-sandbox",
        agent: "tasker",
        args: { command: "oc find other --type task --scope sandbox" },
      },
      { output: '{"items":[{"id":"task_120","scope_key":"sandbox"}]}' },
    )
    await before(plugin, "tasker-sandbox", "oc set task_120 status doing")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
