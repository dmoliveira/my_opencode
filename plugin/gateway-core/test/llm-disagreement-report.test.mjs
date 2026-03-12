import assert from "node:assert/strict"
import test from "node:test"

import {
  buildLlmRolloutReport,
  parseGatewayAuditJsonl,
  parseGatewayAuditJsonlWithDiagnostics,
  recommendLlmRolloutActions,
  renderLlmRolloutMarkdown,
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

test("llm disagreement report tracks invalid jsonl lines", () => {
  const parsed = parseGatewayAuditJsonlWithDiagnostics(`
{"hook":"auto-slash-command","reason_code":"llm_decision_disagreement","deterministic_decision_meaning":"no_slash","llm_decision_meaning":"route_doctor"}
not-json
`)
  assert.equal(parsed.invalidLines, 1)
  assert.equal(parsed.events.length, 1)
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
      thresholds: { investigateAt: 10, tuneAt: 4, observeAt: 1 },
    },
    {
      hook: "auto-slash-command",
      action: "tune",
      reason: "moderate disagreement volume; refine prompt, context shaping, or fallback policy",
      disagreementCount: 5,
      thresholds: { investigateAt: 10, tuneAt: 4, observeAt: 1 },
    },
    {
      hook: "provider-error-classifier",
      action: "observe",
      reason: "low disagreement volume; continue shadow sampling before promotion",
      disagreementCount: 2,
      thresholds: { investigateAt: 10, tuneAt: 4, observeAt: 1 },
    },
  ])
})

test("llm disagreement report supports per-hook thresholds", () => {
  const summary = {
    total: 3,
    byHook: [{ hook: "agent-model-resolver", count: 3 }],
    pairs: [],
  }
  assert.deepEqual(recommendLlmRolloutActions(summary, {
    hooks: {
      "agent-model-resolver": {
        tuneAt: 3,
      },
    },
  }), [
    {
      hook: "agent-model-resolver",
      action: "tune",
      reason: "moderate disagreement volume; refine prompt, context shaping, or fallback policy",
      disagreementCount: 3,
      thresholds: { investigateAt: 10, tuneAt: 3, observeAt: 1 },
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
  assert.deepEqual(report.recommendations[0]?.thresholds, { investigateAt: 10, tuneAt: 4, observeAt: 1 })
})

test("llm disagreement report renders markdown artifact", () => {
  const markdown = renderLlmRolloutMarkdown({
    metadata: {
      generatedAt: "2026-03-11T09:00:00.000Z",
      branch: "fix/next-parity-item-2",
      worktreePath: "/tmp/my_opencode-wt-next-parity-item-2",
      sourceAuditPath: "/tmp/gateway-events.jsonl",
      sourceAuditShared: true,
      invalidLines: 2,
    },
    summary: {
      total: 3,
      byHook: [{ hook: "agent-model-resolver", count: 3 }],
      pairs: [
        {
          hook: "agent-model-resolver",
          deterministicMeaning: "route_explore",
          aiMeaning: "route_librarian",
          count: 3,
        },
      ],
    },
    recommendations: [
      {
        hook: "agent-model-resolver",
        action: "observe",
        reason: "low disagreement volume; continue shadow sampling before promotion",
        disagreementCount: 3,
        thresholds: { investigateAt: 10, tuneAt: 4, observeAt: 1 },
      },
    ],
  })
  assert.match(markdown, /# LLM Disagreement Rollout Report/)
  assert.match(markdown, /Generated at: 2026-03-11T09:00:00.000Z/)
  assert.match(markdown, /Branch: `fix\/next-parity-item-2`/)
  assert.match(markdown, /Source audit: `\/tmp\/gateway-events.jsonl`/)
  assert.match(markdown, /Audit source scope: shared primary repo audit feed/)
  assert.match(markdown, /Invalid audit lines skipped: 2/)
  assert.match(markdown, /agent-model-resolver: observe \(3\)/)
  assert.match(markdown, /thresholds: investigate>=10, tune>=4, observe>=1/)
  assert.match(markdown, /route_explore -> route_librarian \(3\)/)
})
