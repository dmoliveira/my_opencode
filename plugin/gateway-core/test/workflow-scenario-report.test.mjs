import assert from "node:assert/strict"
import test from "node:test"

import {
  renderWorkflowScenarioMarkdown,
  summarizeWorkflowScenarioResults,
} from "../dist/audit/workflow-scenario-report.js"

test("workflow scenario report summarizes workflow action accuracy", () => {
  const summary = summarizeWorkflowScenarioResults([
    { id: "a", workflow: "todo-continuation-enforcer", requestType: "pending_marker", description: "", expectedAction: "inject_prompt", actualAction: "inject_prompt", correct: true },
    { id: "b", workflow: "mistake-ledger", requestType: "semantic_deferral", description: "", expectedAction: "write_ledger_entry", actualAction: "write_ledger_entry", correct: true },
    { id: "c", workflow: "task-resume-info", requestType: "llm_continue_only", description: "", expectedAction: "continuation_hint", actualAction: "continuation_hint", correct: true },
    { id: "d", workflow: "done-proof-enforcer", requestType: "missing_proof", description: "", expectedAction: "pending_validation", actualAction: "pending_validation", correct: true },
  ])
  assert.equal(summary.total, 4)
  assert.equal(summary.correct, 4)
  assert.equal(summary.accuracyPct, 100)
})

test("workflow scenario report renders markdown", () => {
  const results = [
    { id: "a", workflow: "todo-continuation-enforcer", requestType: "pending_marker", description: "", expectedAction: "inject_prompt", actualAction: "inject_prompt", correct: true },
    { id: "b", workflow: "mistake-ledger", requestType: "semantic_deferral", description: "", expectedAction: "write_ledger_entry", actualAction: "write_ledger_entry", correct: true },
  ]
  const markdown = renderWorkflowScenarioMarkdown(summarizeWorkflowScenarioResults(results), results)
  assert.match(markdown, /# Workflow Scenario Reliability Report/)
  assert.match(markdown, /todo-continuation-enforcer: 1\/1 \(100%\)/)
  assert.match(markdown, /mistake-ledger/)
  assert.match(markdown, /pending_marker/)
})
