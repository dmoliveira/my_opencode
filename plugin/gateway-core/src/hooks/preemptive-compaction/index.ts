import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"

const DEFAULT_ACTUAL_LIMIT = 200_000

// Declares assistant message token shape for compaction trigger.
interface AssistantMessageInfo {
  role?: string
  providerID?: string
  modelID?: string
  tokens?: {
    input?: number
    cache?: { read?: number }
  }
}

// Declares session message wrapper shape for compaction trigger.
interface MessageWrapper {
  info?: AssistantMessageInfo
}

// Declares minimal session API used by preemptive compaction hook.
interface GatewayClient {
  session?: {
    messages(args: {
      path: { id: string }
      query?: { directory?: string }
    }): Promise<{ data?: MessageWrapper[] }>
    summarize(args: {
      path: { id: string }
      body: { providerID: string; modelID: string; auto: boolean }
      query?: { directory?: string }
    }): Promise<void>
  }
}

// Declares post-tool payload shape for compaction trigger.
interface ToolAfterPayload {
  input?: {
    sessionID?: string
    sessionId?: string
  }
  output?: {
    output?: unknown
  }
  directory?: string
}

// Declares session cleanup payload for compaction memory.
interface EventPayload {
  properties?: {
    info?: { id?: string }
  }
}

interface SessionCompactionState {
  toolCalls: number
  lastCompactedAtToolCall: number
  lastCompactedTokens: number
}

const CONTEXT_GUARD_PREFIX = "󰚩 Context Guard:"

// Resolves effective session id across payload variants.
function resolveSessionId(payload: ToolAfterPayload): string {
  const candidates = [payload.input?.sessionID, payload.input?.sessionId]
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) {
      return value.trim()
    }
  }
  return ""
}

// Resolves Anthropic actual token limit from runtime environment flags.
function anthropicActualLimit(): number {
  return process.env.ANTHROPIC_1M_CONTEXT === "true" || process.env.VERTEX_ANTHROPIC_1M_CONTEXT === "true"
    ? 1_000_000
    : DEFAULT_ACTUAL_LIMIT
}

// Creates preemptive compaction hook for high context pressure sessions.
export function createPreemptiveCompactionHook(options: {
  directory: string
  client?: GatewayClient
  enabled: boolean
  warningThreshold: number
  compactionCooldownToolCalls: number
  minTokenDeltaForCompaction: number
}): GatewayHook {
  const compactionInProgress = new Set<string>()
  const sessionStates = new Map<string, SessionCompactionState>()
  return {
    id: "preemptive-compaction",
    priority: 270,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }
      if (type === "session.deleted") {
        const eventPayload = (payload ?? {}) as EventPayload
        const sessionId = eventPayload.properties?.info?.id
        if (typeof sessionId === "string" && sessionId.trim()) {
          const resolvedSessionId = sessionId.trim()
          compactionInProgress.delete(resolvedSessionId)
          sessionStates.delete(resolvedSessionId)
        }
        return
      }
      if (type !== "tool.execute.after") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolAfterPayload
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = resolveSessionId(eventPayload)
      if (!sessionId) {
        return
      }
      const priorState = sessionStates.get(sessionId) ?? {
        toolCalls: 0,
        lastCompactedAtToolCall: 0,
        lastCompactedTokens: 0,
      }
      const nextState: SessionCompactionState = {
        ...priorState,
        toolCalls: priorState.toolCalls + 1,
      }
      sessionStates.set(sessionId, nextState)
      if (compactionInProgress.has(sessionId)) {
        return
      }
      const client = options.client?.session
      if (!client) {
        return
      }
      try {
        const response = await client.messages({ path: { id: sessionId }, query: { directory } })
        const messages = Array.isArray(response.data) ? response.data : []
        const assistants = messages
          .filter((item) => item.info?.role === "assistant")
          .map((item) => item.info)
        const last = assistants[assistants.length - 1]
        if (!last) {
          return
        }
        const actualLimit = last.providerID === "anthropic" ? anthropicActualLimit() : DEFAULT_ACTUAL_LIMIT
        const totalInputTokens = (last.tokens?.input ?? 0) + (last.tokens?.cache?.read ?? 0)
        const usageRatio = totalInputTokens / actualLimit
        if (usageRatio < options.warningThreshold) {
          return
        }
        const hasPriorCompaction = nextState.lastCompactedAtToolCall > 0
        if (hasPriorCompaction) {
          const cooldownElapsed =
            nextState.toolCalls - nextState.lastCompactedAtToolCall >= options.compactionCooldownToolCalls
          const tokenDeltaEnough =
            totalInputTokens - nextState.lastCompactedTokens >= options.minTokenDeltaForCompaction
          if (!cooldownElapsed) {
            writeGatewayEventAudit(directory, {
              hook: "preemptive-compaction",
              stage: "skip",
              reason_code: "compaction_cooldown_not_elapsed",
              session_id: sessionId,
            })
            return
          }
          if (!tokenDeltaEnough) {
            writeGatewayEventAudit(directory, {
              hook: "preemptive-compaction",
              stage: "skip",
              reason_code: "compaction_token_delta_too_small",
              session_id: sessionId,
            })
            return
          }
        }
        const providerID = typeof last.providerID === "string" ? last.providerID : ""
        const modelID = typeof last.modelID === "string" ? last.modelID : ""
        if (!providerID || !modelID) {
          return
        }
        compactionInProgress.add(sessionId)
        await client.summarize({
          path: { id: sessionId },
          body: { providerID, modelID, auto: true },
          query: { directory },
        })
        if (typeof eventPayload.output?.output === "string") {
          eventPayload.output.output = `${eventPayload.output.output}\n\n${CONTEXT_GUARD_PREFIX} Preemptive compaction triggered to reduce context pressure.`
        }
        sessionStates.set(sessionId, {
          ...nextState,
          lastCompactedAtToolCall: nextState.toolCalls,
          lastCompactedTokens: totalInputTokens,
        })
        writeGatewayEventAudit(directory, {
          hook: "preemptive-compaction",
          stage: "state",
          reason_code: "session_compacted_preemptively",
          session_id: sessionId,
        })
      } catch {
        writeGatewayEventAudit(directory, {
          hook: "preemptive-compaction",
          stage: "skip",
          reason_code: "session_compaction_failed",
          session_id: sessionId,
        })
      } finally {
        compactionInProgress.delete(sessionId)
      }
    },
  }
}
