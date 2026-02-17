import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
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
    for (let idx = messages.length - 1; idx >= 0; idx -= 1) {
      const sessionIdCandidates = [messages[idx]?.info?.sessionID, messages[idx]?.info?.sessionId]
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

// Creates context injector that injects pending context on chat and transform hooks.
export function createContextInjectorHook(options: {
  directory: string
  enabled: boolean
  collector: ContextCollector
}): GatewayHook {
  let lastKnownSessionId = ""
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
          if (lastKnownSessionId === normalized) {
            lastKnownSessionId = ""
          }
        }
        return
      }

      if (type === "chat.message") {
        const eventPayload = (payload ?? {}) as ChatPayload
        const directory =
          typeof eventPayload.directory === "string" && eventPayload.directory.trim()
            ? eventPayload.directory
            : options.directory
        const sessionId = resolveSessionId(eventPayload, lastKnownSessionId)
        if (sessionId) {
          lastKnownSessionId = sessionId
        }
        const parts = eventPayload.output?.parts
        if (!sessionId || !Array.isArray(parts) || !options.collector.hasPending(sessionId)) {
          return
        }
        const pending = options.collector.consume(sessionId)
        if (!pending.hasContent) {
          return
        }
        if (!injectIntoParts(parts, pending.merged)) {
          options.collector.register(sessionId, {
            source: "context-injector-requeue",
            id: "chat-message-fallback",
            content: pending.merged,
            priority: "high",
          })
          return
        }
        writeGatewayEventAudit(directory, {
          hook: "context-injector",
          stage: "inject",
          reason_code: "pending_context_injected_chat_message",
          session_id: sessionId,
          context_length: pending.merged.length,
        })
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
      const sessionId = resolveSessionId(eventPayload, lastKnownSessionId)
      if (sessionId) {
        lastKnownSessionId = sessionId
      }
      const messages = eventPayload.output?.messages
      if (!sessionId || !Array.isArray(messages) || !options.collector.hasPending(sessionId)) {
        return
      }
      let lastUserIndex = -1
      for (let idx = messages.length - 1; idx >= 0; idx -= 1) {
        if (messages[idx]?.info?.role === "user") {
          lastUserIndex = idx
          break
        }
      }
      if (lastUserIndex < 0) {
        return
      }
      const parts = messages[lastUserIndex].parts
      if (!Array.isArray(parts)) {
        return
      }
      const pending = options.collector.consume(sessionId)
      if (!pending.hasContent) {
        return
      }
      const synthetic: TextPart & { synthetic: boolean } = {
        type: "text",
        text: pending.merged,
        synthetic: true,
      }
      parts.unshift(synthetic)
      writeGatewayEventAudit(directory, {
        hook: "context-injector",
        stage: "inject",
        reason_code: "pending_context_injected_messages_transform",
        session_id: sessionId,
        context_length: pending.merged.length,
      })
    },
  }
}
