import assert from "node:assert/strict"
import test from "node:test"
import { isAllowedTaskerCommand } from "../dist/hooks/tasker-command-gateway/command-policy.js"
import { fixture, sandbox } from "./tasker-protocol-fixture.mjs"

test("allows discovery and one bounded OC read", async () => {
  for (const command of ["command -v oc", "oc config --doctor", "oc --format json config --doctor", "oc find title --type task --scope sandbox --format json"]) await fixture().execute(command)
  await fixture().execute({}, {}, { tool: "read" })
})
test("rejects arbitrary tools, compound syntax, lifecycle and configuration overrides", async () => {
  for (const command of ["echo unsafe", "oc current; echo unsafe", "oc current && oc queue", "oc current | cat", "oc current &echo unsafe", "oc current&echo unsafe", "oc current $(id)", "oc current `id`", "oc --config /tmp/other current", "/tmp/oc current", "oc cancel task_1 --why removal --expected-revision 1 --format json", "oc set task_1 status doing --format json", "oc list task --scope other", "oc find title --type task --scope other"])
    await assert.rejects(fixture().execute(command), /tasker_command_boundary_blocked/)
  for (const tool of ["write", "edit", "task", "todowrite", "webfetch"]) await assert.rejects(fixture().execute({}, {}, { tool }), /Blocked planning-agent request/)
})
test("only a caller-bound native session prefix is transparent", () => {
  const context = { sandbox, sessionID: "ses_native" }
  assert.equal(isAllowedTaskerCommand("OPENCODE_SESSION_ID='ses_native' oc current", context), true)
  for (const value of ["OPENCODE_SESSION_ID=other oc current", "env OPENCODE_SESSION_ID=ses_native oc current", "OPENCODE_SESSION_ID=ses_native HOME=/other oc current"]) assert.equal(isAllowedTaskerCommand(value, context), false)
})
test("fails closed on absent identity and deleted session reuse", async () => {
  const { hook, execute } = fixture({ resolveAgent: async () => undefined })
  await assert.rejects(execute("oc current", {}, { agent: "" }), /tasker_identity_unknown/)
  await hook.event("session.deleted", { properties: { info: { id: "parent" } } })
  await assert.rejects(execute("oc current"), /tasker_identity_unknown/)
})
test("leaves a proven unrelated agent unchanged", async () => {
  await fixture().execute("echo safe", {}, { agent: "reviewer" })
})
