import assert from "node:assert/strict"
import test from "node:test"
import { mkdtempSync, rmSync, realpathSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import GatewayCorePlugin from "../dist/index.js"
import { packet } from "./tasker-protocol-fixture.mjs"
let nextCall = 0

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
    { tool: "bash", sessionID, callID: `integration-${++nextCall}`, ...(agent ? { agent } : {}) },
    { args: { command } },
  )
}

test("keeps the command boundary when hooks are disabled or reordered", async () => {
  const directory = realpathSync(mkdtempSync(join(tmpdir(), "gateway-tasker-integration-")))
  try {
    const plugin = GatewayCorePlugin({ directory }, {
      hooks: { enabled: false, disabled: ["tasker-command-gateway"], order: ["think-mode"] },
    })
    await plugin["chat.params"](chatParams("tasker-disabled-hooks", "tasker"), chatOutput())
    await plugin["chat.message"]({ sessionID: "tasker-disabled-hooks", prompt: `Use scope 'sandbox', worktree '${directory}', branch 'sandbox/tasker'.` })
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
    await reordered["chat.message"]({ sessionID: "tasker-reordered-hooks", prompt: `Use scope 'sandbox', worktree '${directory}', branch 'sandbox/tasker'.` })
    await assert.rejects(
      before(reordered, "tasker-reordered-hooks", "oc current; echo unsafe"),
      /tasker_command_boundary_blocked/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("resolves identity from authoritative session messages and cleans deleted sessions", async () => {
  const directory = realpathSync(mkdtempSync(join(tmpdir(), "gateway-tasker-identity-")))
  try {
    let messageReads = 0
    const plugin = GatewayCorePlugin({
      directory,
      client: {
        session: {
          async get({ path }) { return { data: { id: path.id } } },
          async messages() {
            messageReads += 1
            return messageReads === 1 ? { data: [{ info: { role: "assistant", agent: "tasker" } }] } : { data: [] }
          },
        },
      },
    }, { hooks: { enabled: false } })
    await plugin["chat.message"]({ sessionID: "tasker-from-history", prompt: `Use scope 'sandbox', worktree '${directory}', branch 'sandbox/tasker'.` })
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
  const directory = realpathSync(mkdtempSync(join(tmpdir(), "gateway-non-tasker-")))
  try {
    const plugin = GatewayCorePlugin({ directory }, { hooks: { enabled: false } })
    await plugin["chat.params"](chatParams("reviewer-session", "reviewer"), chatOutput())
    await before(plugin, "reviewer-session", "echo unsafe")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("binds typed creation to the immutable prompt and native command directory", async () => {
  const directory = realpathSync(mkdtempSync(join(tmpdir(), "gateway-tasker-sandbox-")))
  const sessionID = "tasker-sandbox"
  try {
    const plugin = GatewayCorePlugin({ directory }, { hooks: { enabled: false } })
    await plugin["chat.params"](chatParams(sessionID, "tasker"), chatOutput())
    await plugin["chat.message"]({ sessionID, prompt: `Use scope 'sandbox', worktree '${directory}', and branch 'sandbox/tasker'.` })
    await plugin["chat.message"]({ sessionID, prompt: "Use scope 'other', worktree '/tmp/other', and branch 'other'." })
    const execute = async (command, result) => {
      const input = { tool: "bash", sessionID, callID: `integration-${++nextCall}` }
      const output = { args: { command } }
      await plugin["tool.execute.before"](input, output)
      assert.equal(output.args.workdir, directory)
      await plugin["tool.execute.after"]({ ...input, args: output.args }, { output: JSON.stringify(result), metadata: { exit: 0 } })
    }
    const add = `oc add task planned --scope sandbox --worktree ${directory} --branch sandbox/tasker --format json`
    await assert.rejects(before(plugin, sessionID, add), /lookup_required/)
    await execute("oc find planned --type task --scope sandbox --limit 100 --format json", { type: "find_result", entity_type: "task", query: "planned", scope_key: "sandbox", count: 0, items: [] })
    await execute(add, { id: "task_119", type: "task", title: "planned", scope_key: "sandbox" })
    for (const command of ["oc set task_119 status doing --format json", `oc add task foreign --scope other --worktree ${directory} --branch sandbox/tasker --format json`, "oc find foreign --type task --scope other --format json", "oc set task_999 goal unrelated --reason requested --expected-revision 1 --format json"])
      await assert.rejects(before(plugin, sessionID, command), /tasker_command_boundary_blocked/)
  } finally { rmSync(directory, { recursive: true, force: true }) }
})

test("structured research survives optional hooks without routing or prose mutation", async () => {
  const directory = realpathSync(mkdtempSync(join(tmpdir(), "gateway-tasker-research-")))
  try {
    const plugin = GatewayCorePlugin({ directory }, { hooks: { enabled: true, order: ["agent-model-resolver", "agent-context-shaper", "agent-discoverability-injector", "hook-semantic-bridge", "adaptive-delegation-policy", "agent-denied-tool-enforcer"] } })
    await plugin["chat.params"](chatParams("research-parent", "tasker"), chatOutput())
    await plugin["chat.message"]({ sessionID: "research-parent", prompt: `Use scope 'sandbox', worktree '${directory}', and branch 'sandbox/tasker'.` })
    const input = { tool: "task", sessionID: "research-parent", callID: "research-call" }
    const output = { args: { subagent_type: "explore", description: "Inspect planning documentation", prompt: packet() } }
    await plugin["tool.execute.before"](input, output)
    assert.equal(output.args.subagent_type, "explore")
    assert.ok(output.args.prompt.includes(packet()))
    assert.ok(output.args.prompt.endsWith("do not execute implementation or validation."))
    assert.ok(!output.args.prompt.includes("[agent-context-shaper]"))
    await plugin["tool.execute.after"]({ ...input, args: output.args }, { output: "Evidence: docs:1", metadata: {} })
  } finally { rmSync(directory, { recursive: true, force: true }) }
})
