import type { GatewayHook } from "../registry.js"

interface ChatPayload {
  properties?: {
    info?: { id?: unknown }
    sessionID?: unknown
    sessionId?: unknown
    prompt?: unknown
    message?: unknown
    text?: unknown
  }
  output?: {
    parts?: Array<{ type: string; text?: string }>
  }
}

interface SessionEventPayload {
  properties?: {
    info?: { id?: unknown }
  }
}

const COMPLEX_TASK_PATTERN = /(debug|architecture|refactor|research|investigate|root cause|postmortem|optimi[sz]e)/

// Extracts prompt text from chat payload properties.
function promptText(payload: ChatPayload): string {
  const props = payload.properties ?? {}
  const candidates = [props.prompt, props.message, props.text]
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) {
      return value.trim()
    }
  }
  return ""
}

// Resolves session id from event payload.
function resolveSessionId(payload: ChatPayload | SessionEventPayload): string {
  const candidates = [
    payload.properties?.info?.id,
    (payload as ChatPayload).properties?.sessionID,
    (payload as ChatPayload).properties?.sessionId,
  ]
  for (const id of candidates) {
    if (typeof id === "string" && id.trim()) {
      return id.trim()
    }
  }
  return ""
}

// Creates session guidance hook for complex tasks.
export function createAgentUserReminderHook(options: { enabled: boolean }): GatewayHook {
  const remindedSessions = new Set<string>()

  return {
    id: "agent-user-reminder",
    priority: 365,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }

      if (type === "session.deleted" || type === "session.compacted") {
        const sessionPayload = (payload ?? {}) as SessionEventPayload
        const sessionId = resolveSessionId(sessionPayload)
        if (sessionId) {
          remindedSessions.delete(sessionId)
        }
        return
      }

      if (type !== "chat.message") {
        return
      }

      const eventPayload = (payload ?? {}) as ChatPayload
      const sessionId = resolveSessionId(eventPayload)
      if (sessionId && remindedSessions.has(sessionId)) {
        return
      }

      const prompt = promptText(eventPayload).toLowerCase()
      if (!prompt || !COMPLEX_TASK_PATTERN.test(prompt)) {
        return
      }

      const parts = eventPayload.output?.parts
      if (!Array.isArray(parts) || parts.length === 0) {
        return
      }
      const firstText = parts.find((part) => part.type === "text")
      if (!firstText || typeof firstText.text !== "string") {
        return
      }

      firstText.text = `${firstText.text}\n\n[session guidance] For complex work, use focused passes: discover with explore, validate with verifier, and run reviewer before final delivery.`
      if (sessionId) {
        remindedSessions.add(sessionId)
      }
    },
  }
}
