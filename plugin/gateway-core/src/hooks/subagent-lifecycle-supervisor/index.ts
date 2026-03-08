import { createHash } from "node:crypto"

import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import {
  annotateDelegationMetadata,
  extractDelegationChildRunId,
  extractDelegationSubagentType,
  extractDelegationSubagentTypeFromOutput,
  extractDelegationTraceId,
  resolveDelegationTraceId,
} from "../shared/delegation-trace.js"

interface ToolPayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
  }
  output?: {
    args?: {
      subagent_type?: string
      prompt?: string
      description?: string
    }
    metadata?: unknown
    output?: unknown
  }
  directory?: string
  error?: unknown
}

interface DelegationArgs {
  subagent_type?: string
  category?: string
  prompt?: string
  description?: string
}

interface SessionDeletedPayload {
  properties?: {
    info?: {
      id?: string
    }
  }
}

interface LifecycleState {
  childRunId?: string
  traceId?: string
  subagentType: string
  status: "running" | "failed" | "completed"
  failureCount: number
  lastStartedAt: number
  lastUpdatedAt: number
  lastReasonCode?: string
}

function fallbackDelegationKey(sid: string, args: DelegationArgs | undefined): string {
  const subagentType = String(args?.subagent_type ?? "").toLowerCase().trim()
  const category = String(args?.category ?? "").toLowerCase().trim()
  const prompt = String(args?.prompt ?? "").trim()
  const description = String(args?.description ?? "").trim()
  const fingerprintSource = [subagentType, category, prompt, description]
    .filter(Boolean)
    .join("\n")
  if (fingerprintSource) {
    const fingerprint = createHash("sha1").update(fingerprintSource).digest("hex").slice(0, 12)
    return `${sid}:fp:${fingerprint}`
  }
  return `${sid}:agent:${subagentType || "unknown"}`
}

function lifecycleKey(sid: string, childRunId: string, traceId: string, args?: DelegationArgs): string {
  if (childRunId) {
    return `${sid}:${childRunId}`
  }
  return traceId ? `${sid}:${traceId}` : fallbackDelegationKey(sid, args)
}

function sessionId(payload: {
  input?: { sessionID?: string; sessionId?: string }
  properties?: { info?: { id?: string } }
}): string {
  return String(payload.input?.sessionID ?? payload.input?.sessionId ?? payload.properties?.info?.id ?? "").trim()
}

function nowMs(): number {
  return Date.now()
}

function sessionLifecycleKeys(
  byDelegation: Map<string, LifecycleState>,
  sid: string,
): string[] {
  const matches: string[] = []
  for (const key of byDelegation.keys()) {
    if (key === sid || key.startsWith(`${sid}:`)) {
      matches.push(key)
    }
  }
  return matches
}

function matchingSessionLifecycleKeys(
  byDelegation: Map<string, LifecycleState>,
  sid: string,
  subagentType: string,
): string[] {
  const matches: string[] = []
  for (const [key, value] of byDelegation.entries()) {
    if ((key === sid || key.startsWith(`${sid}:`)) && value.subagentType === subagentType) {
      matches.push(key)
    }
  }
  return matches
}

function matchingSessionTraceLifecycleKeys(
  byDelegation: Map<string, LifecycleState>,
  sid: string,
  traceId: string,
): string[] {
  const matches: string[] = []
  for (const [key, value] of byDelegation.entries()) {
    if ((key === sid || key.startsWith(`${sid}:`)) && value.traceId === traceId) {
      matches.push(key)
    }
  }
  return matches
}

function isFailureOutput(output: string): boolean {
  const trimmed = output.trim()
  if (!trimmed) {
    return false
  }
  return /(^\[error\]|^error:|^exception:|^traceback\b|invalid arguments|unknown\s+agent|unknown\s+category|blocked delegation)/im.test(
    trimmed,
  )
}

