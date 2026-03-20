import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import { loadGatewayState } from "../../state/storage.js"
import { injectHookMessage, inspectHookMessageSafety } from "../hook-message-injector/index.js"
import type { GatewayHook } from "../registry.js"
import { buildCompactDecisionCacheKey, type LlmDecisionRuntime, writeDecisionComparisonAudit } from "../shared/llm-decision-runtime.js"
import type { StopContinuationGuard } from "../stop-continuation-guard/index.js"

interface GatewayClient {
  session?: {
    messages(args: {
      path: { id: string }
      query?: { directory?: string }
    }): Promise<{
      data?: Array<{
        info?: { role?: string; error?: unknown; time?: { completed?: number } }
        parts?: Array<{ type: string; text?: string; synthetic?: boolean }>
      }>
    }>
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
    trace_id?: string
    traceId?: string
  }
  output?: {
    output?: unknown
  }
  properties?: {
    sessionID?: string
    sessionId?: string
    trace_id?: string
    traceId?: string
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

interface MessageUpdatedPayload {
  directory?: string
  properties?: {
    sessionID?: string
    sessionId?: string
    trace_id?: string
    traceId?: string
    info?: {
      id?: string
      role?: string
      sessionID?: string
      sessionId?: string
      error?: unknown
      time?: { completed?: number }
    }
    parts?: Array<{ type?: string; text?: string; synthetic?: boolean }>
  }
  output?: {
    parts?: Array<{ type?: string; text?: string; synthetic?: boolean }>
  }
}

interface SessionState {
  pendingContinuation: boolean
  pendingSource?: "assistant_message" | "task_output" | "message_probe"
  pendingTodoCount: number
  lastInjectedAt: number
  consecutiveFailures: number
  inFlight: boolean
  markerProbeAttempted: boolean
  continueIntentArmed: boolean
  continueAckPending: boolean
  lastTraceId?: string
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

function shouldAcknowledgeContinueIntent(prompt: string): boolean {
  const normalized = prompt.trim().toLowerCase()
  if (!normalized || normalized.length > 80 || normalized.includes("\n")) {
    return false
  }
  return /^(yes|yes please|continue|continue please|go ahead|proceed|keep going|carry on|do it now)$/.test(
    normalized,
  )
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
  const hasActionableNextItemsCue =
    normalized.includes("next items") &&
    !normalized.includes("next items: none") &&
    !normalized.includes("next items none") &&
    !normalized.includes("next items: n/a")
  return (
    normalized.includes("still left to do") ||
    normalized.includes("remaining actionable") ||
    normalized.includes("remaining epic") ||
    normalized.includes("next remaining epic") ||
    normalized.includes("remaining tasks") ||
    normalized.includes("remaining items") ||
    hasActionableNextItemsCue ||
    normalized.includes("continue loop") ||
    normalized.includes("in-progress right now") ||
    normalized.includes("still left to do (next") ||
    normalized.includes("need finish")
  )
}

function hasSoftContinuationCue(text: string): boolean {
  const normalized = text.toLowerCase()
  const hasNextSteps =
    normalized.includes("next steps") ||
    normalized.includes("next safe steps") ||
    normalized.includes("natural next") ||
    normalized.includes("if you want")
  const hasOfferToExecute =
    normalized.includes("i can") &&
    (normalized.includes("now") || normalized.includes("next") || normalized.includes("run"))
  return hasNextSteps && hasOfferToExecute
}

function hasCompletionClosureCue(text: string): boolean {
  const normalized = text.toLowerCase()
  return (
    normalized.includes("nothing additional") ||
    normalized.includes("nothing more to") ||
    normalized.includes("nothing left to") ||
    normalized.includes("there is nothing additional") ||
    normalized.includes("this slice is done") ||
    normalized.includes("work from this slice is done") ||
    normalized.includes("task is finished") ||
    normalized.includes("task complete") ||
    normalized.includes("complete for now") ||
    normalized.includes("done for now") ||
    normalized.includes("already included") ||
    normalized.includes("already in the current released state") ||
    normalized.includes("already in the released state")
  )
}

function hasActionableNextSliceCue(text: string): boolean {
  const normalized = text.toLowerCase()
  return (
    normalized.includes("next steps") ||
    normalized.includes("next safe steps") ||
    normalized.includes("natural next") ||
    normalized.includes("best next safe slice") ||
    normalized.includes("next safe slice") ||
    normalized.includes("next slice")
  )
}

function hasDirectContinuationOfferCue(text: string): boolean {
  const normalized = text.toLowerCase()
  return (
    /\bi\s+will\s+continue\b/.test(normalized) ||
    /\bi'?ll\s+continue\b/.test(normalized) ||
    /\bi\s+am\s+continuing\b/.test(normalized) ||
    /\bi'?m\s+continuing\b/.test(normalized) ||
    /\bcontinuing\s+with\s+the\s+next\b/.test(normalized) ||
    normalized.includes("continue directly")
  )
}

function parseTodoContinuationCount(raw: unknown): number | null {
  let parsed = raw
  if (typeof raw === "string") {
    const trimmed = raw.trim()
    if (!trimmed) {
      return null
    }
    try {
      parsed = JSON.parse(trimmed)
    } catch {
      return null
    }
  }
  if (!Array.isArray(parsed)) {
    return null
  }
  let openTodos = 0
  for (const item of parsed) {
    if (!item || typeof item !== "object") {
      continue
    }
    const status = String((item as { status?: unknown }).status ?? "")
      .trim()
      .toLowerCase()
    if (status === "pending" || status === "in_progress") {
      openTodos += 1
    }
  }
  return openTodos
}

function shouldUseLlmContinuationFallback(text: string): boolean {
  return hasCompletionClosureCue(text) && hasActionableNextSliceCue(text) && hasDirectContinuationOfferCue(text)
}

function buildContinuationInstruction(): string {
  return "Does this assistant text mean the run should auto-continue now because work remains or the assistant is offering to execute the next slice immediately, even if the text also sounds complete? C=continue, S=stop, U=unclear."
}

function buildContinuationContext(text: string, continueIntentArmed: boolean, source: string): string {
  return [
    `continue_intent_armed=${continueIntentArmed ? "true" : "false"}`,
    `source=${source}`,
    `assistant_text=${text.trim() || "(empty)"}`,
  ].join("\n")
}

function hasPendingCueText(text: string, continueIntentArmed: boolean): boolean {
  if (!text.trim()) {
    return false
  }
  if (NEGATED_CONTINUE_INTENT_PATTERN.test(text) || isStopIntent(text)) {
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

async function resolvePendingContinuationDecision(options: {
  text: string
  continueIntentArmed: boolean
  source: "assistant_message" | "task_output" | "message_probe"
  sessionId: string
  directory: string
  traceId?: string
  decisionRuntime?: LlmDecisionRuntime
}): Promise<boolean> {
  const deterministicPending = hasPendingCueText(options.text, options.continueIntentArmed)
  if (deterministicPending) {
    return true
  }
  if (!options.sessionId || !options.decisionRuntime || !shouldUseLlmContinuationFallback(options.text)) {
    return false
  }
  let decision
  try {
    decision = await options.decisionRuntime.decide({
      hookId: "todo-continuation-enforcer",
      sessionId: options.sessionId,
      traceId: options.traceId,
      templateId: "todo-continuation-decision-v1",
      instruction: buildContinuationInstruction(),
      context: buildContinuationContext(options.text, options.continueIntentArmed, options.source),
      allowedChars: ["C", "S", "U"],
      decisionMeaning: {
        C: "continue_now",
        S: "no_pending",
        U: "unclear",
      },
      cacheKey: buildCompactDecisionCacheKey({
        prefix: "todo-continuation",
        parts: [options.source, options.continueIntentArmed ? "armed" : "unarmed"],
        text: buildContinuationContext(options.text, options.continueIntentArmed, options.source),
      }),
    })
  } catch (error) {
    writeGatewayEventAudit(options.directory, {
      hook: "todo-continuation-enforcer",
      stage: "state",
      reason_code: "llm_todo_continuation_decision_failed",
      session_id: options.sessionId,
      trace_id: options.traceId,
      llm_decision_mode: options.decisionRuntime.config.mode,
      decision_source: options.source,
      error: error instanceof Error ? error.message : String(error ?? "unknown_error"),
    })
    return false
  }
  if (!decision.accepted) {
    writeGatewayEventAudit(options.directory, {
      hook: "todo-continuation-enforcer",
      stage: "state",
      reason_code: "llm_todo_continuation_decision_skipped",
      session_id: options.sessionId,
      trace_id: options.traceId,
      llm_decision_mode: options.decisionRuntime.config.mode,
      decision_source: options.source,
      llm_decision_reason: decision.skippedReason || "not_accepted",
      error: decision.error,
    })
    return false
  }
  writeDecisionComparisonAudit({
    directory: options.directory,
    hookId: "todo-continuation-enforcer",
    sessionId: options.sessionId,
    traceId: options.traceId,
    mode: options.decisionRuntime.config.mode,
    deterministicMeaning: "no_pending",
    aiMeaning: decision.meaning || "no_pending",
    deterministicValue: "false",
    aiValue: decision.char === "C" ? "true" : decision.char === "U" ? "unclear" : "false",
  })
  writeGatewayEventAudit(options.directory, {
    hook: "todo-continuation-enforcer",
    stage: "state",
    reason_code: "llm_todo_continuation_decision_recorded",
    session_id: options.sessionId,
    trace_id: options.traceId,
    llm_decision_char: decision.char,
    llm_decision_meaning: decision.meaning,
    llm_decision_mode: options.decisionRuntime.config.mode,
    decision_source: options.source,
  })
  if (options.decisionRuntime.config.mode === "shadow" && decision.char === "C") {
    writeGatewayEventAudit(options.directory, {
      hook: "todo-continuation-enforcer",
      stage: "state",
      reason_code: "llm_todo_continuation_shadow_deferred",
      session_id: options.sessionId,
      trace_id: options.traceId,
      llm_decision_char: decision.char,
      llm_decision_meaning: decision.meaning,
      llm_decision_mode: options.decisionRuntime.config.mode,
      decision_source: options.source,
    })
    return false
  }
  return decision.char === "C"
}

function resolveTraceId(payload: {
  properties?: { trace_id?: string; traceId?: string }
  input?: { trace_id?: string; traceId?: string }
}): string | undefined {
  const candidates = [
    payload.properties?.trace_id,
    payload.properties?.traceId,
    payload.input?.trace_id,
    payload.input?.traceId,
  ]
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) {
      return value.trim()
    }
  }
  return undefined
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
    pendingSource: undefined,
    pendingTodoCount: 0,
    lastInjectedAt: 0,
    consecutiveFailures: 0,
    inFlight: false,
    markerProbeAttempted: false,
    continueIntentArmed: false,
    continueAckPending: false,
    lastTraceId: undefined,
  }
  store.set(sessionId, created)
  return created
}

async function injectContinueAcknowledgement(args: {
  client: NonNullable<GatewayClient["session"]>
  sessionId: string
  directory: string
}): Promise<boolean> {
  const safety = await inspectHookMessageSafety({
    session: args.client,
    sessionId: args.sessionId,
    directory: args.directory,
  })
  if (!safety.safe && safety.reason !== "assistant_turn_incomplete") {
    writeGatewayEventAudit(args.directory, {
      hook: "todo-continuation-enforcer",
      stage: "skip",
      reason_code: `todo_continuation_continue_ack_${safety.reason}`,
      session_id: args.sessionId,
    })
    return false
  }
  if (!safety.safe && safety.reason === "assistant_turn_incomplete") {
    writeGatewayEventAudit(args.directory, {
      hook: "todo-continuation-enforcer",
      stage: "state",
      reason_code: "todo_continuation_continue_ack_forcing_incomplete_parent_recovery",
      session_id: args.sessionId,
    })
  }
  const injected = await injectHookMessage({
    session: args.client,
    sessionId: args.sessionId,
    directory: args.directory,
    content:
      "[continuing now]\nI am resuming the next pending step now and will report back after the next checkpoint.",
  })
  writeGatewayEventAudit(args.directory, {
    hook: "todo-continuation-enforcer",
    stage: injected ? "inject" : "skip",
    reason_code: injected ? "todo_continuation_continue_ack_injected" : "todo_continuation_continue_ack_inject_failed",
    session_id: args.sessionId,
  })
  return injected
}

export function createTodoContinuationEnforcerHook(options: {
  directory: string
  enabled: boolean
  client?: GatewayClient
  stopGuard?: StopContinuationGuard
  decisionRuntime?: LlmDecisionRuntime
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
          state.continueAckPending = false
          state.pendingContinuation = false
          state.pendingSource = undefined
          state.pendingTodoCount = 0
          state.pendingSource = undefined
          state.pendingTodoCount = 0
          state.markerProbeAttempted = false
          return
        }
        if (isContinueIntent(prompt)) {
          state.continueIntentArmed = true
          state.continueAckPending = shouldAcknowledgeContinueIntent(prompt)
        } else {
          state.continueAckPending = false
        }
        state.markerProbeAttempted = false
        return
      }

      if (type === "tool.execute.after") {
        const eventPayload = (payload ?? {}) as ToolAfterPayload
        const sessionId = resolveSessionId(eventPayload)
        const tool = String(eventPayload.input?.tool ?? "").toLowerCase()
        if (!sessionId) {
          return
        }
        const state = getSessionState(sessionState, sessionId)
        state.lastTraceId = resolveTraceId(eventPayload)
        const directory = resolveDirectory(eventPayload, options.directory)
        const client = options.client?.session
        if (state.continueAckPending && client && tool !== "task") {
          state.continueAckPending = false
          await injectContinueAcknowledgement({
            client,
            sessionId,
            directory,
          })
        }
        if (tool === "todowrite") {
          const pendingTodoCount = parseTodoContinuationCount(eventPayload.output?.output)
          if (pendingTodoCount !== null) {
            state.pendingTodoCount = pendingTodoCount
            state.pendingContinuation = pendingTodoCount > 0
            state.markerProbeAttempted = true
            writeGatewayEventAudit(directory, {
              hook: "todo-continuation-enforcer",
              stage: "state",
              reason_code: "todo_continuation_todowrite_state_recorded",
              session_id: sessionId,
              trace_id: state.lastTraceId,
              open_todo_count: pendingTodoCount,
            })
          }
          return
        }
        if (tool !== "task" || typeof eventPayload.output?.output !== "string") {
          return
        }
        state.continueAckPending = false
        state.pendingContinuation = await resolvePendingContinuationDecision({
          text: eventPayload.output.output,
          continueIntentArmed: state.continueIntentArmed,
          source: "task_output",
          sessionId,
          directory,
          traceId: state.lastTraceId,
          decisionRuntime: options.decisionRuntime,
        })
        const hasExplicitCompletion = hasCompletionClosureCue(eventPayload.output.output)
        state.markerProbeAttempted = state.pendingContinuation || hasExplicitCompletion
        if (!state.pendingContinuation && !hasExplicitCompletion) {
          writeGatewayEventAudit(directory, {
            hook: "todo-continuation-enforcer",
            stage: "state",
            reason_code: "todo_continuation_task_probe_retained",
            session_id: sessionId,
            trace_id: state.lastTraceId,
          })
        }
        state.pendingSource = state.pendingContinuation ? "task_output" : undefined
        return
      }

      if (type === "message.updated") {
        const eventPayload = (payload ?? {}) as MessageUpdatedPayload
        const sessionId = resolveSessionId(eventPayload)
        if (!sessionId) {
          return
        }
        const info = eventPayload.properties?.info
        if (String(info?.role ?? "").toLowerCase().trim() !== "assistant") {
          return
        }
        const completed = Number.isFinite(Number(info?.time?.completed ?? Number.NaN))
        const failed = info?.error !== undefined && info?.error !== null
        if (!completed && !failed) {
          return
        }
        const state = getSessionState(sessionState, sessionId)
        state.lastTraceId = resolveTraceId(eventPayload)
        if (state.pendingTodoCount <= 0) {
          return
        }
        const text = assistantText({
          info: { role: "assistant" },
          parts: eventPayload.output?.parts ?? eventPayload.properties?.parts,
        })
        if (!text) {
          return
        }
        const shouldContinue = await resolvePendingContinuationDecision({
          text,
          continueIntentArmed: state.continueIntentArmed,
          source: "assistant_message",
          sessionId,
          directory: resolveDirectory(eventPayload, options.directory),
          traceId: state.lastTraceId,
          decisionRuntime: options.decisionRuntime,
        })
        if (!shouldContinue) {
          state.pendingContinuation = false
          state.pendingSource = undefined
          state.pendingTodoCount = 0
          state.markerProbeAttempted = false
          writeGatewayEventAudit(resolveDirectory(eventPayload, options.directory), {
            hook: "todo-continuation-enforcer",
            stage: "state",
            reason_code: "todo_continuation_assistant_message_no_pending",
            session_id: sessionId,
            trace_id: state.lastTraceId,
          })
          return
        }
        state.pendingContinuation = true
        state.pendingSource = "assistant_message"
        state.markerProbeAttempted = false
        writeGatewayEventAudit(resolveDirectory(eventPayload, options.directory), {
          hook: "todo-continuation-enforcer",
          stage: "state",
          reason_code: "todo_continuation_assistant_message_with_open_todos",
          session_id: sessionId,
          trace_id: state.lastTraceId,
          open_todo_count: state.pendingTodoCount,
        })
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
      const state = getSessionState(sessionState, sessionId)
      const ackClient = options.client?.session
      if (state.continueAckPending && ackClient) {
        state.continueAckPending = false
        const acknowledged = await injectContinueAcknowledgement({
          client: ackClient,
          sessionId,
          directory,
        })
        if (acknowledged) {
          return
        }
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

      let pending = state.pendingContinuation || state.pendingTodoCount > 0
      let probeMessages:
        | Array<{
            info?: { role?: string; error?: unknown; time?: { completed?: number } }
            parts?: Array<{ type?: string; text?: string; synthetic?: boolean }>
          }>
        | undefined
      const client = options.client?.session
      if (!pending && client && !state.markerProbeAttempted) {
        try {
          const response = await client.messages({
            path: { id: sessionId },
            query: { directory },
          })
          const messages = Array.isArray(response.data) ? response.data : []
          probeMessages = messages
          pending = hasPendingCue(messages, state.continueIntentArmed)
          if (!pending) {
            for (let i = messages.length - 1; i >= 0; i -= 1) {
              const text = assistantText(messages[i])
              if (!text) {
                continue
              }
              pending = await resolvePendingContinuationDecision({
                text,
                continueIntentArmed: state.continueIntentArmed,
                source: "message_probe",
                sessionId,
                directory,
                traceId: state.lastTraceId,
                decisionRuntime: options.decisionRuntime,
              })
              break
            }
          }
          state.markerProbeAttempted = true
          state.pendingSource = pending ? "message_probe" : undefined
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

      const safety =
        state.pendingSource === "task_output"
          ? { safe: true, reason: "ok" as const }
          : await inspectHookMessageSafety({
              session: client,
              sessionId,
              directory,
              messages: probeMessages,
            })
      if (!safety.safe) {
        state.markerProbeAttempted = false
        writeGatewayEventAudit(directory, {
          hook: "todo-continuation-enforcer",
          stage: "skip",
          reason_code: `todo_continuation_${safety.reason}`,
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
          state.pendingContinuation = false
          state.pendingTodoCount = 0
          state.pendingSource = undefined
          state.continueIntentArmed = false
          state.markerProbeAttempted = false
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
