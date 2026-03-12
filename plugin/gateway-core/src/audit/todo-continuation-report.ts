import { parseGatewayAuditJsonlWithDiagnostics, type GatewayAuditEvent } from "./llm-disagreement-report.js"

export interface TodoContinuationReasonCount {
  reasonCode: string
  count: number
}

export interface TodoContinuationSessionSummary {
  sessionId: string
  lastTs?: string
  injected: number
  todowriteSignals: number
  probeRetained: number
  stopGuards: number
  noPending: number
  probeFailures: number
  injectFailures: number
  llmDecisions: number
  llmShadows: number
  maxOpenTodoCount: number
  lastReasonCode?: string
}

export interface TodoContinuationReport {
  metadata?: {
    generatedAt?: string
    sourceAuditPath?: string
    worktreePath?: string
    branch?: string
    invalidLines?: number
    sourceAuditShared?: boolean
    sessionLimit?: number
  }
  totalEvents: number
  totalSessions: number
  reasonCounts: TodoContinuationReasonCount[]
  sessions: TodoContinuationSessionSummary[]
}

export interface TodoContinuationParsedReport {
  report: TodoContinuationReport
  invalidLines: number
}

function normalized(value: unknown): string {
  return String(value ?? "").trim().toLowerCase()
}

function latestIso(left: string | undefined, right: string | undefined): string | undefined {
  const leftText = String(left ?? "").trim()
  const rightText = String(right ?? "").trim()
  if (!leftText) {
    return rightText || undefined
  }
  if (!rightText) {
    return leftText
  }
  return rightText.localeCompare(leftText) > 0 ? rightText : leftText
}

function numeric(value: unknown): number {
  return Number.isFinite(value) ? Number(value) : Number.parseInt(String(value ?? ""), 10) || 0
}

function isTodoContinuationEvent(event: GatewayAuditEvent): boolean {
  const hook = normalized(event.hook)
  const reasonCode = normalized(event.reason_code)
  return (
    hook === "todo-continuation-enforcer" ||
    reasonCode.startsWith("todo_continuation_") ||
    reasonCode.startsWith("llm_todo_continuation_")
  )
}

function sortSessions(left: TodoContinuationSessionSummary, right: TodoContinuationSessionSummary): number {
  return (
    String(right.lastTs ?? "").localeCompare(String(left.lastTs ?? "")) ||
    right.injected - left.injected ||
    right.todowriteSignals - left.todowriteSignals ||
    left.sessionId.localeCompare(right.sessionId)
  )
}

export function buildTodoContinuationReport(
  events: GatewayAuditEvent[],
  options?: { sessionLimit?: number },
): TodoContinuationReport {
  const reasonCounts = new Map<string, number>()
  const sessionCounts = new Map<string, TodoContinuationSessionSummary>()
  let totalEvents = 0
  for (const event of events) {
    if (!isTodoContinuationEvent(event)) {
      continue
    }
    totalEvents += 1
    const reasonCode = normalized(event.reason_code) || "unknown"
    reasonCounts.set(reasonCode, (reasonCounts.get(reasonCode) ?? 0) + 1)

    const sessionId = String(event.session_id ?? "").trim()
    if (!sessionId) {
      continue
    }
    const current = sessionCounts.get(sessionId) ?? {
      sessionId,
      injected: 0,
      todowriteSignals: 0,
      probeRetained: 0,
      stopGuards: 0,
      noPending: 0,
      probeFailures: 0,
      injectFailures: 0,
      llmDecisions: 0,
      llmShadows: 0,
      maxOpenTodoCount: 0,
    }
    current.lastTs = latestIso(current.lastTs, String(event.ts ?? ""))
    current.lastReasonCode = reasonCode
    if (reasonCode === "todo_continuation_injected") {
      current.injected += 1
    }
    if (reasonCode === "todo_continuation_todowrite_state_recorded") {
      current.todowriteSignals += 1
      current.maxOpenTodoCount = Math.max(current.maxOpenTodoCount, numeric(event.open_todo_count))
    }
    if (reasonCode === "todo_continuation_task_probe_retained") {
      current.probeRetained += 1
    }
    if (reasonCode === "todo_continuation_stop_guard") {
      current.stopGuards += 1
    }
    if (reasonCode === "todo_continuation_no_pending") {
      current.noPending += 1
    }
    if (reasonCode === "todo_continuation_probe_failed") {
      current.probeFailures += 1
    }
    if (reasonCode === "todo_continuation_inject_failed") {
      current.injectFailures += 1
    }
    if (reasonCode === "llm_todo_continuation_decision_recorded") {
      current.llmDecisions += 1
    }
    if (reasonCode === "llm_todo_continuation_shadow_deferred") {
      current.llmShadows += 1
    }
    sessionCounts.set(sessionId, current)
  }

  const sessionLimit = options?.sessionLimit
  const sessions = [...sessionCounts.values()].sort(sortSessions)
  return {
    totalEvents,
    totalSessions: sessions.length,
    reasonCounts: [...reasonCounts.entries()]
      .map(([reasonCode, count]) => ({ reasonCode, count }))
      .sort((left, right) => right.count - left.count || left.reasonCode.localeCompare(right.reasonCode)),
    sessions: sessions.slice(0, sessionLimit && sessionLimit > 0 ? sessionLimit : 10),
  }
}

