import assert from "node:assert/strict"
import test from "node:test"

import {
  buildTodoContinuationReport,
  parseTodoContinuationReport,
  renderTodoContinuationMarkdown,
} from "../dist/audit/todo-continuation-report.js"

test("todo continuation report summarizes reason counts and recent sessions", () => {
  const report = buildTodoContinuationReport([
    {
      hook: "todo-continuation-enforcer",
      reason_code: "todo_continuation_todowrite_state_recorded",
      session_id: "ses-1",
      ts: "2026-03-11T10:00:00.000Z",
      open_todo_count: 3,
    },
    {
      hook: "todo-continuation-enforcer",
      reason_code: "todo_continuation_injected",
      session_id: "ses-1",
      ts: "2026-03-11T10:01:00.000Z",
    },
    {
      hook: "todo-continuation-enforcer",
      reason_code: "todo_continuation_task_probe_retained",
      session_id: "ses-2",
      ts: "2026-03-11T10:02:00.000Z",
    },
    {
      hook: "todo-continuation-enforcer",
      reason_code: "llm_todo_continuation_decision_recorded",
      session_id: "ses-2",
      ts: "2026-03-11T10:03:00.000Z",
    },
    {
      hook: "another-hook",
      reason_code: "other_reason",
      session_id: "ses-ignored",
      ts: "2026-03-11T10:04:00.000Z",
    },
  ])

  assert.equal(report.totalEvents, 4)
  assert.equal(report.totalSessions, 2)
  assert.deepEqual(report.reasonCounts, [
    { reasonCode: "llm_todo_continuation_decision_recorded", count: 1 },
    { reasonCode: "todo_continuation_injected", count: 1 },
    { reasonCode: "todo_continuation_task_probe_retained", count: 1 },
    { reasonCode: "todo_continuation_todowrite_state_recorded", count: 1 },
  ])
  assert.deepEqual(report.sessions, [
    {
      sessionId: "ses-2",
      lastTs: "2026-03-11T10:03:00.000Z",
      injected: 0,
      todowriteSignals: 0,
      probeRetained: 1,
      stopGuards: 0,
      noPending: 0,
      probeFailures: 0,
      injectFailures: 0,
      llmDecisions: 1,
      llmShadows: 0,
      maxOpenTodoCount: 0,
      lastReasonCode: "llm_todo_continuation_decision_recorded",
    },
    {
      sessionId: "ses-1",
      lastTs: "2026-03-11T10:01:00.000Z",
      injected: 1,
      todowriteSignals: 1,
      probeRetained: 0,
      stopGuards: 0,
      noPending: 0,
      probeFailures: 0,
      injectFailures: 0,
      llmDecisions: 0,
      llmShadows: 0,
      maxOpenTodoCount: 3,
      lastReasonCode: "todo_continuation_injected",
    },
  ])
})

test("todo continuation report tracks invalid jsonl lines", () => {
  const parsed = parseTodoContinuationReport(`
{"hook":"todo-continuation-enforcer","reason_code":"todo_continuation_injected","session_id":"ses-1"}
not-json
`)
  assert.equal(parsed.invalidLines, 1)
  assert.equal(parsed.report.totalEvents, 1)
  assert.equal(parsed.report.totalSessions, 1)
})

test("todo continuation report keeps total session count when rows are limited", () => {
  const report = buildTodoContinuationReport(
    [
      {
        hook: "todo-continuation-enforcer",
        reason_code: "todo_continuation_injected",
        session_id: "ses-a",
        ts: "2026-03-11T10:00:00.000Z",
      },
      {
        hook: "todo-continuation-enforcer",
        reason_code: "todo_continuation_injected",
        session_id: "ses-b",
        ts: "2026-03-11T10:01:00.000Z",
      },
      {
        hook: "todo-continuation-enforcer",
        reason_code: "todo_continuation_injected",
        session_id: "ses-c",
        ts: "2026-03-11T10:02:00.000Z",
      },
    ],
    { sessionLimit: 2 },
  )

  assert.equal(report.totalSessions, 3)
  assert.equal(report.sessions.length, 2)
  const markdown = renderTodoContinuationMarkdown(report)
  assert.match(markdown, /Sessions with continuation evidence: 3/)
  assert.match(markdown, /Session rows rendered: 2/)
})

test("todo continuation report uses latest timestamp even when events are out of order", () => {
  const report = buildTodoContinuationReport([
    {
      hook: "todo-continuation-enforcer",
      reason_code: "todo_continuation_injected",
      session_id: "ses-z",
      ts: "2026-03-11T10:05:00.000Z",
    },
    {
      hook: "todo-continuation-enforcer",
      reason_code: "todo_continuation_todowrite_state_recorded",
      session_id: "ses-z",
      ts: "2026-03-11T10:01:00.000Z",
      open_todo_count: 4,
    },
  ])

  assert.equal(report.sessions[0].lastTs, "2026-03-11T10:05:00.000Z")
  assert.equal(report.sessions[0].maxOpenTodoCount, 4)
})

test("todo continuation report renders markdown artifact", () => {
  const markdown = renderTodoContinuationMarkdown({
    metadata: {
      generatedAt: "2026-03-11T11:00:00.000Z",
      branch: "feat/continuation-audit-report",
      worktreePath: "/tmp/my_opencode-wt-continuation-audit",
      sourceAuditPath: "/tmp/gateway-events.jsonl",
      sourceAuditShared: true,
      invalidLines: 2,
      sessionLimit: 5,
    },
    totalEvents: 3,
    totalSessions: 1,
    reasonCounts: [{ reasonCode: "todo_continuation_injected", count: 2 }],
    sessions: [
      {
        sessionId: "ses-1",
        lastTs: "2026-03-11T10:01:00.000Z",
        injected: 2,
        todowriteSignals: 1,
        probeRetained: 1,
        stopGuards: 0,
        noPending: 0,
        probeFailures: 0,
        injectFailures: 0,
        llmDecisions: 1,
        llmShadows: 0,
        maxOpenTodoCount: 4,
        lastReasonCode: "todo_continuation_injected",
      },
    ],
  })

  assert.match(markdown, /# Todo Continuation Audit Report/)
  assert.match(markdown, /Generated at: 2026-03-11T11:00:00.000Z/)
  assert.match(markdown, /Branch: `feat\/continuation-audit-report`/)
  assert.match(markdown, /Session rows shown: 5/)
  assert.match(markdown, /Sessions with continuation evidence: 1/)
  assert.match(markdown, /todo_continuation_injected: 2/)
  assert.match(markdown, /ses-1 \(2026-03-11T10:01:00.000Z\)/)
  assert.match(markdown, /max_open_todos=4/)
  assert.match(markdown, /llm=1/)
})
