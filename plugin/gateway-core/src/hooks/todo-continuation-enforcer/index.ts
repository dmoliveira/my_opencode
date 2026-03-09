import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import { loadGatewayState } from "../../state/storage.js"
import { injectHookMessage } from "../hook-message-injector/index.js"
import type { GatewayHook } from "../registry.js"
import type { StopContinuationGuard } from "../stop-continuation-guard/index.js"

interface GatewayClient {
  session?: {
    messages(args: {
      path: { id: string }
      query?: { directory?: string }
    }): Promise<{ data?: Array<{ info?: { role?: string }; parts?: Array<{ type: string; text?: string }> }> }>
    promptAsync(args: {
      path: { id: string }
      body: { parts: Array<{ type: string; text: string }> }
      query?: { directory?: string }
    }): Promise<void>
  }
}

interface ToolAfterPayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
  }
  output?: {
    output?: unknown
  }
  properties?: {
    sessionID?: string
    sessionId?: string
    info?: { id?: string }
  }
  directory?: string
}

interface SessionEventPayload {
  directory?: string
  input?: {
    sessionID?: string
    sessionId?: string
  }
  properties?: {
    sessionID?: string
    sessionId?: string
    info?: { id?: string }
  }
}

interface ChatPayload {
  directory?: string
  properties?: {
    sessionID?: string
    sessionId?: string
    prompt?: unknown
    message?: unknown
    text?: unknown
    parts?: Array<{ type?: string; text?: string }>
  }
  output?: {
    parts?: Array<{ type?: string; text?: string; synthetic?: boolean }>
  }
}

interface SessionState {
  pendingContinuation: boolean
  lastInjectedAt: number
  consecutiveFailures: number
  inFlight: boolean
  markerProbeAttempted: boolean
  continueIntentArmed: boolean
}

const CONTINUE_LOOP_MARKER = "<CONTINUE-LOOP>"
const TODO_CONTINUATION_PROMPT = [
  "[SYSTEM DIRECTIVE: TODO CONTINUATION]",
  "Incomplete tasks remain in your current run.",
  "- Continue with the next pending task immediately",
  "- Do not ask for extra confirmation",
  "- Keep executing until all pending tasks are complete",
].join("\n")

const CONTINUE_INTENT_PATTERN =
  /\b(continue|keep going|go ahead|proceed|carry on|let'?s do (it|this)|do it now|yes[,! ]*let'?s do)\b/i