export function parseTodoContinuationReport(
  text: string,
  options?: { sessionLimit?: number },
): TodoContinuationParsedReport {
  const parsed = parseGatewayAuditJsonlWithDiagnostics(text)
  return {
    report: buildTodoContinuationReport(parsed.events, options),
    invalidLines: parsed.invalidLines,
  }
}

export function renderTodoContinuationMarkdown(report: TodoContinuationReport): string {
  const lines: string[] = [
    "# Todo Continuation Audit Report",
    "",
    ...(report.metadata?.generatedAt ? [`- Generated at: ${report.metadata.generatedAt}`] : []),
    ...(report.metadata?.branch ? [`- Branch: \`${report.metadata.branch}\``] : []),
    ...(report.metadata?.worktreePath ? [`- Worktree: \`${report.metadata.worktreePath}\``] : []),
    ...(report.metadata?.sourceAuditPath ? [`- Source audit: \`${report.metadata.sourceAuditPath}\``] : []),
    ...(report.metadata?.sourceAuditShared ? ["- Audit source scope: shared primary repo audit feed"] : []),
    ...(typeof report.metadata?.invalidLines === "number"
      ? [`- Invalid audit lines skipped: ${report.metadata.invalidLines}`]
      : []),
    ...(typeof report.metadata?.sessionLimit === "number"
      ? [`- Session rows shown: ${report.metadata.sessionLimit}`]
      : []),
    `- Total continuation events: ${report.totalEvents}`,
    `- Sessions with continuation evidence: ${report.totalSessions}`,
    ...(report.totalSessions > report.sessions.length
      ? [`- Session rows rendered: ${report.sessions.length}`]
      : []),
    "",
    "## Reason counts",
  ]

  if (report.reasonCounts.length === 0) {
    lines.push("", "- No todo continuation audit events found.")
  } else {
    for (const item of report.reasonCounts) {
      lines.push("", `- ${item.reasonCode}: ${item.count}`)
    }
  }

  lines.push("", "## Recent sessions")
  if (report.sessions.length === 0) {
    lines.push("", "- No continuation sessions found.")
  } else {
    for (const session of report.sessions) {
      const details = [
        `injected=${session.injected}`,
        `todowrite_signals=${session.todowriteSignals}`,
        `probe_retained=${session.probeRetained}`,
        `stop_guards=${session.stopGuards}`,
        `no_pending=${session.noPending}`,
      ]
      if (session.maxOpenTodoCount > 0) {
        details.push(`max_open_todos=${session.maxOpenTodoCount}`)
      }
      if (session.llmDecisions > 0 || session.llmShadows > 0) {
        details.push(`llm=${session.llmDecisions}`, `llm_shadow=${session.llmShadows}`)
      }
      if (session.probeFailures > 0 || session.injectFailures > 0) {
        details.push(`probe_failures=${session.probeFailures}`, `inject_failures=${session.injectFailures}`)
      }
      lines.push(
        "",
        `- ${session.sessionId} (${session.lastTs ?? "unknown time"})`,
        `  - ${details.join(", ")}`,
        ...(session.lastReasonCode ? [`  - last_reason=${session.lastReasonCode}`] : []),
      )
    }
  }

  return `${lines.join("\n")}\n`
}
