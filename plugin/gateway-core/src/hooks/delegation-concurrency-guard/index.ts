import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import { loadAgentMetadata } from "../shared/agent-metadata.js"
import {
  annotateDelegationMetadata,
  extractDelegationChildRunId,
  extractDelegationSubagentType,
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
      category?: string
    }
    metadata?: unknown
    output?: unknown
  }
  directory?: string
  error?: unknown
}

interface SessionDeletedPayload {
  properties?: {
    info?: {
      id?: string
    }
  }
}

interface ActiveDelegation {
  childRunId: string
  subagentType: string
  category: string
  costTier: string
  traceId: string
  startedAt: number
}

function nowMs(): number {
  return Date.now()
}

function delegationKey(sid: string, childRunId: string): string {
  return `${sid}:${childRunId}`
}

function sessionId(payload: {
  input?: { sessionID?: string; sessionId?: string }
  properties?: { info?: { id?: string } }
}): string {
  return String(payload.input?.sessionID ?? payload.input?.sessionId ?? payload.properties?.info?.id ?? "").trim()
}

function effectiveDirectory(payload: ToolPayload, fallbackDirectory: string): string {
  return typeof payload.directory === "string" && payload.directory.trim() ? payload.directory : fallbackDirectory
}

export function createDelegationConcurrencyGuardHook(options: {
  directory: string
  enabled: boolean
  maxTotalConcurrent: number
  maxExpensiveConcurrent: number
  maxDeepConcurrent: number
  maxCriticalConcurrent: number
  staleReservationMs: number
}): GatewayHook {
  const activeByDelegation = new Map<string, ActiveDelegation>()

  function releaseDelegationReservation(eventPayload: ToolPayload, directory: string): "none" | "direct" | "missing_identity" {
    const sid = sessionId(eventPayload)
    if (!sid) {
      return "none"
    }
    const childRunId = extractDelegationChildRunId(eventPayload.output?.metadata)
    const traceId = extractDelegationTraceId(eventPayload.output?.args, eventPayload.output?.metadata)
    if (childRunId) {
      const key = delegationKey(sid, childRunId)
      if (activeByDelegation.delete(key)) {
        return "direct"
      }
      return "none"
    }
    if (eventPayload.output) {
      writeGatewayEventAudit(directory, {
        hook: "delegation-concurrency-guard",
        stage: "skip",
        reason_code: "delegation_concurrency_after_missing_identity",
        session_id: sid,
        trace_id: traceId || undefined,
      })
      return "missing_identity"
    }
    return "none"
  }

  function pruneStaleDelegations(directory: string, referenceTime: number): void {
    for (const [key, active] of activeByDelegation.entries()) {
      if (referenceTime - active.startedAt < options.staleReservationMs) {
        continue
      }
      activeByDelegation.delete(key)
      const [sessionKey] = key.split(":", 1)
      writeGatewayEventAudit(directory, {
        hook: "delegation-concurrency-guard",
        stage: "state",
        reason_code: "delegation_concurrency_stale_pruned",
        session_id: sessionKey,
        child_run_id: active.childRunId,
        trace_id: active.traceId || undefined,
        subagent_type: active.subagentType || undefined,
        category: active.category || undefined,
        cost_tier: active.costTier || undefined,
      })
    }
  }

  return {
    id: "delegation-concurrency-guard",
    priority: 294,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }
      if (type === "session.deleted") {
        const sid = sessionId((payload ?? {}) as SessionDeletedPayload)
        if (sid) {
          for (const key of activeByDelegation.keys()) {
            if (key === sid || key.startsWith(`${sid}:`)) {
              activeByDelegation.delete(key)
            }
          }
        }
        return
      }
      if (type === "tool.execute.after") {
        const eventPayload = (payload ?? {}) as ToolPayload
        if (String(eventPayload.input?.tool ?? "").toLowerCase().trim() !== "task") {
          return
        }
        releaseDelegationReservation(eventPayload, effectiveDirectory(eventPayload, options.directory))
        return
      }
      if (type === "tool.execute.before.error") {
        const eventPayload = (payload ?? {}) as ToolPayload
        if (String(eventPayload.input?.tool ?? "").toLowerCase().trim() !== "task") {
          return
        }
        const sid = sessionId(eventPayload)
        if (!sid) {
          return
        }
        const directory = effectiveDirectory(eventPayload, options.directory)
        const releaseMode = releaseDelegationReservation(eventPayload, directory)
        if (releaseMode === "direct") {
          writeGatewayEventAudit(directory, {
            hook: "delegation-concurrency-guard",
            stage: "state",
            reason_code: "delegation_concurrency_before_error_released",
            session_id: sid,
          })
        }
        return
      }
      if (type !== "tool.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolPayload
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase().trim()
      if (tool !== "task") {
        return
      }
      const sid = sessionId(eventPayload)
      if (!sid) {
        return
      }
      const args = eventPayload.output?.args
      if (!args || typeof args !== "object") {
        return
      }
      const subagentType = String(args.subagent_type ?? "").toLowerCase().trim()
      const category = String(args.category ?? "").toLowerCase().trim()
      const traceId = resolveDelegationTraceId(args ?? {})
      annotateDelegationMetadata(eventPayload.output ?? {}, args)
      const childRunId = extractDelegationChildRunId(eventPayload.output?.metadata)
      if (!childRunId) {
        return
      }
      const key = delegationKey(sid, childRunId)
      if (!subagentType && !category) {
        return
      }
      const directory = effectiveDirectory(eventPayload, options.directory)
      const now = nowMs()
      pruneStaleDelegations(directory, now)
      const metadata = subagentType ? loadAgentMetadata(directory).get(subagentType) : undefined
      const costTier = String(metadata?.cost_tier ?? "cheap").toLowerCase()
      const fallbackCategory = category.length > 0 ? category : "balanced"
      const recommendedCategory = String(
        metadata?.default_category ?? fallbackCategory,
      ).toLowerCase()

      const values = [...activeByDelegation.values()]
      const total = values.length
      const expensive = values.filter((item) => item.costTier === "expensive").length
      const deep = values.filter((item) => item.category === "deep").length
      const critical = values.filter((item) => item.category === "critical").length

      if (total >= options.maxTotalConcurrent) {
        writeGatewayEventAudit(directory, {
          hook: "delegation-concurrency-guard",
          stage: "guard",
          reason_code: "delegation_concurrency_total_blocked",
          session_id: sid,
          concurrent_total: String(total),
        })
        throw new Error(
          `Blocked delegation: concurrent task delegations ${total} reached maxTotalConcurrent=${options.maxTotalConcurrent}.`,
        )
      }
      if (costTier === "expensive" && expensive >= options.maxExpensiveConcurrent) {
        writeGatewayEventAudit(directory, {
          hook: "delegation-concurrency-guard",
          stage: "guard",
          reason_code: "delegation_concurrency_expensive_blocked",
          session_id: sid,
          concurrent_expensive: String(expensive),
        })
        throw new Error(
          `Blocked delegation: expensive concurrent delegations ${expensive} reached maxExpensiveConcurrent=${options.maxExpensiveConcurrent}.`,
        )
      }
      if (recommendedCategory === "deep" && deep >= options.maxDeepConcurrent) {
        writeGatewayEventAudit(directory, {
          hook: "delegation-concurrency-guard",
          stage: "guard",
          reason_code: "delegation_concurrency_deep_blocked",
          session_id: sid,
          concurrent_deep: String(deep),
        })
        throw new Error(
          `Blocked delegation: deep concurrent delegations ${deep} reached maxDeepConcurrent=${options.maxDeepConcurrent}.`,
        )
      }
      if (recommendedCategory === "critical" && critical >= options.maxCriticalConcurrent) {
        writeGatewayEventAudit(directory, {
          hook: "delegation-concurrency-guard",
          stage: "guard",
          reason_code: "delegation_concurrency_critical_blocked",
          session_id: sid,
          concurrent_critical: String(critical),
        })
        throw new Error(
          `Blocked delegation: critical concurrent delegations ${critical} reached maxCriticalConcurrent=${options.maxCriticalConcurrent}.`,
        )
      }

      activeByDelegation.set(key, {
        childRunId,
        subagentType,
        category: recommendedCategory,
        costTier,
        traceId,
        startedAt: now,
      })
      writeGatewayEventAudit(directory, {
        hook: "delegation-concurrency-guard",
        stage: "state",
        reason_code: "delegation_concurrency_reserved",
        session_id: sid,
        child_run_id: childRunId || undefined,
        trace_id: traceId || undefined,
        subagent_type: subagentType || undefined,
        category: recommendedCategory,
        cost_tier: costTier,
      })
    },
  }
}
