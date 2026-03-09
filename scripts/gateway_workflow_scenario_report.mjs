#!/usr/bin/env node

import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join, resolve } from "node:path"

import { createTodoContinuationEnforcerHook } from "../plugin/gateway-core/dist/hooks/todo-continuation-enforcer/index.js"
import { createDoneProofEnforcerHook } from "../plugin/gateway-core/dist/hooks/done-proof-enforcer/index.js"
import GatewayCorePlugin from "../plugin/gateway-core/dist/index.js"
import {
  renderWorkflowScenarioMarkdown,
  summarizeWorkflowScenarioResults,
} from "../plugin/gateway-core/dist/audit/workflow-scenario-report.js"

const args = process.argv.slice(2)
const markdownIndex = args.indexOf("--markdown-out")
const markdownOut = markdownIndex >= 0 ? resolve(args[markdownIndex + 1] || "") : ""

const results = []

{
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-"))
  try {
    let promptCalls = 0
    const hook = createTodoContinuationEnforcerHook({
      directory,
      enabled: true,
      cooldownMs: 30000,
      maxConsecutiveFailures: 5,
      client: {
        session: {
          async messages() {
            return { data: [{ info: { role: "assistant" }, parts: [{ type: "text", text: "pending work\n<CONTINUE-LOOP>" }] }] }
          },
          async promptAsync() {
            promptCalls += 1
          },
        },
      },
    })
    await hook.event("session.idle", { directory, properties: { sessionID: "workflow-todo-1" } })
    results.push({ id: "todo-pending-marker", workflow: "todo-continuation-enforcer", requestType: "pending_marker", description: "idle with pending marker", expectedAction: "inject_prompt", actualAction: promptCalls === 1 ? "inject_prompt" : "no_inject", correct: promptCalls === 1 })
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
}

{
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-"))
  try {
    let promptCalls = 0
    const hook = createTodoContinuationEnforcerHook({
      directory,
      enabled: true,
      cooldownMs: 30000,
      maxConsecutiveFailures: 5,
      client: {
        session: {
          async messages() { throw new Error("messages should not be called") },
          async promptAsync() { promptCalls += 1 },
        },
      },
    })
    await hook.event("chat.message", { directory, properties: { sessionID: "workflow-todo-6", prompt: "yes, let's do it" } })
    await hook.event("tool.execute.after", { directory, input: { tool: "task", sessionID: "workflow-todo-6" }, output: { output: "Task 3/7 complete. Remaining tasks exist.\n<CONTINUE-LOOP>" } })
    await hook.event("session.idle", { directory, properties: { sessionID: "workflow-todo-6" } })
    await hook.event("session.idle", { directory, properties: { sessionID: "workflow-todo-6" } })
    results.push({ id: "todo-multi-idle-cooldown", workflow: "todo-continuation-enforcer", requestType: "cooldown", description: "multiple idle cycles after a single pending run", expectedAction: "inject_once", actualAction: promptCalls === 1 ? "inject_once" : `inject_${promptCalls}_times`, correct: promptCalls === 1 })
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
}

{
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-"))
  try {
    let promptCalls = 0
    const hook = createTodoContinuationEnforcerHook({
      directory,
      enabled: true,
      cooldownMs: 30000,
      maxConsecutiveFailures: 5,
      client: {
        session: {
          async messages() { throw new Error("messages should not be called") },
          async promptAsync() { promptCalls += 1 },
        },
      },
    })
    await hook.event("chat.message", { directory, properties: { sessionID: "workflow-todo-7", prompt: "yes, let's do it" } })
    await hook.event("tool.execute.after", { directory, input: { tool: "task", sessionID: "workflow-todo-7" }, output: { output: "Task 3/7 complete. Remaining tasks exist.\n<CONTINUE-LOOP>" } })
    await hook.event("chat.message", { directory, properties: { sessionID: "workflow-todo-7", prompt: "stop for now" } })
    await hook.event("session.idle", { directory, properties: { sessionID: "workflow-todo-7" } })
    await hook.event("chat.message", { directory, properties: { sessionID: "workflow-todo-7", prompt: "continue" } })
    await hook.event("tool.execute.after", { directory, input: { tool: "task", sessionID: "workflow-todo-7" }, output: { output: "Task 4/7 complete. Remaining tasks exist.\n<CONTINUE-LOOP>" } })
    await hook.event("session.idle", { directory, properties: { sessionID: "workflow-todo-7" } })
    results.push({ id: "todo-stop-resume-cycle", workflow: "todo-continuation-enforcer", requestType: "stop_resume", description: "stop clears continuation and later continue re-arms it", expectedAction: "inject_once_after_resume", actualAction: promptCalls === 1 ? "inject_once_after_resume" : `inject_${promptCalls}_times`, correct: promptCalls === 1 })
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
}

{
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-"))
  try {
    let promptCalls = 0
    const hook = createTodoContinuationEnforcerHook({
      directory,
      enabled: true,
      cooldownMs: 30000,
      maxConsecutiveFailures: 5,
      client: {
        session: {
          async messages() {
            return { data: [{ info: { role: "assistant" }, parts: [{ type: "text", text: "Epic 4 in progress. Completed 3/7 tasks. Next items: 4. add tests 5. rerun build. Remaining tasks exist." }] }] }
          },
          async promptAsync() { promptCalls += 1 },
        },
      },
    })
    await hook.event("session.idle", { directory, properties: { sessionID: "workflow-todo-4" } })
    results.push({ id: "todo-epic-progress-pending", workflow: "todo-continuation-enforcer", requestType: "progress_summary", description: "epic progress with remaining items", expectedAction: "inject_prompt", actualAction: promptCalls === 1 ? "inject_prompt" : "no_inject", correct: promptCalls === 1 })
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
}

{
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-"))
  try {
    let promptCalls = 0
    const hook = createTodoContinuationEnforcerHook({
      directory,
      enabled: true,
      cooldownMs: 30000,
      maxConsecutiveFailures: 5,
      client: {
        session: {
          async messages() {
            return { data: [{ info: { role: "assistant" }, parts: [{ type: "text", text: "Epic 4 complete. All 7 tasks are done. Summary: tests passed and build succeeded." }] }] }
          },
          async promptAsync() { promptCalls += 1 },
        },
      },
    })
    await hook.event("session.idle", { directory, properties: { sessionID: "workflow-todo-5" } })
    results.push({ id: "todo-epic-progress-complete", workflow: "todo-continuation-enforcer", requestType: "progress_summary", description: "epic progress summary without pending items", expectedAction: "no_inject", actualAction: promptCalls === 0 ? "no_inject" : "inject_prompt", correct: promptCalls === 0 })
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
}

{
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-"))
  try {
    let promptCalls = 0
    const hook = createTodoContinuationEnforcerHook({
      directory,
      enabled: true,
      cooldownMs: 30000,
      maxConsecutiveFailures: 5,
      client: { session: { async messages() { throw new Error("messages should not be called") }, async promptAsync() { promptCalls += 1 } } },
    })
    await hook.event("chat.message", { directory, properties: { sessionID: "workflow-todo-2", prompt: "yes, let's do it" } })
    await hook.event("tool.execute.after", { directory, input: { tool: "task", sessionID: "workflow-todo-2" }, output: { output: "Task is finished. Natural next steps:\n1. Run focused tests\nIf you want, I can do this next." } })
    await hook.event("session.idle", { directory, properties: { sessionID: "workflow-todo-2" } })
    results.push({ id: "todo-soft-cue-armed", workflow: "todo-continuation-enforcer", requestType: "soft_cue", description: "soft next steps with continue intent armed", expectedAction: "inject_prompt", actualAction: promptCalls === 1 ? "inject_prompt" : "no_inject", correct: promptCalls === 1 })
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
}

{
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-"))
  try {
    let promptCalls = 0
    const hook = createTodoContinuationEnforcerHook({
      directory,
      enabled: true,
      cooldownMs: 30000,
      maxConsecutiveFailures: 5,
      client: { session: { async messages() { throw new Error("messages should not be called") }, async promptAsync() { promptCalls += 1 } } },
    })
    await hook.event("tool.execute.after", { directory, input: { tool: "task", sessionID: "workflow-todo-3" }, output: { output: "Task is finished. Natural next steps:\n1. Run focused tests\nIf you want, I can do this next." } })
    await hook.event("session.idle", { directory, properties: { sessionID: "workflow-todo-3" } })
    results.push({ id: "todo-soft-cue-unarmed", workflow: "todo-continuation-enforcer", requestType: "soft_cue", description: "soft next steps without continue intent", expectedAction: "no_inject", actualAction: promptCalls === 0 ? "no_inject" : "inject_prompt", correct: promptCalls === 0 })
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
}

{
  const hook = createDoneProofEnforcerHook({ enabled: true, requiredMarkers: ["validation", "test", "lint"], requireLedgerEvidence: true, allowTextFallback: false })
  const output = { output: "all complete\n<promise>DONE</promise>" }
  await hook.event("tool.execute.after", { input: { tool: "bash", sessionID: "workflow-done-1" }, output })
  results.push({ id: "done-proof-missing-proof", workflow: "done-proof-enforcer", requestType: "missing_proof", description: "done promise without validation evidence", expectedAction: "pending_validation", actualAction: output.output.includes("PENDING_VALIDATION") ? "pending_validation" : "keep_done", correct: output.output.includes("PENDING_VALIDATION") })
}

{
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["validation-evidence-ledger", "done-proof-enforcer"], disabled: [] },
        validationEvidenceLedger: { enabled: true },
        doneProofEnforcer: { enabled: true, requiredMarkers: ["lint", "test", "build"], requireLedgerEvidence: true, allowTextFallback: false },
      },
    })
    await plugin["tool.execute.before"]({ tool: "bash", sessionID: "workflow-done-2" }, { args: { command: "npm run lint" } })
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "workflow-done-2" }, { output: "Lint passed" })
    await plugin["tool.execute.before"]({ tool: "bash", sessionID: "workflow-done-2" }, { args: { command: "npm test" } })
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "workflow-done-2" }, { output: "All tests passed" })
    await plugin["tool.execute.before"]({ tool: "bash", sessionID: "workflow-done-2" }, { args: { command: "npm run build" } })
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "workflow-done-2" }, { output: "Build passed" })
    await plugin["tool.execute.before"]({ tool: "bash", sessionID: "workflow-done-2" }, { args: { command: "git status" } })
    const output = { output: "Ready to finish\n<promise>DONE</promise>" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "workflow-done-2" }, output)
    results.push({ id: "done-proof-complete", workflow: "done-proof-enforcer", requestType: "complete_proof", description: "done promise after required validation evidence", expectedAction: "keep_done", actualAction: output.output.includes("PENDING_VALIDATION") ? "pending_validation" : "keep_done", correct: !output.output.includes("PENDING_VALIDATION") })
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
}

const summary = summarizeWorkflowScenarioResults(results)
console.log(JSON.stringify({ summary, results }, null, 2))
if (markdownOut) {
  writeFileSync(markdownOut, renderWorkflowScenarioMarkdown(summary, results), "utf-8")
}
