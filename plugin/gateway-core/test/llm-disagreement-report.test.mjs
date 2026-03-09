import assert from "node:assert/strict"
import test from "node:test"

import {
  buildLlmRolloutReport,
  parseGatewayAuditJsonl,
  recommendLlmRolloutActions,
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

test("llm disagreement report recommends rollout actions by disagreement volume", () => {
  const summary = {
    total: 16,
    byHook: [
      { hook: "agent-model-resolver", count: 12 },
      { hook: "auto-slash-command", count: 5 },
      { hook: "provider-error-classifier", count: 2 },
    ],
    pairs: [],
  }
  assert.deepEqual(recommendLlmRolloutActions(summary), [
    {
      hook: "agent-model-resolver",
      action: "investigate",
      reason: "high disagreement volume; keep in shadow and inspect top disagreement pairs",
      disagreementCount: 12,
    },
    {
      hook: "auto-slash-command",
      action: "tune",
      reason: "moderate disagreement volume; refine prompt, context shaping, or fallback policy",
      disagreementCount: 5,
    },
    {
      hook: "provider-error-classifier",
      action: "observe",
      reason: "low disagreement volume; continue shadow sampling before promotion",
      disagreementCount: 2,
    },
  ])
})

test("llm disagreement report builds rollout report from events", () => {
  const report = buildLlmRolloutReport(
    parseGatewayAuditJsonl(`
{"hook":"auto-slash-command","reason_code":"llm_decision_disagreement","deterministic_decision_meaning":"no_slash","llm_decision_meaning":"route_doctor"}
`),
  )
  assert.equal(report.summary.total, 1)
  assert.equal(report.recommendations[0]?.hook, "auto-slash-command")
  assert.equal(report.recommendations[0]?.action, "observe")
})
