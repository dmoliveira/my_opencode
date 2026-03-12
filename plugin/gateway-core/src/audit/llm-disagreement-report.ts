export interface GatewayAuditEvent {
  hook?: unknown
  reason_code?: unknown
  deterministic_decision_meaning?: unknown
  deterministic_decision_value?: unknown
  llm_decision_meaning?: unknown
  llm_decision_value?: unknown
}

export interface LlmDisagreementSummaryEntry {
  hook: string
  deterministicMeaning: string
  aiMeaning: string
  count: number
}

export interface LlmDisagreementSummary {
  total: number
  byHook: Array<{ hook: string; count: number }>
  pairs: LlmDisagreementSummaryEntry[]
}

export interface LlmRolloutRecommendation {
  hook: string
  action: "investigate" | "tune" | "observe"
  reason: string
  disagreementCount: number
  thresholds: LlmRolloutThresholds
}

export interface LlmRolloutThresholds {
  investigateAt: number
  tuneAt: number
  observeAt: number
}

export interface LlmRolloutThresholdMap {
  default?: Partial<LlmRolloutThresholds>
  hooks?: Record<string, Partial<LlmRolloutThresholds>>
}

export interface LlmRolloutReport {
  metadata?: {
    generatedAt?: string
    sourceAuditPath?: string
    worktreePath?: string
    branch?: string
    invalidLines?: number
    sourceAuditShared?: boolean
  }
  summary: LlmDisagreementSummary
  recommendations: LlmRolloutRecommendation[]
}

export interface ParsedGatewayAuditJsonl {
  events: GatewayAuditEvent[]
  invalidLines: number
}

const DEFAULT_THRESHOLDS: LlmRolloutThresholds = {
  investigateAt: 10,
  tuneAt: 4,
  observeAt: 1,
}

export function parseGatewayAuditJsonlWithDiagnostics(text: string): ParsedGatewayAuditJsonl {
  const events: GatewayAuditEvent[] = []
  let invalidLines = 0
  for (const line of String(text ?? "")
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean)) {
    try {
      events.push(JSON.parse(line) as GatewayAuditEvent)
    } catch {
      invalidLines += 1
    }
  }
  return { events, invalidLines }
}

export function parseGatewayAuditJsonl(text: string): GatewayAuditEvent[] {
  return parseGatewayAuditJsonlWithDiagnostics(text).events
}

function normalized(value: unknown): string {
  return String(value ?? "").trim().toLowerCase()
}

export function summarizeLlmDecisionDisagreements(events: GatewayAuditEvent[]): LlmDisagreementSummary {
  const pairCounts = new Map<string, LlmDisagreementSummaryEntry>()
  const hookCounts = new Map<string, number>()
  for (const event of events) {
    if (normalized(event.reason_code) !== "llm_decision_disagreement") {
      continue
    }
    const hook = normalized(event.hook) || "unknown"
    const deterministicMeaning = normalized(event.deterministic_decision_meaning) || "unknown"
    const aiMeaning = normalized(event.llm_decision_meaning) || "unknown"
    const key = `${hook}|${deterministicMeaning}|${aiMeaning}`
    const current = pairCounts.get(key)
    if (current) {
      current.count += 1
    } else {
      pairCounts.set(key, {
        hook,
        deterministicMeaning,
        aiMeaning,
        count: 1,
      })
    }
    hookCounts.set(hook, (hookCounts.get(hook) ?? 0) + 1)
  }
  const pairs = [...pairCounts.values()].sort((left, right) => right.count - left.count || left.hook.localeCompare(right.hook))
  const byHook = [...hookCounts.entries()]
    .map(([hook, count]) => ({ hook, count }))
    .sort((left, right) => right.count - left.count || left.hook.localeCompare(right.hook))
  return {
    total: pairs.reduce((sum, item) => sum + item.count, 0),
    byHook,
    pairs,
  }
}