export function createSubagentLifecycleSupervisorHook(options: {
  directory: string
  enabled: boolean
  maxRetriesPerSession: number
  staleRunningMs: number
  blockOnExhausted: boolean
}): GatewayHook {
  const byDelegation = new Map<string, LifecycleState>()

  function resolveLifecycleState(eventPayload: ToolPayload): { sid: string; activeKey: string; state?: LifecycleState } | null {
    const sid = sessionId(eventPayload)
    if (!sid) {
      return null
    }
    const traceId = extractDelegationTraceId(eventPayload.output?.args, eventPayload.output?.metadata)
    const childRunId = extractDelegationChildRunId(eventPayload.output?.metadata)
    const key = lifecycleKey(sid, childRunId, traceId, eventPayload.output?.args)
    let activeKey = key
    let state = byDelegation.get(activeKey)
    if (!state && traceId) {
      const traceMatches = matchingSessionTraceLifecycleKeys(byDelegation, sid, traceId)
      if (traceMatches.length === 1) {
        activeKey = traceMatches[0]
        state = byDelegation.get(activeKey)
      }
    }
    if (!state && !childRunId && !traceId) {
      const outputText = typeof eventPayload.output?.output === "string" ? eventPayload.output.output : ""
      const outputSubagentType =
        extractDelegationSubagentType(eventPayload.output?.args, eventPayload.output?.metadata) ||
        extractDelegationSubagentTypeFromOutput(outputText)
      const matches = outputSubagentType
        ? matchingSessionLifecycleKeys(byDelegation, sid, outputSubagentType)
        : sessionLifecycleKeys(byDelegation, sid)
      if (matches.length === 1) {
        activeKey = matches[0]
        state = byDelegation.get(activeKey)
      }
    }
    return { sid, activeKey, state }
  }

  return {
    id: "subagent-lifecycle-supervisor",
    priority: 295,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }
      if (type === "session.deleted") {
        const sid = sessionId((payload ?? {}) as SessionDeletedPayload)
        if (sid) {
          for (const key of byDelegation.keys()) {
            if (key === sid || key.startsWith(`${sid}:`)) {
              byDelegation.delete(key)
            }
          }
        }
        return
      }
      if (type === "tool.execute.before") {
        const eventPayload = (payload ?? {}) as ToolPayload
        if (String(eventPayload.input?.tool ?? "").toLowerCase().trim() !== "task") {
          return
        }
        const sid = sessionId(eventPayload)
        if (!sid) {
          return
        }
        const subagentType = String(eventPayload.output?.args?.subagent_type ?? "").toLowerCase().trim()
        if (!subagentType) {
          return
        }
        const traceId = resolveDelegationTraceId(eventPayload.output?.args ?? {})
        annotateDelegationMetadata(eventPayload.output ?? {}, eventPayload.output?.args)
        const childRunId = extractDelegationChildRunId(eventPayload.output?.metadata)
        const key = lifecycleKey(sid, childRunId, traceId, eventPayload.output?.args)
        const directory =
          typeof eventPayload.directory === "string" && eventPayload.directory.trim()
            ? eventPayload.directory
            : options.directory
        const existing = byDelegation.get(key)
        const now = nowMs()
        if (existing && existing.status === "running" && now - existing.lastStartedAt < options.staleRunningMs) {
          writeGatewayEventAudit(directory, {
            hook: "subagent-lifecycle-supervisor",
            stage: "guard",
            reason_code: "subagent_lifecycle_duplicate_running_blocked",
            session_id: sid,
            child_run_id: childRunId || undefined,
            trace_id: traceId || undefined,
            subagent_type: subagentType,
          })
          throw new Error(
            `Blocked delegation: subagent session ${sid} is already running for ${existing.subagentType}. Wait for completion or stale timeout.`,
          )
        }
        if (
          options.blockOnExhausted &&
          existing &&
          existing.status === "failed" &&
          existing.failureCount >= options.maxRetriesPerSession
        ) {
          writeGatewayEventAudit(directory, {
            hook: "subagent-lifecycle-supervisor",
            stage: "guard",
            reason_code: "subagent_lifecycle_retry_exhausted_blocked",
            session_id: sid,
            child_run_id: childRunId || undefined,
            trace_id: traceId || undefined,
            subagent_type: subagentType,
            failure_count: String(existing.failureCount),
          })
          throw new Error(
            `Blocked delegation: retry budget exhausted for session ${sid} (${existing.failureCount}/${options.maxRetriesPerSession}).`,
          )
        }
        const nextFailureCount = existing?.status === "failed" ? existing.failureCount : 0
        byDelegation.set(key, {
          childRunId: childRunId || undefined,
          traceId: traceId || undefined,
          subagentType,
          status: "running",
          failureCount: nextFailureCount,
          lastStartedAt: now,
          lastUpdatedAt: now,
          lastReasonCode: "subagent_lifecycle_started",
        })
        writeGatewayEventAudit(directory, {
          hook: "subagent-lifecycle-supervisor",
          stage: "state",
          reason_code: "subagent_lifecycle_started",
          session_id: sid,
          child_run_id: childRunId || undefined,
          trace_id: traceId || undefined,
          subagent_type: subagentType,
          failure_count: String(nextFailureCount),
        })
        return
      }
      if (type === "tool.execute.before.error") {
        const eventPayload = (payload ?? {}) as ToolPayload
        if (String(eventPayload.input?.tool ?? "").toLowerCase().trim() !== "task") {
          return
        }
        const resolved = resolveLifecycleState(eventPayload)
        if (!resolved?.state) {
          return
        }
        byDelegation.delete(resolved.activeKey)
        writeGatewayEventAudit(options.directory, {
          hook: "subagent-lifecycle-supervisor",
          stage: "state",
          reason_code: "subagent_lifecycle_before_error_released",
          session_id: resolved.sid,
          subagent_type: resolved.state.subagentType,
          trace_id: resolved.state.traceId,
          child_run_id: resolved.state.childRunId,
        })
        return
      }
      if (type !== "tool.execute.after") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolPayload
      if (String(eventPayload.input?.tool ?? "").toLowerCase().trim() !== "task") {
        return
      }
      const resolved = resolveLifecycleState(eventPayload)
      if (!resolved) {
        return
      }
      const sid = resolved.sid
      const traceId = extractDelegationTraceId(eventPayload.output?.args, eventPayload.output?.metadata)
      const childRunId = extractDelegationChildRunId(eventPayload.output?.metadata)
      let activeKey = resolved.activeKey
      let state = resolved.state
      if (!state && !childRunId && !traceId) {
        const outputText = typeof eventPayload.output?.output === "string" ? eventPayload.output.output : ""
        const outputSubagentType =
          extractDelegationSubagentType(eventPayload.output?.args, eventPayload.output?.metadata) ||
          extractDelegationSubagentTypeFromOutput(outputText)
        const matches = outputSubagentType
          ? matchingSessionLifecycleKeys(byDelegation, sid, outputSubagentType)
          : sessionLifecycleKeys(byDelegation, sid)
        if (matches.length > 1) {
          writeGatewayEventAudit(options.directory, {
            hook: "subagent-lifecycle-supervisor",
            stage: "skip",
            reason_code: "subagent_lifecycle_after_ambiguous_skip",
            session_id: sid,
            concurrent_total: String(matches.length),
          })
          return
        }
      }
      if (!state) {
        return
      }
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const outputText = typeof eventPayload.output?.output === "string" ? eventPayload.output.output : ""
      if (isFailureOutput(outputText)) {
        const failedCount = state.failureCount + 1
        byDelegation.set(activeKey, {
          ...state,
          status: "failed",
          failureCount: failedCount,
          lastUpdatedAt: nowMs(),
          lastReasonCode: "subagent_lifecycle_failed",
        })
        writeGatewayEventAudit(directory, {
          hook: "subagent-lifecycle-supervisor",
          stage: "state",
          reason_code: "subagent_lifecycle_failed",
          session_id: sid,
          child_run_id: childRunId || undefined,
          trace_id: traceId || undefined,
          subagent_type: state.subagentType,
          failure_count: String(failedCount),
        })
        if (typeof eventPayload.output?.output === "string") {
          eventPayload.output.output += `\n[subagent-lifecycle-supervisor] state=failed retries=${failedCount}/${options.maxRetriesPerSession}`
        }
        return
      }
      byDelegation.set(activeKey, {
        ...state,
        status: "completed",
        lastUpdatedAt: nowMs(),
        lastReasonCode: "subagent_lifecycle_completed",
      })
      writeGatewayEventAudit(directory, {
        hook: "subagent-lifecycle-supervisor",
        stage: "state",
        reason_code: "subagent_lifecycle_completed",
        session_id: sid,
        child_run_id: childRunId || undefined,
        trace_id: traceId || undefined,
        subagent_type: state.subagentType,
        failure_count: String(state.failureCount),
      })
      byDelegation.delete(activeKey)
    },
  }
}
