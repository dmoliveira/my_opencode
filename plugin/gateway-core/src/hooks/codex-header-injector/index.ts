import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"

interface TextPart {
  type?: string
  text?: string
}

interface ChatPayload {
  properties?: {
    sessionID?: string
    sessionId?: string
    info?: { id?: string }
    model?: unknown
    providerID?: unknown
    modelID?: unknown
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
    providerID?: unknown
    modelID?: unknown
    model?: unknown
  }
  output?: {
    messages?: Array<{
      info?: {
        role?: string
        sessionID?: string
        sessionId?: string
        providerID?: unknown
        modelID?: unknown
        model?: unknown
      }
      parts?: TextPart[]
    }>
  }
  directory?: string
}

interface SessionEventPayload {
  properties?: {
    info?: { id?: string }
    sessionID?: string
    sessionId?: string
  }
}

const CODEX_HEADER_MARKER = "[codex HEADER]"
const CODEX_HEADER_LINES = [
  CODEX_HEADER_MARKER,
  "Codex provider guidance is active.",
  "- Prefer concise, deterministic tool interactions",
  "- Keep output focused on actionable implementation details",
  "- Avoid redundant prose when code or command evidence is available",
].join("\n")

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
  return ""
}

function textFromUnknown(value: unknown): string {
  return typeof value === "string" ? value.trim().toLowerCase() : ""
}

function isCodexModel(payload: ChatPayload | TransformPayload): boolean {
  const candidates: unknown[] = []
  const chatPayload = payload as ChatPayload
  candidates.push(chatPayload.properties?.model)
  candidates.push(chatPayload.properties?.providerID)
  candidates.push(chatPayload.properties?.modelID)

  const transformPayload = payload as TransformPayload
  candidates.push(transformPayload.input?.model)
  candidates.push(transformPayload.input?.providerID)
  candidates.push(transformPayload.input?.modelID)

  const messages = transformPayload.output?.messages
  if (Array.isArray(messages) && messages.length > 0) {
    for (let idx = messages.length - 1; idx >= 0; idx -= 1) {
      const info = messages[idx]?.info
      candidates.push(info?.model)
      candidates.push(info?.providerID)
      candidates.push(info?.modelID)
    }
  }

  const joined = candidates
    .map((value) => textFromUnknown(value))
    .filter((value) => value.length > 0)
    .join("\n")

  return joined.includes("codex") || joined.includes("gpt-5")
}

function injectIntoParts(parts: TextPart[]): boolean {
  const textPart = parts.find((part) => part.type === "text" && typeof part.text === "string")
  if (!textPart || typeof textPart.text !== "string") {
    return false
  }
  if (textPart.text.includes(CODEX_HEADER_MARKER)) {
    return false
  }
  textPart.text = `${CODEX_HEADER_LINES}\n\n---\n\n${textPart.text}`
  return true
}

export function createCodexHeaderInjectorHook(options: {
  directory: string
  enabled: boolean
}): GatewayHook {
  const injectedSessions = new Set<string>()
  return {
    id: "codex-header-injector",
    priority: 296,
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

      if (type === "chat.message") {
        const eventPayload = (payload ?? {}) as ChatPayload
        const sessionId = resolveSessionId(eventPayload)
        if (!sessionId || injectedSessions.has(sessionId) || !isCodexModel(eventPayload)) {
          return
        }
        const parts = eventPayload.output?.parts
        if (!Array.isArray(parts) || !injectIntoParts(parts)) {
          return
        }
        injectedSessions.add(sessionId)
        writeGatewayEventAudit(eventPayload.directory || options.directory, {
          hook: "codex-header-injector",
          stage: "inject",
          reason_code: "codex_header_injected_chat",
          session_id: sessionId,
        })
        return
      }

      if (type !== "experimental.chat.messages.transform") {
        return
      }

      const eventPayload = (payload ?? {}) as TransformPayload
      const sessionId = resolveSessionId(eventPayload)
      if (!sessionId || injectedSessions.has(sessionId) || !isCodexModel(eventPayload)) {
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
      if (target < 0 || !Array.isArray(messages[target]?.parts) || !injectIntoParts(messages[target].parts ?? [])) {
        return
      }
      injectedSessions.add(sessionId)
      writeGatewayEventAudit(eventPayload.directory || options.directory, {
        hook: "codex-header-injector",
        stage: "inject",
        reason_code: "codex_header_injected_transform",
        session_id: sessionId,
      })
    },
  }
}
