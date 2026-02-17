import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"

// Declares minimal session message token shape for context monitor.
interface AssistantMessageInfo {
  role?: string
  providerID?: string
  tokens?: {
    input?: number
    cache?: { read?: number }
  }
}

// Declares minimal message wrapper shape from session API.
interface MessageWrapper {
  info?: AssistantMessageInfo
}

// Declares minimal session client required by context monitor.
interface GatewayClient {
  session?: {
    messages(args: {
      path: { id: string }
      query?: { directory?: string }
    }): Promise<{ data?: MessageWrapper[] }>
  }
}

// Declares post-tool payload shape for context monitor.
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

// Declares event payload shape for session cleanup.
interface EventPayload {
  directory?: string
  properties?: {
    info?: { id?: string }
  }
}

interface SessionReminderState {
  toolCalls: number
  lastWarnedAtToolCall: number
  lastWarnedTokens: number
  lastSeenAtMs: number
}

// Resolves effective session id from tool after payload.
function resolveSessionId(payload: ToolAfterPayload): string {
  const candidates = [payload.input?.sessionID, payload.input?.sessionId]
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) {
      return value.trim()
    }
  }
  return ""
}

// Resolves Anthropic actual limit from environment toggles.
function anthropicActualLimit(): number {
  return process.env.ANTHROPIC_1M_CONTEXT === "true" || process.env.VERTEX_ANTHROPIC_1M_CONTEXT === "true"
    ? 1_000_000
    : 200_000
}

// Builds warning suffix with context usage details.
function warningSuffix(totalInputTokens: number, contextLimit: number): string {
  const safeLimit = contextLimit > 0 ? contextLimit : 1
  const displayUsagePercentage = totalInputTokens / safeLimit
  const usedPct = (displayUsagePercentage * 100).toFixed(1)
  const remainingPct = (Math.max(0, 1 - displayUsagePercentage) * 100).toFixed(1)
  const usedTokens = totalInputTokens.toLocaleString()
  const limitTokens = safeLimit.toLocaleString()
  return `[Context Status: ${usedPct}% used (${usedTokens}/${limitTokens} tokens), ${remainingPct}% remaining]`
}

const CONTEXT_GUARD_PREFIX = "󰚩 Context Guard:"

function guardPrefix(mode: "nerd" | "plain" | "both"): string {
  if (mode === "plain") {
    return "[Context Guard]:"
  }
  if (mode === "both") {
    return "󰚩 Context Guard [Context Guard]:"
  }
  return CONTEXT_GUARD_PREFIX
}

function pruneSessionStates(
  states: Map<string, SessionReminderState>,
  maxEntries: number,
): void {
  if (states.size <= maxEntries) {
    return
  }
  let oldestKey = ""
  let oldestAt = Number.POSITIVE_INFINITY
  for (const [key, state] of states.entries()) {
    if (state.lastSeenAtMs < oldestAt) {
      oldestAt = state.lastSeenAtMs
      oldestKey = key
    }
  }
  if (oldestKey) {
    states.delete(oldestKey)
  }
}

