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

export function parseGatewayAuditJsonl(text: string): GatewayAuditEvent[] {
  return String(text ?? "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      try {
        return JSON.parse(line) as GatewayAuditEvent
      } catch {
        return null
      }
    })
    .filter((item): item is GatewayAuditEvent => Boolean(item))
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
