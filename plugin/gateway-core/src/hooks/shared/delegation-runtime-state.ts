import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { dirname, resolve } from "node:path"

export interface DelegationStartInput {
  sessionId: string
  childRunId?: string
  subagentType: string
  category: string
  startedAt: number
  traceId?: string
}

export interface DelegationOutcomeInput {
  sessionId: string
  status: "completed" | "failed"
  reasonCode?: string
  endedAt: number
  childRunId?: string
  traceId?: string
  subagentType?: string
}

export interface DelegationOutcomeRecord {
  sessionId: string
  childRunId?: string
  subagentType: string
  category: string
  status: "completed" | "failed"
  reasonCode: string
  startedAt: number
  endedAt: number
  durationMs: number
  traceId?: string
}

interface ActiveDelegation {
  childRunId?: string
  subagentType: string
  category: string
  startedAt: number
  traceId?: string
}

interface PersistedState {
  timeline: DelegationOutcomeRecord[]
}

const activeByDelegation = new Map<string, ActiveDelegation>()
const timeline: DelegationOutcomeRecord[] = []

let statePath = ""
let stateMaxEntries = 300
let persistenceEnabled = false
let loaded = false

function normalizeRecord(value: unknown): DelegationOutcomeRecord | null {
  if (!value || typeof value !== "object") {
    return null
  }
  const source = value as Record<string, unknown>
  const status = source.status === "failed" ? "failed" : source.status === "completed" ? "completed" : null
  const sessionId = String(source.sessionId ?? "").trim()
  const subagentType = String(source.subagentType ?? "").trim()
  const category = String(source.category ?? "").trim()
  const reasonCode = String(source.reasonCode ?? "").trim()
  const startedAt = Number(source.startedAt ?? NaN)
  const endedAt = Number(source.endedAt ?? NaN)
  const durationMs = Number(source.durationMs ?? NaN)
  if (
    !status ||
    !sessionId ||
    !subagentType ||
    !category ||
    !reasonCode ||
    !Number.isFinite(startedAt) ||
    !Number.isFinite(endedAt) ||
    !Number.isFinite(durationMs)
  ) {
    return null
  }
  const childRunId = String(source.childRunId ?? "").trim() || undefined
  const traceId = String(source.traceId ?? "").trim() || undefined
  return {
    sessionId,
    childRunId,
    subagentType,
    category,
    status,
    reasonCode,
    startedAt,
    endedAt,
    durationMs,
    traceId,
  }
}

function trimTimeline(maxEntries: number): void {
  if (maxEntries <= 0) {
    timeline.splice(0, timeline.length)
    return
  }
  while (timeline.length > maxEntries) {
    timeline.shift()
  }
}

function persist(): void {
  if (!persistenceEnabled || !statePath) {
    return
  }
  const payload: PersistedState = { timeline }
  mkdirSync(dirname(statePath), { recursive: true })
  writeFileSync(statePath, JSON.stringify(payload, null, 2), "utf-8")
}

function load(): void {
  if (loaded) {
    return
  }
  loaded = true
  if (!persistenceEnabled || !statePath || !existsSync(statePath)) {
    return
  }
  try {
    const parsed = JSON.parse(readFileSync(statePath, "utf-8")) as PersistedState
    const records = Array.isArray(parsed?.timeline)
      ? parsed.timeline.map((item) => normalizeRecord(item)).filter((item): item is DelegationOutcomeRecord => item !== null)
      : []
    timeline.splice(0, timeline.length, ...records)
    trimTimeline(stateMaxEntries)
  } catch {
    timeline.splice(0, timeline.length)
  }
}

export function configureDelegationRuntimeState(options: {
  directory: string
  persistState: boolean
  stateFile: string
  stateMaxEntries: number
}): void {
  persistenceEnabled = options.persistState
  statePath = resolve(options.directory, options.stateFile)
  stateMaxEntries = Math.max(1, options.stateMaxEntries)
  loaded = false
  load()
}

function delegationKey(sessionId: string, childRunId?: string, traceId?: string, subagentType?: string): string {
  const normalizedChildRunId = String(childRunId ?? "").trim()
  if (normalizedChildRunId) {
    return `${sessionId}:${normalizedChildRunId}`
  }
  const normalizedTrace = String(traceId ?? "").trim()
  if (normalizedTrace) {
    return `${sessionId}:${normalizedTrace}`
  }
  const normalizedSubagent = String(subagentType ?? "").trim().toLowerCase() || "unknown"
  return `${sessionId}:agent:${normalizedSubagent}`
}

export function registerDelegationStart(input: DelegationStartInput): void {
  if (!input.sessionId.trim()) {
    return
  }
  load()
  activeByDelegation.set(delegationKey(input.sessionId, input.childRunId, input.traceId, input.subagentType), {
    childRunId: input.childRunId,
    subagentType: input.subagentType,
    category: input.category,
    startedAt: input.startedAt,
    traceId: input.traceId,
  })
}

export function registerDelegationOutcome(
  input: DelegationOutcomeInput,
  maxEntries: number,
): DelegationOutcomeRecord | null {
  load()
  const directKey = delegationKey(input.sessionId, input.childRunId, input.traceId, input.subagentType)
  let active = activeByDelegation.get(directKey)
  let activeKey = directKey
  if (!active && input.traceId) {
    const matches = [...activeByDelegation.entries()].filter(
      ([candidateKey, candidate]) =>
        (candidateKey === input.sessionId || candidateKey.startsWith(`${input.sessionId}:`)) &&
        candidate.traceId === input.traceId,
    )
    if (matches.length === 1) {
      ;[[activeKey, active]] = matches
    }
  }
  if (!active && !input.childRunId && !input.traceId && input.subagentType) {
    const matches = [...activeByDelegation.entries()].filter(
      ([candidateKey, candidate]) =>
        (candidateKey === input.sessionId || candidateKey.startsWith(`${input.sessionId}:`)) &&
        candidate.subagentType === input.subagentType,
    )
    if (matches.length === 1) {
      ;[[activeKey, active]] = matches
    }
  }
  if (!active && !input.childRunId && !input.traceId && !input.subagentType) {
    const matches = [...activeByDelegation.entries()].filter(
      ([candidateKey]) => candidateKey === input.sessionId || candidateKey.startsWith(`${input.sessionId}:`),
    )
    if (matches.length === 1) {
      ;[[activeKey, active]] = matches
    }
  }
  if (!active) {
    return null
  }
  activeByDelegation.delete(activeKey)
  const durationMs = Math.max(0, input.endedAt - active.startedAt)
  const record: DelegationOutcomeRecord = {
    sessionId: input.sessionId,
    childRunId: active.childRunId,
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
    traceId: active.traceId,
  }
  timeline.push(record)
  trimTimeline(Math.max(1, Math.min(maxEntries, stateMaxEntries)))
  persist()
  return record
}

export function clearDelegationSession(sessionId: string): void {
  for (const key of activeByDelegation.keys()) {
    if (key === sessionId || key.startsWith(`${sessionId}:`)) {
      activeByDelegation.delete(key)
    }
  }
}

export function getRecentDelegationOutcomes(windowMs: number): DelegationOutcomeRecord[] {
  load()
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
