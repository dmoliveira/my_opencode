import assert from "node:assert/strict"
import test from "node:test"

import {
  renderWorkflowScenarioMarkdown,
  summarizeWorkflowScenarioResults,
} from "../dist/audit/workflow-scenario-report.js"

test("workflow scenario report summarizes workflow action accuracy", () => {
  const summary = summarizeWorkflowScenarioResults([
    { id: "a", workflow: "todo-continuation-enforcer", requestType: "pending_marker", description: "", expectedAction: "inject_prompt", actualAction: "inject_prompt", correct: true },
    { id: "b", workflow: "done-proof-enforcer", requestType: "missing_proof", description: "", expectedAction: "pending_validation", actualAction: "pending_validation", correct: true },
  ])
  assert.equal(summary.total, 2)
  assert.equal(summary.correct, 2)
  assert.equal(summary.accuracyPct, 100)
})

test("workflow scenario report renders markdown", () => {
  const results = [
    { id: "a", workflow: "todo-continuation-enforcer", requestType: "pending_marker", description: "", expectedAction: "inject_prompt", actualAction: "inject_prompt", correct: true },
  ]
  const markdown = renderWorkflowScenarioMarkdown(summarizeWorkflowScenarioResults(results), results)
  assert.match(markdown, /# Workflow Scenario Reliability Report/)
  assert.match(markdown, /todo-continuation-enforcer: 1\/1 \(100%\)/)
})