const STOP_INTENT_PATTERN = /\b(stop|pause|hold|that'?s all|no thanks|done for now)\b/i
const NEGATED_CONTINUE_INTENT_PATTERN =
  /\b(do not|don't|dont|not)\s+(continue|proceed|go ahead|keep going|carry on)\b/i
const NEGATED_STOP_INTENT_PATTERN = /\b(do not|don't|dont|not)\s+stop\b/i

function isContinueIntent(prompt: string): boolean {
  if (NEGATED_CONTINUE_INTENT_PATTERN.test(prompt)) {
    return false
  }
  return CONTINUE_INTENT_PATTERN.test(prompt)
}

function isStopIntent(prompt: string): boolean {
  if (NEGATED_STOP_INTENT_PATTERN.test(prompt)) {
    return false
  }
  return STOP_INTENT_PATTERN.test(prompt)
}

function assistantText(message: {
  info?: { role?: string }
  parts?: Array<{ type?: string; text?: string; synthetic?: boolean }>
}): string {
  if (message?.info?.role !== "assistant") {
    return ""
  }
  return (message.parts ?? [])
    .filter((part) => part?.type === "text" && typeof part.text === "string")
    .filter((part) => !(part as { synthetic?: boolean }).synthetic)
    .map((part) => part.text?.trim() ?? "")
    .filter(Boolean)
    .join("\n")
}

function promptText(payload: ChatPayload): string {
  const props = payload.properties ?? {}
  const direct = [props.prompt, props.message, props.text]
  for (const candidate of direct) {
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim()
    }
  }
  const partSources = [payload.output?.parts, props.parts]
  for (const parts of partSources) {
    if (!Array.isArray(parts)) {
      continue
    }
    const text = parts
      .filter((part) => part?.type === "text" && typeof part.text === "string")
      .filter((part) => !(part as { synthetic?: boolean }).synthetic)
      .map((part) => part.text?.trim() ?? "")
      .filter(Boolean)
      .join("\n")
    if (text) {
      return text
    }
  }
  return ""
}

function hasHardContinuationCue(text: string): boolean {
  const normalized = text.toLowerCase()
  if (text.includes(CONTINUE_LOOP_MARKER)) {
    return true
  }
  return (
    normalized.includes("still left to do") ||
    normalized.includes("remaining actionable") ||
    normalized.includes("remaining tasks") ||
    normalized.includes("remaining items") ||
    normalized.includes("next items") ||
    normalized.includes("in progress") ||
    normalized.includes("in-progress right now") ||
    normalized.includes("still left to do (next") ||
    normalized.includes("need finish")
  )
}

function hasSoftContinuationCue(text: string): boolean {
  const normalized = text.toLowerCase()
  const hasNextSteps =
    normalized.includes("next steps") ||
    normalized.includes("natural next") ||
    normalized.includes("if you want")
  const hasOfferToExecute =
    normalized.includes("i can") &&
    (normalized.includes("now") || normalized.includes("next") || normalized.includes("run"))
  return hasNextSteps && hasOfferToExecute
}

function hasPendingCueText(text: string, continueIntentArmed: boolean): boolean {
  if (!text.trim()) {
    return false
  }
  if (hasHardContinuationCue(text)) {
    return true
  }
  if (continueIntentArmed && hasSoftContinuationCue(text)) {
    return true
  }
  return false
}

function resolveSessionId(payload: {
  properties?: { sessionID?: string; sessionId?: string; info?: { id?: string } }
  input?: { sessionID?: string; sessionId?: string }
}): string {
  const candidates = [
    payload.properties?.sessionID,
    payload.properties?.sessionId,
    payload.properties?.info?.id,
    payload.input?.sessionID,
    payload.input?.sessionId,
  ]
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) {
      return value.trim()
    }
  }
  return ""
}

function resolveDirectory(payload: { directory?: string }, fallback: string): string {
  return typeof payload.directory === "string" && payload.directory.trim() ? payload.directory : fallback
}

function hasPendingCue(
  messages: Array<{ info?: { role?: string }; parts?: Array<{ type?: string; text?: string; synthetic?: boolean }> }>,
  continueIntentArmed: boolean,
): boolean {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const text = assistantText(messages[i])
    if (!text) {
      continue
    }
    return hasPendingCueText(text, continueIntentArmed)
  }
  return false
}

function getSessionState(store: Map<string, SessionState>, sessionId: string): SessionState {
  const existing = store.get(sessionId)
  if (existing) {
    return existing
  }
  const created: SessionState = {
    pendingContinuation: false,
    lastInjectedAt: 0,
    consecutiveFailures: 0,
    inFlight: false,
    markerProbeAttempted: false,
    continueIntentArmed: false,
  }
  store.set(sessionId, created)
  return created
}

