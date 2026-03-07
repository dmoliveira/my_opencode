import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import {
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
    output?: unknown
  }
  directory?: string
}

interface SessionDeletedPayload {
  properties?: {
    info?: {
      id?: string
    }
  }
}

interface LifecycleState {
  subagentType: string
  status: "running" | "failed" | "completed"
  failureCount: number
  lastStartedAt: number
  lastUpdatedAt: number
  lastReasonCode?: string
}

function lifecycleKey(sid: string, traceId: string): string {
  return traceId ? `${sid}:${traceId}` : sid
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

function isFailureOutput(output: string): boolean {
  return /(\[error\]|invalid arguments|failed|exception|traceback|unknown\s+agent|unknown\s+category|blocked delegation)/i.test(
    output,
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
        const key = lifecycleKey(sid, traceId)
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
          trace_id: traceId || undefined,
          subagent_type: subagentType,
          failure_count: String(nextFailureCount),
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
      const sid = sessionId(eventPayload)
      if (!sid) {
        return
      }
      const traceId = extractDelegationTraceId(eventPayload.output?.args)
      const key = lifecycleKey(sid, traceId)
      let activeKey = key
      let state = byDelegation.get(activeKey)
      if (!state) {
        if (!traceId) {
          for (const candidate of byDelegation.keys()) {
            if (candidate === sid || candidate.startsWith(`${sid}:`)) {
              activeKey = candidate
              state = byDelegation.get(candidate)
              break
            }
          }
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
        trace_id: traceId || undefined,
        subagent_type: state.subagentType,
        failure_count: String(state.failureCount),
      })
      byDelegation.delete(activeKey)
    },
  }
}
