import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import { REASON_CODES } from "../../bridge/reason-codes.js"
import type { GatewayHook } from "../registry.js"
import { DEFAULT_INJECTED_TEXT_MAX_CHARS, truncateInjectedText } from "../shared/injected-text-truncator.js"
import type { ContextCollector } from "./collector.js"

interface TextPart {
  type?: string
  text?: string
}

interface ChatPayload {
  properties?: {
    sessionID?: string
    sessionId?: string
    info?: { id?: string }
  }
  output?: {
    parts?: TextPart[]
  }
  directory?: string
}

interface TransformPayload {
  input?: {
    sessionID?: string
    sessionId?: string
  }
  output?: {
    messages?: Array<{
      info?: { role?: string; id?: string; sessionID?: string; sessionId?: string }
      parts?: TextPart[]
    }>
  }
  directory?: string
}

interface EventPayload {
  properties?: {
    info?: { id?: string }
  }
}
const TRANSFORM_MESSAGE_LOOKBACK_LIMIT = 64

function recentMessages<T>(messages: T[], limit = TRANSFORM_MESSAGE_LOOKBACK_LIMIT): T[] {
  if (!Array.isArray(messages) || messages.length <= limit) {
    return messages
  }
  return messages.slice(messages.length - limit)
}

// Resolves session id from known payload variants.
function resolveSessionId(payload: ChatPayload | TransformPayload, fallbackSessionId = ""): string {
  const record = payload as {
    input?: { sessionID?: string; sessionId?: string }
    properties?: { sessionID?: string; sessionId?: string; info?: { id?: string } }
  }
  const candidates = [
    record.input?.sessionID,
    record.input?.sessionId,
    record.properties?.sessionID,
    record.properties?.sessionId,
    record.properties?.info?.id,
  ]
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) {
      return value.trim()
    }
  }
  const transformPayload = payload as TransformPayload
  const messages = transformPayload.output?.messages
  if (Array.isArray(messages)) {
    for (const message of [...recentMessages(messages)].reverse()) {
      const sessionIdCandidates = [message?.info?.sessionID, message?.info?.sessionId]
      for (const value of sessionIdCandidates) {
        if (typeof value === "string" && value.trim()) {
          return value.trim()
        }
      }
    }
  }
  return fallbackSessionId.trim()
}

// Injects pending context into mutable output parts.
function injectIntoParts(parts: TextPart[], merged: string): boolean {
  const textPart = parts.find((part) => part.type === "text" && typeof part.text === "string")
  if (!textPart || typeof textPart.text !== "string") {
    return false
  }
  textPart.text = `${merged}\n\n---\n\n${textPart.text}`
  return true
}

function estimateChangedChars(previous: string, next: string): number {
  if (previous === next) {
    return 0
  }
  let start = 0
  while (start < previous.length && start < next.length && previous[start] === next[start]) {
    start += 1
  }
  let endPrevious = previous.length - 1
  let endNext = next.length - 1
  while (endPrevious >= start && endNext >= start && previous[endPrevious] === next[endNext]) {
    endPrevious -= 1
    endNext -= 1
  }
  const changedPrevious = Math.max(0, endPrevious - start + 1)
  const changedNext = Math.max(0, endNext - start + 1)
  return Math.max(changedPrevious, changedNext, Math.abs(previous.length - next.length))
}

