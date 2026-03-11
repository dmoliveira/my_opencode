import { createHash } from "node:crypto"

import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import { loadAgentMetadata } from "../shared/agent-metadata.js"
import {
  clearDelegationChildSessionLink,
  getDelegationChildSessionLink,
  registerDelegationChildSession,
} from "../shared/delegation-child-session.js"
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

interface SessionInfoPayload {
  properties?: {
    info?: {
      id?: string
      parentID?: string
      title?: string
    }
  }
}

interface SessionIdlePayload {
  properties?: {
    sessionID?: string
    sessionId?: string
    info?: { id?: string }
  }
}

interface MessageUpdatedPayload {
  directory?: string
  properties?: {
    info?: {
      role?: string
      sessionID?: string
      sessionId?: string
      error?: unknown
      time?: {
        completed?: number
      }
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
  properties?: { sessionID?: string; sessionId?: string; info?: { id?: string } }
}): string {
  return String(
    payload.input?.sessionID ??
      payload.input?.sessionId ??
      payload.properties?.sessionID ??
      payload.properties?.sessionId ??
      payload.properties?.info?.id ??
      "",
  ).trim()
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

  function releaseLinkedDelegation(args: {
    parentSessionId: string
    childRunId?: string
    traceId?: string
    subagentType?: string
    directory: string
    reasonCode: string
  }): boolean {
    const fallbackEventPayload: ToolPayload = {
      input: { tool: "task", sessionID: args.parentSessionId },
      output: {
        args: {
          ...(args.traceId ? { prompt: `[DELEGATION TRACE ${args.traceId}]` } : {}),
        },
        metadata: {
          gateway: {
            delegation: {
              ...(args.childRunId ? { childRunId: args.childRunId } : {}),
              ...(args.traceId ? { traceId: args.traceId } : {}),
              ...(args.subagentType ? { subagentType: args.subagentType } : {}),
            },
          },
        },
      },
      directory: args.directory,
    }
    const releaseMode = releaseDelegationReservation(fallbackEventPayload, args.directory)
    if (releaseMode === "none" || releaseMode === "ambiguous_skip") {
      return false
    }
    writeGatewayEventAudit(args.directory, {
      hook: "delegation-concurrency-guard",
      stage: "state",
      reason_code: args.reasonCode,
      session_id: args.parentSessionId,
      trace_id: args.traceId || undefined,
    })
    return true
  }

  function releaseDelegationReservation(eventPayload: ToolPayload, directory: string): "none" | "direct" | "trace_fallback" | "subagent_fallback" | "ambiguous_skip" {
    const sid = sessionId(eventPayload)
    if (!sid) {
      return "none"
    }
    const childRunId = extractDelegationChildRunId(eventPayload.output?.metadata)
    const traceId = extractDelegationTraceId(eventPayload.output?.args, eventPayload.output?.metadata)
    if (childRunId || traceId) {
      const key = delegationKey(sid, childRunId, traceId)
      if (activeByDelegation.delete(key)) {
        return "direct"
      }
      if (traceId) {
        const traceMatches = matchingSessionTraceDelegationKeys(activeByDelegation, sid, traceId)
        if (traceMatches.length === 1) {
          activeByDelegation.delete(traceMatches[0])
          writeGatewayEventAudit(directory, {
            hook: "delegation-concurrency-guard",
            stage: "state",
            reason_code: "delegation_concurrency_trace_fallback_matched",
            session_id: sid,
            trace_id: traceId || undefined,
          })
          return "trace_fallback"
        }
      }
    }
    const outputText = typeof eventPayload.output?.output === "string" ? eventPayload.output.output : ""
    const outputSubagentType =
      extractDelegationSubagentType(eventPayload.output?.args, eventPayload.output?.metadata) ||
      extractDelegationSubagentTypeFromOutput(outputText)
    const fallbackKeys = outputSubagentType
      ? matchingSessionDelegationKeys(activeByDelegation, sid, outputSubagentType)
      : sessionDelegationKeys(activeByDelegation, sid)
    if (fallbackKeys.length === 1) {
      activeByDelegation.delete(fallbackKeys[0])
      writeGatewayEventAudit(directory, {
        hook: "delegation-concurrency-guard",
        stage: "state",
        reason_code: "delegation_concurrency_subagent_fallback_matched",
        session_id: sid,
        subagent_type: outputSubagentType || undefined,
      })
      return "subagent_fallback"
    }
    if (fallbackKeys.length > 1) {
      for (const key of fallbackKeys) {
        activeByDelegation.delete(key)
      }
      writeGatewayEventAudit(directory, {
        hook: "delegation-concurrency-guard",
        stage: "state",
        reason_code: "delegation_concurrency_after_ambiguous_forced_release",
        session_id: sid,
        concurrent_total: String(fallbackKeys.length),
      })
    }
    return fallbackKeys.length > 1 ? "ambiguous_skip" : "none"
  }

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
      if (type === "session.created" || type === "session.updated") {
        registerDelegationChildSession((payload ?? {}) as SessionInfoPayload)
        return
      }
      if (type === "session.idle") {
        const childSessionId = sessionId((payload ?? {}) as SessionIdlePayload)
        const link = getDelegationChildSessionLink(childSessionId)
        if (!link) {
          return
        }
        releaseLinkedDelegation({
          parentSessionId: link.parentSessionId,
          childRunId: link.childRunId,
          traceId: link.traceId,
          subagentType: link.subagentType,
          directory: options.directory,
          reasonCode: "delegation_concurrency_child_idle_released",
        })
        return
      }
      if (type === "message.updated") {
        const eventPayload = (payload ?? {}) as MessageUpdatedPayload
        const info = eventPayload.properties?.info
        if (String(info?.role ?? "").toLowerCase().trim() !== "assistant") {
          return
        }
        const childSessionId = String(info?.sessionID ?? info?.sessionId ?? "").trim()
        const link = getDelegationChildSessionLink(childSessionId)
        if (!link) {
          return
        }
        const completed = Number.isFinite(Number(info?.time?.completed ?? NaN))
        const failed = info?.error !== undefined && info?.error !== null
        if (!completed && !failed) {
          return
        }
        releaseLinkedDelegation({
          parentSessionId: link.parentSessionId,
          childRunId: link.childRunId,
          traceId: link.traceId,
          subagentType: link.subagentType,
          directory:
            typeof eventPayload.directory === "string" && eventPayload.directory.trim()
              ? eventPayload.directory
              : options.directory,
          reasonCode: failed
            ? "delegation_concurrency_child_message_failed_released"
            : "delegation_concurrency_child_message_completed_released",
        })
        return
      }
      if (type === "session.deleted") {
        const sid = sessionId((payload ?? {}) as SessionDeletedPayload)
        if (sid) {
          const childLink = clearDelegationChildSessionLink(sid)
          if (childLink) {
              releaseLinkedDelegation({
                parentSessionId: childLink.parentSessionId,
                childRunId: childLink.childRunId,
                traceId: childLink.traceId,
                subagentType: childLink.subagentType,
                directory: options.directory,
                reasonCode: "delegation_concurrency_child_deleted_released",
              })
          }
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
        if (releaseMode !== "none" && releaseMode !== "ambiguous_skip") {
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
      const key = delegationKey(sid, childRunId, traceId, args)
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
