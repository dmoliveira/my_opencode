import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import { injectHookMessage } from "../hook-message-injector/index.js"
import type { GatewayHook } from "../registry.js"

interface TextPart {
  type?: string
  text?: string
}

interface SessionClient {
  promptAsync(args: {
    path: { id: string }
    body: {
      parts: Array<{ type: string; text: string }>
      agent?: string
      model?: { providerID: string; modelID: string; variant?: string }
    }
    query?: { directory?: string }
  }): Promise<void>
  messages?(args: {
    path: { id: string }
    query?: { directory?: string }
  }): Promise<{ data?: Array<{ info?: { role?: string } }> }>
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
      info?: { role?: string; sessionID?: string; sessionId?: string }
      parts?: TextPart[]
    }>
  }
  directory?: string
}

interface SessionEventPayload {
  directory?: string
  properties?: {
    sessionID?: string
    sessionId?: string
    info?: { id?: string }
  }
  input?: {
    sessionID?: string
    sessionId?: string
  }
}

const SESSION_CONTEXT_MARKER = "[SESSION CONTEXT]"

function resolveSessionId(payload: ChatPayload | TransformPayload | SessionEventPayload): string {
  const typed = payload as {
    input?: { sessionID?: string; sessionId?: string }
    properties?: { sessionID?: string; sessionId?: string; info?: { id?: string } }
  }
  const candidates = [
    typed.input?.sessionID,
    typed.input?.sessionId,
    typed.properties?.sessionID,
    typed.properties?.sessionId,
    typed.properties?.info?.id,
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
      const messageCandidates = [messages[idx]?.info?.sessionID, messages[idx]?.info?.sessionId]
      for (const value of messageCandidates) {
        if (typeof value === "string" && value.trim()) {
          return value.trim()
        }
      }
    }
  }
  return ""
}

function buildSessionContext(sessionId: string): string {
  return [
    SESSION_CONTEXT_MARKER,
    `authoritative_runtime_session_id=${sessionId}`,
    "Use this exact session id for commits, logs, telemetry, and external tooling created during this runtime session.",
    "If the user asks for the current runtime session id, return this exact session id directly.",
    "Bash tool commands in this session expose OPENCODE_SESSION_ID when available.",
  ].join("\n")
}

function injectIntoParts(parts: TextPart[], content: string): boolean {
  const textPart = parts.find((part) => part.type === "text" && typeof part.text === "string")
  if (!textPart || typeof textPart.text !== "string") {
    return false
  }
  if (textPart.text.includes(SESSION_CONTEXT_MARKER)) {
    return false
  }
  textPart.text = `${content}\n\n---\n\n${textPart.text}`
  return true
}

export function createSessionRuntimeContextHook(options: {
  directory: string
  enabled: boolean
  client?: { session?: SessionClient }
}): GatewayHook {
  const injectedSessions = new Set<string>()

  return {
    id: "session-runtime-context",
    priority: 294,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }

      if (type === "session.deleted") {
        const sessionId = resolveSessionId((payload ?? {}) as SessionEventPayload)
        if (sessionId) {
          injectedSessions.delete(sessionId)
        }
        return
      }

      if (type === "session.compacted") {
        const eventPayload = (payload ?? {}) as SessionEventPayload
        const directory =
          typeof eventPayload.directory === "string" && eventPayload.directory.trim()
            ? eventPayload.directory
            : options.directory
        const sessionId = resolveSessionId(eventPayload)
        if (!sessionId) {
          return
        }
        injectedSessions.delete(sessionId)
        const client = options.client?.session
        if (!client) {
          return
        }
        const injected = await injectHookMessage({
          session: client,
          sessionId,
          content: buildSessionContext(sessionId),
          directory,
        })
        if (!injected) {
          writeGatewayEventAudit(directory, {
            hook: "session-runtime-context",
            stage: "inject",
            reason_code: "session_runtime_context_compaction_restore_failed",
            session_id: sessionId,
          })
          return
        }
        injectedSessions.add(sessionId)
        writeGatewayEventAudit(directory, {
          hook: "session-runtime-context",
          stage: "inject",
          reason_code: "session_runtime_context_compaction_restored",
          session_id: sessionId,
        })
        return
      }

      if (type === "chat.message") {
        const eventPayload = (payload ?? {}) as ChatPayload
        const sessionId = resolveSessionId(eventPayload)
        const directory =
          typeof eventPayload.directory === "string" && eventPayload.directory.trim()
            ? eventPayload.directory
            : options.directory
        const parts = eventPayload.output?.parts
        if (!sessionId || injectedSessions.has(sessionId) || !Array.isArray(parts)) {
          return
        }
        if (!injectIntoParts(parts, buildSessionContext(sessionId))) {
          return
        }
        injectedSessions.add(sessionId)
        writeGatewayEventAudit(directory, {
          hook: "session-runtime-context",
          stage: "inject",
          reason_code: "session_runtime_context_injected_chat",
          session_id: sessionId,
        })
        return
      }

      if (type !== "experimental.chat.messages.transform") {
        return
      }

      const eventPayload = (payload ?? {}) as TransformPayload
      const sessionId = resolveSessionId(eventPayload)
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      if (!sessionId || injectedSessions.has(sessionId)) {
        return
      }
      const messages = eventPayload.output?.messages
      if (!Array.isArray(messages)) {
        return
      }
      let target = -1
      for (let idx = messages.length - 1; idx >= 0; idx -= 1) {
        if (messages[idx]?.info?.role === "user") {
          target = idx
          break
        }
      }
      if (target < 0 || !Array.isArray(messages[target]?.parts)) {
        return
      }
      if (!injectIntoParts(messages[target].parts ?? [], buildSessionContext(sessionId))) {
        return
      }
      injectedSessions.add(sessionId)
      writeGatewayEventAudit(directory, {
        hook: "session-runtime-context",
        stage: "inject",
        reason_code: "session_runtime_context_injected_transform",
        session_id: sessionId,
      })
    },
  }
}
