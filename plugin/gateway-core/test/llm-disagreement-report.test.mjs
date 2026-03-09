import assert from "node:assert/strict"
import test from "node:test"

import {
  parseGatewayAuditJsonl,
  summarizeLlmDecisionDisagreements,
} from "../dist/audit/llm-disagreement-report.js"

test("llm disagreement report parses jsonl and groups by hook and meaning pair", () => {
  const events = parseGatewayAuditJsonl(`
{"hook":"auto-slash-command","reason_code":"llm_decision_disagreement","deterministic_decision_meaning":"no_slash","llm_decision_meaning":"route_doctor"}
{"hook":"auto-slash-command","reason_code":"llm_decision_disagreement","deterministic_decision_meaning":"no_slash","llm_decision_meaning":"route_doctor"}
{"hook":"agent-model-resolver","reason_code":"llm_decision_disagreement","deterministic_decision_meaning":"route_explore","llm_decision_meaning":"route_librarian"}
{"hook":"agent-model-resolver","reason_code":"other_reason","deterministic_decision_meaning":"route_explore","llm_decision_meaning":"route_librarian"}
`)
  const summary = summarizeLlmDecisionDisagreements(events)
  assert.equal(summary.total, 3)
  assert.deepEqual(summary.byHook, [
    { hook: "auto-slash-command", count: 2 },
    { hook: "agent-model-resolver", count: 1 },
  ])
  assert.deepEqual(summary.pairs, [
    {
      hook: "auto-slash-command",
      deterministicMeaning: "no_slash",
      aiMeaning: "route_doctor",
      count: 2,
    },
    {
      hook: "agent-model-resolver",
      deterministicMeaning: "route_explore",
      aiMeaning: "route_librarian",
      count: 1,
    },
  ])
})
