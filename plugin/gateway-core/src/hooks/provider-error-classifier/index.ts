import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import { injectHookMessage } from "../hook-message-injector/index.js"
import type { GatewayHook } from "../registry.js"

interface GatewayClient {
  session?: {
    promptAsync(args: {
      path: { id: string }
      body: { parts: Array<{ type: string; text: string }> }
      query?: { directory?: string }
    }): Promise<void>
  }
}

interface EventPayload {
  directory?: string
  error?: unknown
  message?: unknown
  properties?: {
    sessionID?: string
    sessionId?: string
    info?: { id?: string }
    error?: unknown
  }
}

type Classification = "free_usage_exhausted" | "rate_limited" | "provider_overloaded"

function resolveSessionId(payload: EventPayload): string {
  const candidates = [payload.properties?.sessionID, payload.properties?.sessionId, payload.properties?.info?.id]
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) {
      return value.trim()
    }
  }
  return ""
}

function resolveDirectory(payload: EventPayload, fallback: string): string {
  return typeof payload.directory === "string" && payload.directory.trim() ? payload.directory : fallback
}

function extractErrorText(payload: EventPayload): string {
  return [payload.error, payload.message, payload.properties?.error]
    .map((value) => (typeof value === "string" ? value : JSON.stringify(value ?? "")))
    .join("\n")
}

function classify(text: string): Classification | null {
  if (/freeusagelimiterror/i.test(text) || /free usage exceeded/i.test(text) || /insufficient.*credits/i.test(text)) {
    return "free_usage_exhausted"
  }
  if (/too_many_requests/i.test(text) || /rate[_ -]?limit(ed)?/i.test(text)) {
    return "rate_limited"
  }
  if (/overloaded/i.test(text) || /code.*(exhausted|unavailable)/i.test(text) || /provider is overloaded/i.test(text)) {
    return "provider_overloaded"
  }
  return null
}

function buildHint(classification: Classification): string {
  if (classification === "free_usage_exhausted") {
    return [
      "[provider ERROR CLASSIFIER]",
      "Detected provider free-usage or credit exhaustion.",
      "- Add provider credits / quota before retrying",
      "- Do not loop immediate retries until quota is restored",
    ].join("\n")
  }
  if (classification === "rate_limited") {
    return [
      "[provider ERROR CLASSIFIER]",
      "Detected provider rate limiting.",
      "- Reduce retry frequency and apply backoff",
      "- Keep follow-up prompts concise while limits reset",
    ].join("\n")
  }
  return [
    "[provider ERROR CLASSIFIER]",
    "Detected provider overload/unavailable condition.",
    "- Wait and retry with backoff",
    "- Continue with minimal prompt scope until provider stabilizes",
  ].join("\n")
}

export function createProviderErrorClassifierHook(options: {
  directory: string
  enabled: boolean
  client?: GatewayClient
  cooldownMs: number
}): GatewayHook {
  const lastClassificationBySession = new Map<string, { classification: Classification; at: number }>()
  return {
    id: "provider-error-classifier",
    priority: 361,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }
      if (type === "session.deleted") {
        const sessionId = resolveSessionId((payload ?? {}) as EventPayload)
        if (sessionId) {
          lastClassificationBySession.delete(sessionId)
        }
        return
      }
      if (type !== "session.error" && type !== "message.updated") {
        return
      }
      const eventPayload = (payload ?? {}) as EventPayload
      const text = extractErrorText(eventPayload)
      const classification = classify(text)
      const sessionId = resolveSessionId(eventPayload)
      const session = options.client?.session
      if (!classification || !sessionId || !session) {
        return
      }
      const now = Date.now()
      const cooldownMs = Math.max(1, Math.floor(options.cooldownMs))
      const previous = lastClassificationBySession.get(sessionId)
      if (previous && previous.classification === classification && now - previous.at < cooldownMs) {
        return
      }
      const directory = resolveDirectory(eventPayload, options.directory)
      await injectHookMessage({
        session,
        sessionId,
        content: buildHint(classification),
        directory,
      })
      writeGatewayEventAudit(directory, {
        hook: "provider-error-classifier",
        stage: "state",
        reason_code: `provider_error_${classification}`,
        session_id: sessionId,
      })
      lastClassificationBySession.set(sessionId, { classification, at: now })
    },
  }
}
