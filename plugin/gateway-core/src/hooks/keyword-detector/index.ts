import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"

export type KeywordMode = "ultrawork" | "analyze" | "search"

// Declares mode lookup API exposed to continuation hook.
export interface KeywordDetector {
  modeForSession(sessionId: string): KeywordMode | null
}

interface ChatPayload {
  properties?: {
    sessionID?: string
    prompt?: unknown
    message?: unknown
    text?: unknown
    parts?: Array<{ type?: string; text?: string }>
  }
}

interface EventPayload {
  properties?: {
    info?: { id?: string }
  }
}

// Extracts searchable prompt text from chat payload variants.
function extractPromptText(payload: ChatPayload): string {
  const props = payload.properties ?? {}
  const direct = [props.prompt, props.message, props.text]
  for (const value of direct) {
    if (typeof value === "string" && value.trim()) {
      return value.trim()
    }
  }
  if (Array.isArray(props.parts)) {
    return props.parts
      .filter((part) => part?.type === "text" && typeof part.text === "string")
      .map((part) => part.text?.trim() ?? "")
      .filter(Boolean)
      .join("\n")
  }
  return ""
}

// Returns detected mode keyword from prompt text.
function detectMode(prompt: string): KeywordMode | null {
  const text = prompt.toLowerCase()
  if (/\bultrawork\b|\bulw\b/.test(text)) {
    return "ultrawork"
  }
  if (/\banalyze\b|\banalysis\b/.test(text)) {
    return "analyze"
  }
  if (/\bsearch\b|\bresearch\b/.test(text)) {
    return "search"
  }
  return null
}

// Creates keyword detector hook that tracks mode hints by session.
export function createKeywordDetectorHook(options: {
  directory: string
  enabled: boolean
}): GatewayHook & KeywordDetector {
  const modesBySession = new Map<string, KeywordMode>()
  return {
    id: "keyword-detector",
    priority: 296,
    modeForSession(sessionId: string): KeywordMode | null {
      return modesBySession.get(sessionId) ?? null
    },
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }
      if (type === "session.deleted") {
        const eventPayload = (payload ?? {}) as EventPayload
        const sessionId = eventPayload.properties?.info?.id
        if (typeof sessionId === "string" && sessionId.trim()) {
          modesBySession.delete(sessionId.trim())
        }
        return
      }
      if (type !== "chat.message") {
        return
      }
      const eventPayload = (payload ?? {}) as ChatPayload
      const sessionId = eventPayload.properties?.sessionID
      if (typeof sessionId !== "string" || !sessionId.trim()) {
        return
      }
      const directory = options.directory
      const text = extractPromptText(eventPayload)
      if (!text) {
        return
      }
      const detected = detectMode(text)
      if (!detected) {
        return
      }
      modesBySession.set(sessionId.trim(), detected)
      writeGatewayEventAudit(directory, {
        hook: "keyword-detector",
        stage: "state",
        reason_code: "keyword_mode_detected",
        session_id: sessionId.trim(),
        keyword_mode: detected,
      })
    },
  }
}
