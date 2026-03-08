import { createHash } from "node:crypto"

import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import { loadAgentMetadata } from "../shared/agent-metadata.js"
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
      category?: string
    }
    metadata?: unknown
    output?: unknown
  }
  directory?: string
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

interface ActiveDelegation {
  childRunId?: string
  subagentType: string
  category: string
  costTier: string
  traceId: string
  startedAt: number
}

function matchingSessionDelegationKeys(
  activeByDelegation: Map<string, ActiveDelegation>,
  sid: string,
  subagentType: string,
): string[] {
  const matches: string[] = []
  for (const [key, value] of activeByDelegation.entries()) {
    if ((key === sid || key.startsWith(`${sid}:`)) && value.subagentType === subagentType) {
      matches.push(key)
    }
  }
  return matches
}

function nowMs(): number {
  return Date.now()
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

function delegationKey(sid: string, childRunId: string, traceId: string, args?: DelegationArgs): string {
  if (childRunId) {
    return `${sid}:${childRunId}`
  }
  return traceId ? `${sid}:${traceId}` : fallbackDelegationKey(sid, args)
}

function matchingSessionTraceDelegationKeys(
  activeByDelegation: Map<string, ActiveDelegation>,
  sid: string,
  traceId: string,
): string[] {
  const matches: string[] = []
  for (const [key, value] of activeByDelegation.entries()) {
    if ((key === sid || key.startsWith(`${sid}:`)) && value.traceId === traceId) {
      matches.push(key)
    }
  }
  return matches
}

function sessionDelegationKeys(
  activeByDelegation: Map<string, ActiveDelegation>,
  sid: string,
): string[] {
  const matches: string[] = []
  for (const key of activeByDelegation.keys()) {
    if (key === sid || key.startsWith(`${sid}:`)) {
      matches.push(key)
    }
  }
  return matches
}

function sessionId(payload: {
  input?: { sessionID?: string; sessionId?: string }
  properties?: { info?: { id?: string } }
}): string {
  return String(payload.input?.sessionID ?? payload.input?.sessionId ?? payload.properties?.info?.id ?? "").trim()
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

  function pruneStaleDelegations(directory: string, referenceTime: number): void {
    for (const [key, active] of activeByDelegation.entries()) {
      if (referenceTime - active.startedAt < options.staleReservationMs) {
        continue
      }
      activeByDelegation.delete(key)
      const [sessionKey, traceKey] = key.split(":", 2)
      writeGatewayEventAudit(directory, {
        hook: "delegation-concurrency-guard",
        stage: "state",
        reason_code: "delegation_concurrency_stale_pruned",
        session_id: sessionKey,
        trace_id: active.traceId || (traceKey && !traceKey.startsWith("fp") ? traceKey : undefined),
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
        const sid = sessionId(eventPayload)
        if (sid) {
          const childRunId = extractDelegationChildRunId(eventPayload.output?.metadata)
          const traceId = extractDelegationTraceId(eventPayload.output?.args, eventPayload.output?.metadata)
          if (childRunId || traceId) {
            const key = delegationKey(sid, childRunId, traceId)
            if (activeByDelegation.delete(key)) {
              return
            }
            if (traceId) {
              const traceMatches = matchingSessionTraceDelegationKeys(activeByDelegation, sid, traceId)
              if (traceMatches.length === 1) {
                activeByDelegation.delete(traceMatches[0])
                return
              }
            }
          } else {
            const outputText = typeof eventPayload.output?.output === "string" ? eventPayload.output.output : ""
            const outputSubagentType =
              extractDelegationSubagentType(eventPayload.output?.args, eventPayload.output?.metadata) ||
              extractDelegationSubagentTypeFromOutput(outputText)
            const fallbackKeys = outputSubagentType
              ? matchingSessionDelegationKeys(activeByDelegation, sid, outputSubagentType)
              : sessionDelegationKeys(activeByDelegation, sid)
            if (fallbackKeys.length === 1) {
              activeByDelegation.delete(fallbackKeys[0])
            } else if (fallbackKeys.length > 1) {
              writeGatewayEventAudit(options.directory, {
                hook: "delegation-concurrency-guard",
                stage: "skip",
                reason_code: "delegation_concurrency_after_ambiguous_skip",
                session_id: sid,
                concurrent_total: String(fallbackKeys.length),
              })
            }
          }
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
      const key = delegationKey(sid, childRunId, traceId, args)
      if (!subagentType && !category) {
        return
      }
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
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
        childRunId: childRunId || undefined,
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