// Creates context monitor hook that appends usage warnings once per session.
export function createContextWindowMonitorHook(options: {
  directory: string
  client?: GatewayClient
  enabled: boolean
  warningThreshold: number
  reminderCooldownToolCalls: number
  minTokenDeltaForReminder: number
  guardMarkerMode: "nerd" | "plain" | "both"
  guardVerbosity: "minimal" | "normal" | "debug"
  maxSessionStateEntries: number
}): GatewayHook {
  const sessionStates = new Map<string, SessionReminderState>()
  return {
    id: "context-window-monitor",
    priority: 260,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }
      if (type === "session.deleted") {
        const eventPayload = (payload ?? {}) as EventPayload
        const sessionId = eventPayload.properties?.info?.id
        if (typeof sessionId === "string" && sessionId.trim()) {
          sessionStates.delete(sessionId.trim())
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
        writeGatewayEventAudit(directory, {
          hook: "context-window-monitor",
          stage: "skip",
          reason_code: "missing_session_id",
        })
        return
      }
      const priorState = sessionStates.get(sessionId) ?? {
        toolCalls: 0,
        lastWarnedAtToolCall: 0,
        lastWarnedTokens: 0,
        lastSeenAtMs: Date.now(),
      }
      const nextState: SessionReminderState = {
        ...priorState,
        toolCalls: priorState.toolCalls + 1,
        lastSeenAtMs: Date.now(),
      }
      sessionStates.set(sessionId, nextState)
      pruneSessionStates(sessionStates, options.maxSessionStateEntries)
      if (typeof eventPayload.output?.output !== "string") {
        writeGatewayEventAudit(directory, {
          hook: "context-window-monitor",
          stage: "skip",
          reason_code: "output_not_text",
          session_id: sessionId,
        })
        return
      }
      const client = options.client?.session
      if (!client) {
        writeGatewayEventAudit(directory, {
          hook: "context-window-monitor",
          stage: "skip",
          reason_code: "session_client_unavailable",
          session_id: sessionId,
        })
        return
      }
      try {
        const response = await client.messages({
          path: { id: sessionId },
          query: { directory },
        })
        const messages = Array.isArray(response.data) ? response.data : []
        const assistants = messages
          .filter((item) => item.info?.role === "assistant")
          .map((item) => item.info)
        const last = assistants[assistants.length - 1]
        if (!last || last.providerID !== "anthropic") {
          writeGatewayEventAudit(directory, {
            hook: "context-window-monitor",
            stage: "skip",
            reason_code: "provider_not_anthropic",
            session_id: sessionId,
          })
          return
        }
        const totalInputTokens = (last.tokens?.input ?? 0) + (last.tokens?.cache?.read ?? 0)
        const actualLimit = anthropicActualLimit()
        const actualUsage = totalInputTokens / actualLimit
        if (actualUsage < options.warningThreshold) {
          writeGatewayEventAudit(directory, {
            hook: "context-window-monitor",
            stage: "skip",
            reason_code: "below_warning_threshold",
            session_id: sessionId,
          })
          return
        }
        const hasPriorReminder = nextState.lastWarnedAtToolCall > 0
        if (hasPriorReminder) {
          const cooldownElapsed =
            nextState.toolCalls - nextState.lastWarnedAtToolCall >= options.reminderCooldownToolCalls
          const tokenDeltaEnough =
            totalInputTokens - nextState.lastWarnedTokens >= options.minTokenDeltaForReminder
          if (!cooldownElapsed) {
            writeGatewayEventAudit(directory, {
              hook: "context-window-monitor",
              stage: "skip",
              reason_code: "reminder_cooldown_not_elapsed",
              session_id: sessionId,
            })
            return
          }
          if (!tokenDeltaEnough) {
            writeGatewayEventAudit(directory, {
              hook: "context-window-monitor",
              stage: "skip",
              reason_code: "reminder_token_delta_too_small",
              session_id: sessionId,
            })
            return
          }
        }
        sessionStates.set(sessionId, {
          ...nextState,
          lastWarnedAtToolCall: nextState.toolCalls,
          lastWarnedTokens: totalInputTokens,
        })
        const prefix = guardPrefix(options.guardMarkerMode)
        if (options.guardVerbosity === "minimal") {
          eventPayload.output.output = `${eventPayload.output.output}\n\n${prefix} High context usage detected.`
        } else if (options.guardVerbosity === "debug") {
          eventPayload.output.output = `${eventPayload.output.output}\n\n${prefix} High context usage detected; threshold ${(options.warningThreshold * 100).toFixed(1)}% crossed.\n${warningSuffix(totalInputTokens, actualLimit)}\n[cooldown=${options.reminderCooldownToolCalls} calls, min_delta=${options.minTokenDeltaForReminder} tokens]`
        } else {
          eventPayload.output.output = `${eventPayload.output.output}\n\n${prefix} High context usage detected; keep responses focused.\n${warningSuffix(totalInputTokens, actualLimit)}`
        }
        writeGatewayEventAudit(directory, {
          hook: "context-window-monitor",
          stage: "state",
          reason_code: "context_warning_appended",
          session_id: sessionId,
        })
      } catch {
        writeGatewayEventAudit(directory, {
          hook: "context-window-monitor",
          stage: "skip",
          reason_code: "session_messages_failed",
          session_id: sessionId,
        })
      }
    },
  }
}
