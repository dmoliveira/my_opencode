export interface DelegationStartInput {
  sessionId: string
  subagentType: string
  category: string
  startedAt: number
}

export interface DelegationOutcomeInput {
  sessionId: string
  status: "completed" | "failed"
  reasonCode?: string
  endedAt: number
}

export interface DelegationOutcomeRecord {
  sessionId: string
  subagentType: string
  category: string
  status: "completed" | "failed"
  reasonCode: string
  startedAt: number
  endedAt: number
  durationMs: number
}

interface ActiveDelegation {
  subagentType: string
  category: string
  startedAt: number
}

const activeBySession = new Map<string, ActiveDelegation>()
const timeline: DelegationOutcomeRecord[] = []

function pushTimeline(record: DelegationOutcomeRecord, maxEntries: number): void {
  timeline.push(record)
  if (maxEntries <= 0) {
    timeline.splice(0, timeline.length)
    return
  }
  while (timeline.length > maxEntries) {
    timeline.shift()
  }
}

export function registerDelegationStart(input: DelegationStartInput): void {
  if (!input.sessionId.trim()) {
    return
  }
  activeBySession.set(input.sessionId, {
    subagentType: input.subagentType,
    category: input.category,
    startedAt: input.startedAt,
  })
}

export function registerDelegationOutcome(
  input: DelegationOutcomeInput,
  maxEntries: number,
): DelegationOutcomeRecord | null {
  const active = activeBySession.get(input.sessionId)
  if (!active) {
    return null
  }
  activeBySession.delete(input.sessionId)
  const durationMs = Math.max(0, input.endedAt - active.startedAt)
  const record: DelegationOutcomeRecord = {
    sessionId: input.sessionId,
    subagentType: active.subagentType,
    category: active.category,
    status: input.status,
    reasonCode:
      input.reasonCode ??
      (input.status === "failed"
        ? "delegation_runtime_failure"
        : "delegation_runtime_completed"),
    startedAt: active.startedAt,
    endedAt: input.endedAt,
    durationMs,
  }
  pushTimeline(record, maxEntries)
  return record
}

export function clearDelegationSession(sessionId: string): void {
  activeBySession.delete(sessionId)
}

export function getRecentDelegationOutcomes(windowMs: number): DelegationOutcomeRecord[] {
  const minTs = Date.now() - Math.max(0, windowMs)
  return timeline.filter((item) => item.endedAt >= minTs)
}

export function getDelegationFailureStats(windowMs: number): {
  total: number
  failed: number
  failureRate: number
} {
  const outcomes = getRecentDelegationOutcomes(windowMs)
  const total = outcomes.length
  const failed = outcomes.filter((item) => item.status === "failed").length
  return {
    total,
    failed,
    failureRate: total > 0 ? failed / total : 0,
  }
}
