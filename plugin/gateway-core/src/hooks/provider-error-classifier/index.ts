import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import { injectHookMessage } from "../hook-message-injector/index.js"
import type { GatewayHook } from "../registry.js"
import { classifyProviderRetryReason, isContextOverflowNonRetryable } from "../shared/provider-retry-reason.js"

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

function classify(text: string): { classification: Classification; reason: string } | null {
  const reason = classifyProviderRetryReason(text)
  if (!reason) {
    return null
  }
  if (reason.code === "free_usage_exhausted") {
    return { classification: "free_usage_exhausted", reason: reason.message }
  }
  if (reason.code === "provider_overloaded") {
    return { classification: "provider_overloaded", reason: reason.message }
  }
  return { classification: "rate_limited", reason: reason.message }
}

function buildHint(classification: Classification, reason: string): string {
  if (classification === "free_usage_exhausted") {
    return [
      "[provider ERROR CLASSIFIER]",
      "Detected provider free-usage or credit exhaustion.",
      `- Canonical reason: ${reason}`,
      "- Add provider credits / quota before retrying",
      "- Do not loop immediate retries until quota is restored",
    ].join("\n")
  }
  if (classification === "rate_limited") {
    return [
      "[provider ERROR CLASSIFIER]",
      "Detected provider rate limiting.",
      `- Canonical reason: ${reason}`,
      "- Reduce retry frequency and apply backoff",
      "- Keep follow-up prompts concise while limits reset",
    ].join("\n")
  }
  return [
    "[provider ERROR CLASSIFIER]",
    "Detected provider overload/unavailable condition.",
    `- Canonical reason: ${reason}`,
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
      if (isContextOverflowNonRetryable(text)) {
        return
      }
      const outcome = classify(text)
      const sessionId = resolveSessionId(eventPayload)
      const session = options.client?.session
      if (!outcome || !sessionId || !session) {
        return
      }
      const now = Date.now()
      const cooldownMs = Math.max(1, Math.floor(options.cooldownMs))
      const previous = lastClassificationBySession.get(sessionId)
      if (previous && previous.classification === outcome.classification && now - previous.at < cooldownMs) {
        return
      }
      const directory = resolveDirectory(eventPayload, options.directory)
      await injectHookMessage({
        session,
        sessionId,
        content: buildHint(outcome.classification, outcome.reason),
        directory,
      })
      writeGatewayEventAudit(directory, {
        hook: "provider-error-classifier",
        stage: "state",
        reason_code: `provider_error_${outcome.classification}`,
        session_id: sessionId,
      })
      lastClassificationBySession.set(sessionId, { classification: outcome.classification, at: now })
    },
  }
}
