import assert from "node:assert/strict"
import test from "node:test"

import {
  renderLlmScenarioMarkdown,
  summarizeLlmScenarioResults,
} from "../dist/audit/llm-scenario-report.js"

test("llm scenario report summarizes accuracy by hook and request type", () => {
  const summary = summarizeLlmScenarioResults([
    { id: "a", hookId: "auto-slash-command", requestType: "contamination", description: "", expectedChar: "D", actualChar: "D", accepted: true, correct: true, durationMs: 100 },
    { id: "b", hookId: "auto-slash-command", requestType: "contamination", description: "", expectedChar: "D", actualChar: "", accepted: false, correct: false, durationMs: 200 },
    { id: "c", hookId: "provider-error-classifier", requestType: "provider_error", description: "", expectedChar: "O", actualChar: "O", accepted: true, correct: true, durationMs: 300 },
  ])
  assert.equal(summary.total, 3)
  assert.equal(summary.correct, 2)
  assert.equal(summary.accuracyPct, 66.7)
  assert.deepEqual(summary.byHook, [
    { hookId: "auto-slash-command", total: 2, correct: 1, accuracyPct: 50 },
    { hookId: "provider-error-classifier", total: 1, correct: 1, accuracyPct: 100 },
  ])
})

test("llm scenario report renders markdown with scenario details", () => {
  const results = [
    { id: "a", hookId: "auto-slash-command", requestType: "contamination", description: "", expectedChar: "D", actualChar: "D", accepted: true, correct: true, durationMs: 100 },
  ]
  const markdown = renderLlmScenarioMarkdown(summarizeLlmScenarioResults(results), results)
  assert.match(markdown, /# LLM Scenario Reliability Report/)
  assert.match(markdown, /auto-slash-command: 1\/1 \(100%\)/)
  assert.match(markdown, /a: PASS \| auto-slash-command \| contamination/)
})
