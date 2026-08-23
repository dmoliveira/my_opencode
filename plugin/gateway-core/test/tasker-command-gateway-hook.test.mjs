import assert from "node:assert/strict"
import test from "node:test"
import { createTaskerCommandGatewayHook } from "../dist/hooks/tasker-command-gateway/index.js"

const create = (agent) =>
  createTaskerCommandGatewayHook({
    directory: process.cwd(),
    resolveAgent: async () => agent,
    resolveSandbox: async () => ({
      scope: "sandbox",
      worktree: "/tmp/worktree",
      branch: "sandbox/tasker",
    }),
    knownRecordTargets: new Map([
      ["task_119", { scope: "sandbox", worktree: "/tmp/worktree", branch: "sandbox/tasker" }],
      ["task_120", { scope: "sandbox", worktree: "/tmp/worktree", branch: "sandbox/tasker" }],
    ]),
  })

const invoke = (command, tool = "bash", agent = "tasker", inputAgent) =>
  create(agent).event("tool.execute.before", {
    input: {
      tool,
      sessionID: "ses-tasker",
      ...(inputAgent ? { agent: inputAgent } : {}),
    },
    output: { args: { command } },
    directory: process.cwd(),
  })

const scopedAdd = 'oc add task "planned work" --scope sandbox --worktree /tmp/worktree --branch sandbox/tasker --kind chore --format json'

test("allows discovery and bounded OC reads", async () => {
  await invoke("", "read")
  await invoke("command -v oc")
  await invoke("oc find tasker --type task --scope sandbox && oc get task_119 --view full")
  await invoke("oc config --doctor")
  await invoke("oc --format json config --doctor")
})

test("allows one bounded OC write", async () => {
  await invoke(scopedAdd)
  await invoke("oc set task_119 status doing")
  await invoke("oc link task_119 depends-on task_120")
})

test("requires bounded write targets and rejects unknown options", async () => {
  for (const command of [
    "oc add memory note --kind note",
    "oc add task note --scope other --worktree /tmp/worktree --branch sandbox/tasker",
    "oc add task note --scope sandbox --worktree /tmp/other --branch sandbox/tasker",
    "oc add task note --scope sandbox --worktree /tmp/worktree --branch other",
    "oc add memory note --scope sandbox --worktree /tmp/worktree --branch sandbox/tasker --config /tmp/other",
    "oc set task_119 status doing --override {\"scope\":\"other\"}",
    "oc set task_999 status doing",
    "oc link task_119 arbitrary-edge task_120",
    "oc link task_119 captured task_120",
    "oc link task_119 depends-on task_999",
  ]) {
    await assert.rejects(invoke(command), /Blocked planning-agent request/)
  }
})

test("blocks arbitrary tools and shell syntax", async () => {
  for (const [command, tool] of [
    ["echo unsafe", "bash"],
    ["oc current; echo unsafe", "bash"],
    ["oc current | cat", "bash"],
    ["oc current &echo unsafe", "bash"],
    ["oc current&echo unsafe", "bash"],
    ["oc current && oc add memory note", "bash"],
    ["oc current $(id)", "bash"],
    ["oc current `id`", "bash"],
    ["/tmp/oc current", "bash"],
    ["", "task"],
    ["", "write"],
    ["oc delete task_119", "bash"],
  ]) {
    await assert.rejects(invoke(command, tool), /Blocked planning-agent request/)
  }
})

test("fails closed when identity is unknown", async () => {
  await assert.rejects(invoke("oc current", "bash", null), /tasker_identity_unknown/)
})

test("prefers authoritative input identity over a stale resolver", async () => {
  await assert.rejects(invoke("oc current; echo unsafe", "bash", "reviewer", "tasker"), /Blocked planning-agent request/)
  await invoke("echo unsafe", "bash", "tasker", "reviewer")
})
