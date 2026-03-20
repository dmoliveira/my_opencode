import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import { injectHookMessage } from "../hook-message-injector/index.js"
import type { GatewayHook } from "../registry.js"
import { classifyProviderRetryReason, isContextOverflowNonRetryable } from "../shared/provider-retry-reason.js"
import {
  buildCompactDecisionCacheKey,
  type LlmDecisionRuntime,
  writeDecisionComparisonAudit,
} from "../shared/llm-decision-runtime.js"

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

const CLASSIFICATION_BY_CHAR: Record<string, Classification> = {
  F: "free_usage_exhausted",
  R: "rate_limited",
  O: "provider_overloaded",
}

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
    .map((value) => (typeof value === "string" ? value.trim() : value != null ? JSON.stringify(value) : ""))
    .filter(Boolean)
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

function buildAiInstruction(): string {
  return "Classify this provider error. F=free_usage_or_credit_exhausted, R=rate_limited, O=provider_overloaded_or_unavailable, N=not_classified."
}

function buildAiContext(text: string): string {
  return `error=${text.trim() || "(empty)"}`
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

function buildConcurrencySkipHint(): string {
  return [
    "[provider ERROR CLASSIFIER]",
    "LLM classification skipped — subprocess already in progress.",
    "- A decision subprocess is already running; this event was dropped.",
    "- The active classification will complete shortly.",
    "- Pattern-based error detection continues normally.",
  ].join("\n")
}

function buildCooldownSkipHint(): string {
  return [
    "[provider ERROR CLASSIFIER]",
    "LLM classification paused — runtime cooldown active.",
    "- The decision runtime is cooling down after a recent subprocess failure.",
    "- Provider errors will not be LLM-classified until the cooldown expires.",
    "- Pattern-based classification continues normally.",
  ].join("\n")
}

export function createProviderErrorClassifierHook(options: {
  directory: string
  enabled: boolean
  client?: GatewayClient
  cooldownMs: number
  decisionRuntime?: LlmDecisionRuntime
}): GatewayHook {
  const lastClassificationBySession = new Map<string, { classification: Classification; at: number }>()
  const lastRuntimeSkipNoticeBySession = new Map<string, number>()
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
          lastRuntimeSkipNoticeBySession.delete(sessionId)
        }
        return
      }
      if (type !== "session.error" && type !== "message.updated") {
        return
      }
      const eventPayload = (payload ?? {}) as EventPayload
      const text = extractErrorText(eventPayload)
      if (!text) {
        return
      }
      if (isContextOverflowNonRetryable(text)) {
        return
      }
      let outcome = classify(text)
      const sessionId = resolveSessionId(eventPayload)
      const session = options.client?.session
      if (!outcome && options.decisionRuntime && sessionId) {
        const decision = await options.decisionRuntime.decide({
          hookId: "provider-error-classifier",
          sessionId,
          templateId: "provider-error-classifier-v1",
          instruction: buildAiInstruction(),
          context: buildAiContext(text),
          allowedChars: ["F", "R", "O", "N"],
          decisionMeaning: {
            F: "free_usage_exhausted",
            R: "rate_limited",
            O: "provider_overloaded",
            N: "not_classified",
          },
          cacheKey: buildCompactDecisionCacheKey({
            prefix: "provider-error",
            text: buildAiContext(text),
          }),
        })
        if (decision.skippedReason === "max_concurrency_reached" || decision.skippedReason === "runtime_cooldown") {
          if (session && sessionId) {
            const now = Date.now()
            const cooldownMs = Math.max(1, Math.floor(options.cooldownMs))
            const lastNoticeAt = lastRuntimeSkipNoticeBySession.get(sessionId) ?? 0
            if (now - lastNoticeAt >= cooldownMs) {
              const hint = decision.skippedReason === "max_concurrency_reached"
                ? buildConcurrencySkipHint()
                : buildCooldownSkipHint()
              const directory = resolveDirectory(eventPayload, options.directory)
              await injectHookMessage({ session, sessionId, content: hint, directory })
              writeGatewayEventAudit(directory, {
                hook: "provider-error-classifier",
                stage: "state",
                reason_code: `llm_decision_${decision.skippedReason}`,
                session_id: sessionId,
              })
              lastRuntimeSkipNoticeBySession.set(sessionId, now)
            }
          }
        }
        if (decision.accepted) {
          const classification = CLASSIFICATION_BY_CHAR[decision.char]
          if (classification) {
            writeDecisionComparisonAudit({
              directory: resolveDirectory(eventPayload, options.directory),
              hookId: "provider-error-classifier",
              sessionId,
              mode: options.decisionRuntime.config.mode,
              deterministicMeaning: "not_classified",
              aiMeaning: decision.meaning || classification,
              deterministicValue: "none",
              aiValue: classification,
            })
            writeGatewayEventAudit(resolveDirectory(eventPayload, options.directory), {
              hook: "provider-error-classifier",
              stage: "state",
              reason_code: "llm_provider_error_decision_recorded",
              session_id: sessionId,
              llm_decision_char: decision.char,
              llm_decision_meaning: decision.meaning,
              llm_decision_mode: options.decisionRuntime.config.mode,
            })
            if (options.decisionRuntime.config.mode === "shadow") {
              writeGatewayEventAudit(resolveDirectory(eventPayload, options.directory), {
                hook: "provider-error-classifier",
                stage: "state",
                reason_code: "llm_provider_error_shadow_deferred",
                session_id: sessionId,
                llm_decision_char: decision.char,
                llm_decision_meaning: decision.meaning,
                llm_decision_mode: options.decisionRuntime.config.mode,
              })
            } else {
              outcome = {
                classification,
                reason: `llm:${decision.meaning || decision.char}`,
              }
            }
          }
        }
      }
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
