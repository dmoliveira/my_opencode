import { mkdtempSync, realpathSync, rmSync, mkdirSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { createTaskerCommandGatewayHook } from "../dist/hooks/tasker-command-gateway/index.js"
import { TASKER_RESEARCH_CONSTRAINTS } from "../dist/hooks/tasker-command-gateway/research-policy.js"
const worktree = realpathSync(mkdtempSync(join(tmpdir(), "tasker-policy-fixture-")))
mkdirSync(join(worktree, "docs"))
writeFileSync(join(worktree, "docs/codememory-workflow.md"), "Scoped fixture documentation")
process.on("exit", () => rmSync(worktree, { recursive: true, force: true }))
export const sandbox = { scope: "sandbox", worktree, branch: "sandbox/tasker" }
export const task = (id = "task_1", title = "existing") => ({ id, type: "task", scope_key: "sandbox", title, status: "not-started" })
export const find = (query, items = [], entity_type = "task", scope_key = "sandbox") => ({ type: "find_result", entity_type, query, scope_key, count: items.length, items })
export const links = (items = []) => ({ type: "list_result", entity_type: "link", scope_key: "sandbox", count: items.length, items })
export const history = (id, revision = 1) => ({ type: "history", scope_key: "sandbox", query: id, count: 1, operations: [{ target_id: id, target_type: id.split("_")[0], scope_key: "sandbox", outcome: "applied", resulting_revision: revision }] })
export const packet = () => JSON.stringify({ objective: "Inspect the planning documentation.", paths: ["docs/codememory-workflow.md"], acceptance: "Identify the scope rules.", checks: "Read-only inspection.", evidence: "File and line references.", constraints: [...TASKER_RESEARCH_CONSTRAINTS] })
export const add = (title = "planned") => `oc add task "${title}" --scope sandbox --worktree ${sandbox.worktree} --branch sandbox/tasker --kind chore --format json`
export function fixture(options = {}) {
  let count = 0
  const knownRecordTargets = new Map(["task_1", "task_2", "memory_1"].map((id) => [id, sandbox]))
  const hook = createTaskerCommandGatewayHook({ knownRecordTargets, directory: process.cwd(), resolveAgent: async () => "tasker", resolveSandbox: async () => sandbox, ...options })
  void hook.event("chat.message", { properties: { sessionID: "parent", messageID: "fixture-user", prompt: "Scoped planning request" } })
  const admission = (command, tool = "bash", agent = "tasker", sessionID = "parent") => ({ input: { tool, agent, sessionID, callID: `call-${++count}` }, output: { args: typeof command === "string" ? { command } : command }, directory: process.cwd() })
  async function execute(command, result = {}, opts = {}) {
    const event = admission(command, opts.tool ?? "bash", opts.agent ?? "tasker", opts.session ?? "parent")
    try {
      await hook.event("tool.execute.before", event)
      if (opts.rewrite) opts.rewrite(event.output.args)
      await hook.event("tool.execute.before.final", event)
    } catch (error) { await hook.event("tool.execute.before.error", event); throw error }
    await hook.event("tool.execute.after", { input: { ...event.input, args: event.output.args }, output: { output: opts.tool === "task" ? result : JSON.stringify(result), metadata: { exit: opts.exit ?? 0 } }, directory: event.directory })
    return event
  }
  return { hook, admission, execute }
}