// Creates context injector that injects pending context on chat and transform hooks.
export function createContextInjectorHook(options: {
  directory: string
  enabled: boolean
  collector: ContextCollector
  maxChars?: number
  dedupeEnabled?: boolean
  minDeltaChars?: number
}): GatewayHook {
  const lastInjectedBySession = new Map<string, string>()
  const maxChars =
    typeof options.maxChars === "number" && Number.isFinite(options.maxChars) && options.maxChars > 0
      ? Math.floor(options.maxChars)
      : DEFAULT_INJECTED_TEXT_MAX_CHARS
  const dedupeEnabled = options.dedupeEnabled !== false
  const minDeltaChars =
    typeof options.minDeltaChars === "number" && Number.isFinite(options.minDeltaChars)
      ? Math.max(0, Math.floor(options.minDeltaChars))
      : 0
  return {
    id: "context-injector",
    priority: 295,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }
      if (type === "session.deleted") {
        const eventPayload = (payload ?? {}) as EventPayload
        const sessionId = eventPayload.properties?.info?.id
        if (typeof sessionId === "string" && sessionId.trim()) {
          const normalized = sessionId.trim()
          options.collector.clear(normalized)
          lastInjectedBySession.delete(normalized)
        }
        return
      }

      if (type === "chat.message") {
        const eventPayload = (payload ?? {}) as ChatPayload
        const directory =
          typeof eventPayload.directory === "string" && eventPayload.directory.trim()
            ? eventPayload.directory
            : options.directory
        const sessionId = resolveSessionId(eventPayload)
        const parts = eventPayload.output?.parts
        if (!sessionId || !Array.isArray(parts) || !options.collector.hasPending(sessionId)) {
          return
        }
        const pending = options.collector.consume(sessionId)
        if (!pending.hasContent) {
          return
        }
        const truncated = truncateInjectedText(pending.merged, maxChars)
        if (dedupeEnabled) {
          const previous = lastInjectedBySession.get(sessionId) ?? ""
          if (previous) {
            const deltaChars = estimateChangedChars(previous, truncated.text)
            if (deltaChars === 0) {
              writeGatewayEventAudit(directory, {
                hook: "context-injector",
                stage: "inject",
                reason_code: "context_inject_chat_skipped_duplicate",
                session_id: sessionId,
                context_length: truncated.text.length,
              })
              return
            }
            if (minDeltaChars > 0 && deltaChars < minDeltaChars) {
              writeGatewayEventAudit(directory, {
                hook: "context-injector",
                stage: "inject",
                reason_code: "context_inject_chat_skipped_small_delta",
                session_id: sessionId,
                context_length: truncated.text.length,
                delta_chars: deltaChars,
                min_delta_chars: minDeltaChars,
              })
              return
            }
          }
        }
        if (truncated.truncated) {
          writeGatewayEventAudit(directory, {
            hook: "context-injector",
            stage: "inject",
            reason_code: REASON_CODES.CONTEXT_TRUNCATED_CHAT,
            session_id: sessionId,
            context_length_before: truncated.originalLength,
            context_length_after: truncated.text.length,
          })
        }
        if (!injectIntoParts(parts, truncated.text)) {
          writeGatewayEventAudit(directory, {
            hook: "context-injector",
            stage: "inject",
            reason_code: REASON_CODES.CONTEXT_REQUEUED_NO_TEXT_PART,
            session_id: sessionId,
            context_length: truncated.text.length,
          })
          options.collector.register(sessionId, {
            source: "context-injector-requeue",
            id: "chat-message-fallback",
            content: truncated.text,
            priority: "high",
          })
          return
        }
        writeGatewayEventAudit(directory, {
          hook: "context-injector",
          stage: "inject",
          reason_code: REASON_CODES.CONTEXT_INJECT_CHAT,
          session_id: sessionId,
          context_length: truncated.text.length,
        })
        lastInjectedBySession.set(sessionId, truncated.text)
        return
      }

      if (type !== "experimental.chat.messages.transform") {
        return
      }

      const eventPayload = (payload ?? {}) as TransformPayload
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = resolveSessionId(eventPayload)
      const messages = eventPayload.output?.messages
      if (!sessionId || !Array.isArray(messages) || !options.collector.hasPending(sessionId)) {
        return
      }
      const recent = recentMessages(messages)
      let lastUserIndex = -1
      for (let idx = recent.length - 1; idx >= 0; idx -= 1) {
        if (recent[idx]?.info?.role === "user") {
          lastUserIndex = messages.length - recent.length + idx
          break
        }
      }
      if (lastUserIndex < 0) {
        if (options.collector.hasPending(sessionId)) {
          writeGatewayEventAudit(directory, {
            hook: "context-injector",
            stage: "inject",
            reason_code: REASON_CODES.CONTEXT_TRANSFORM_NO_USER_MESSAGE,
            session_id: sessionId,
          })
        }
        return
      }
      const parts = messages[lastUserIndex].parts
      if (!Array.isArray(parts)) {
        if (options.collector.hasPending(sessionId)) {
          writeGatewayEventAudit(directory, {
            hook: "context-injector",
            stage: "inject",
            reason_code: REASON_CODES.CONTEXT_TRANSFORM_NO_PARTS,
            session_id: sessionId,
          })
        }
        return
      }
      const pending = options.collector.consume(sessionId)
      if (!pending.hasContent) {
        return
      }
      const truncated = truncateInjectedText(pending.merged, maxChars)
      if (dedupeEnabled) {
        const previous = lastInjectedBySession.get(sessionId) ?? ""
        if (previous) {
          const deltaChars = estimateChangedChars(previous, truncated.text)
          if (deltaChars === 0) {
            writeGatewayEventAudit(directory, {
              hook: "context-injector",
              stage: "inject",
              reason_code: "context_inject_transform_skipped_duplicate",
              session_id: sessionId,
              context_length: truncated.text.length,
            })
            return
          }
          if (minDeltaChars > 0 && deltaChars < minDeltaChars) {
            writeGatewayEventAudit(directory, {
              hook: "context-injector",
              stage: "inject",
              reason_code: "context_inject_transform_skipped_small_delta",
              session_id: sessionId,
              context_length: truncated.text.length,
              delta_chars: deltaChars,
              min_delta_chars: minDeltaChars,
            })
            return
          }
        }
      }
      if (truncated.truncated) {
        writeGatewayEventAudit(directory, {
          hook: "context-injector",
          stage: "inject",
          reason_code: REASON_CODES.CONTEXT_TRUNCATED_TRANSFORM,
          session_id: sessionId,
          context_length_before: truncated.originalLength,
          context_length_after: truncated.text.length,
        })
      }
      const synthetic: TextPart & { synthetic: boolean } = {
        type: "text",
        text: truncated.text,
        synthetic: true,
      }
      parts.unshift(synthetic)
      writeGatewayEventAudit(directory, {
        hook: "context-injector",
        stage: "inject",
        reason_code: REASON_CODES.CONTEXT_INJECT_TRANSFORM,
        session_id: sessionId,
        context_length: truncated.text.length,
      })
      lastInjectedBySession.set(sessionId, truncated.text)
    },
  }
}