export function createTodoContinuationEnforcerHook(options: {
  directory: string
  enabled: boolean
  client?: GatewayClient
  stopGuard?: StopContinuationGuard
  cooldownMs: number
  maxConsecutiveFailures: number
}): GatewayHook {
  const sessionState = new Map<string, SessionState>()
  return {
    id: "todo-continuation-enforcer",
    priority: 345,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }

      if (type === "session.deleted" || type === "session.compacted") {
        const eventPayload = (payload ?? {}) as SessionEventPayload
        const sessionId = resolveSessionId(eventPayload)
        if (sessionId) {
          sessionState.delete(sessionId)
        }
        return
      }

      if (type === "chat.message") {
        const eventPayload = (payload ?? {}) as ChatPayload
        const sessionId = resolveSessionId(eventPayload)
        if (!sessionId) {
          return
        }
        const state = getSessionState(sessionState, sessionId)
        const prompt = promptText(eventPayload)
        if (!prompt) {
          return
        }
        if (isStopIntent(prompt)) {
          state.continueIntentArmed = false
          state.pendingContinuation = false
          return
        }
        if (isContinueIntent(prompt)) {
          state.continueIntentArmed = true
        }
        return
      }

      if (type === "tool.execute.after") {
        const eventPayload = (payload ?? {}) as ToolAfterPayload
        const sessionId = resolveSessionId(eventPayload)
        const tool = String(eventPayload.input?.tool ?? "").toLowerCase()
        if (!sessionId || tool !== "task" || typeof eventPayload.output?.output !== "string") {
          return
        }
        const state = getSessionState(sessionState, sessionId)
        state.pendingContinuation = hasPendingCueText(
          eventPayload.output.output,
          state.continueIntentArmed,
        )
        state.markerProbeAttempted = true
        return
      }

      if (type !== "session.idle") {
        return
      }

      const eventPayload = (payload ?? {}) as SessionEventPayload
      const directory = resolveDirectory(eventPayload, options.directory)
      const sessionId = resolveSessionId(eventPayload)
      if (!sessionId) {
        return
      }
      if (options.stopGuard?.isStopped(sessionId)) {
        writeGatewayEventAudit(directory, {
          hook: "todo-continuation-enforcer",
          stage: "skip",
          reason_code: "todo_continuation_stop_guard",
          session_id: sessionId,
        })
        return
      }
      const gatewayState = loadGatewayState(directory)
      if (gatewayState?.activeLoop?.active === true && gatewayState.activeLoop.sessionId === sessionId) {
        writeGatewayEventAudit(directory, {
          hook: "todo-continuation-enforcer",
          stage: "skip",
          reason_code: "todo_continuation_active_loop",
          session_id: sessionId,
        })
        return
      }

      const state = getSessionState(sessionState, sessionId)
      const now = Date.now()
      const cooldownBase = Math.max(1, Math.floor(options.cooldownMs))
      const maxFailures = Math.max(1, Math.floor(options.maxConsecutiveFailures))
      const failureResetWindowMs = Math.max(cooldownBase * 4, 60_000)
      if (state.consecutiveFailures >= maxFailures) {
        if (state.lastInjectedAt > 0 && now - state.lastInjectedAt > failureResetWindowMs) {
          state.consecutiveFailures = 0
        } else {
          writeGatewayEventAudit(directory, {
            hook: "todo-continuation-enforcer",
            stage: "skip",
            reason_code: "todo_continuation_failure_budget_exhausted",
            session_id: sessionId,
            failures: state.consecutiveFailures,
          })
          return
        }
      }
      if (state.inFlight) {
        return
      }
      const cooldownMs = cooldownBase * 2 ** Math.min(state.consecutiveFailures, 5)
      if (state.lastInjectedAt > 0 && now - state.lastInjectedAt < cooldownMs) {
        return
      }

      let pending = state.pendingContinuation
      const client = options.client?.session
      if (!pending && client && !state.markerProbeAttempted) {
        try {
          const response = await client.messages({
            path: { id: sessionId },
            query: { directory },
          })
          pending = hasPendingCue(
            Array.isArray(response.data) ? response.data : [],
            state.continueIntentArmed,
          )
          state.markerProbeAttempted = true
        } catch {
          writeGatewayEventAudit(directory, {
            hook: "todo-continuation-enforcer",
            stage: "skip",
            reason_code: "todo_continuation_probe_failed",
            session_id: sessionId,
          })
          return
        }
      }
      state.pendingContinuation = pending
      if (!pending || !client) {
        writeGatewayEventAudit(directory, {
          hook: "todo-continuation-enforcer",
          stage: "skip",
          reason_code: "todo_continuation_no_pending",
          session_id: sessionId,
        })
        return
      }

      state.inFlight = true
      try {
        const injected = await injectHookMessage({
          session: client,
          sessionId,
          content: TODO_CONTINUATION_PROMPT,
          directory,
        })
        state.lastInjectedAt = now
        if (injected) {
          state.consecutiveFailures = 0
          writeGatewayEventAudit(directory, {
            hook: "todo-continuation-enforcer",
            stage: "inject",
            reason_code: "todo_continuation_injected",
            session_id: sessionId,
          })
        } else {
          state.consecutiveFailures += 1
          writeGatewayEventAudit(directory, {
            hook: "todo-continuation-enforcer",
            stage: "inject",
            reason_code: "todo_continuation_inject_failed",
            session_id: sessionId,
            failures: state.consecutiveFailures,
          })
        }
      } finally {
        state.inFlight = false
      }
    },
  }
}