function resolvedThresholds(hook: string, overrides?: LlmRolloutThresholdMap): LlmRolloutThresholds {
  const normalizedHook = hook.trim().toLowerCase()
  const defaultOverrides = overrides?.default ?? {}
  const hookOverrides = overrides?.hooks?.[normalizedHook] ?? overrides?.hooks?.[hook] ?? {}
  const merged: LlmRolloutThresholds = {
    investigateAt: hookOverrides.investigateAt ?? defaultOverrides.investigateAt ?? DEFAULT_THRESHOLDS.investigateAt,
    tuneAt: hookOverrides.tuneAt ?? defaultOverrides.tuneAt ?? DEFAULT_THRESHOLDS.tuneAt,
    observeAt: hookOverrides.observeAt ?? defaultOverrides.observeAt ?? DEFAULT_THRESHOLDS.observeAt,
  }
  return merged
}

export function recommendLlmRolloutActions(
  summary: LlmDisagreementSummary,
  overrides?: LlmRolloutThresholdMap,
): LlmRolloutRecommendation[] {
  const actions: LlmRolloutRecommendation[] = []
  for (const { hook, count } of summary.byHook) {
    const thresholds = resolvedThresholds(hook, overrides)
    if (count >= thresholds.investigateAt) {
      actions.push({
        hook,
        action: "investigate",
        reason: "high disagreement volume; keep in shadow and inspect top disagreement pairs",
        disagreementCount: count,
        thresholds,
      })
      continue
    }
    if (count >= thresholds.tuneAt) {
      actions.push({
        hook,
        action: "tune",
        reason: "moderate disagreement volume; refine prompt, context shaping, or fallback policy",
        disagreementCount: count,
        thresholds,
      })
      continue
    }
    if (count >= thresholds.observeAt) {
      actions.push({
        hook,
        action: "observe",
        reason: "low disagreement volume; continue shadow sampling before promotion",
        disagreementCount: count,
        thresholds,
      })
    }
  }
  return actions
}

export function buildLlmRolloutReport(
  events: GatewayAuditEvent[],
  overrides?: LlmRolloutThresholdMap,
): LlmRolloutReport {
  const summary = summarizeLlmDecisionDisagreements(events)
  return {
    summary,
    recommendations: recommendLlmRolloutActions(summary, overrides),
  }
}

export function renderLlmRolloutMarkdown(report: LlmRolloutReport): string {
  const lines: string[] = [
    "# LLM Disagreement Rollout Report",
    "",
    ...(report.metadata?.generatedAt ? [`- Generated at: ${report.metadata.generatedAt}`] : []),
    ...(report.metadata?.branch ? [`- Branch: \`${report.metadata.branch}\``] : []),
    ...(report.metadata?.worktreePath ? [`- Worktree: \`${report.metadata.worktreePath}\``] : []),
    ...(report.metadata?.sourceAuditPath ? [`- Source audit: \`${report.metadata.sourceAuditPath}\``] : []),
    ...(report.metadata?.sourceAuditShared ? ["- Audit source scope: shared primary repo audit feed"] : []),
    ...(typeof report.metadata?.invalidLines === "number"
      ? [`- Invalid audit lines skipped: ${report.metadata.invalidLines}`]
      : []),
    `- Total disagreements: ${report.summary.total}`,
    `- Hooks with disagreements: ${report.summary.byHook.length}`,
    "",
    "## Recommendations",
  ]

  if (report.recommendations.length === 0) {
    lines.push("", "- No disagreement data found.")
  } else {
    for (const item of report.recommendations) {
      lines.push(
        "",
        `- ${item.hook}: ${item.action} (${item.disagreementCount})`,
        `  - ${item.reason}`,
        `  - thresholds: investigate>=${item.thresholds.investigateAt}, tune>=${item.thresholds.tuneAt}, observe>=${item.thresholds.observeAt}`,
      )
    }
  }

  lines.push("", "## Top disagreement pairs")
  if (report.summary.pairs.length === 0) {
    lines.push("", "- No disagreement pairs found.")
  } else {
    for (const pair of report.summary.pairs.slice(0, 10)) {
      lines.push(
        "",
        `- ${pair.hook}: ${pair.deterministicMeaning} -> ${pair.aiMeaning} (${pair.count})`,
      )
    }
  }

  return `${lines.join("\n")}\n`
}
