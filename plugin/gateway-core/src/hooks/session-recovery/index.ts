import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import { injectHookMessage, inspectHookMessageSafety } from "../hook-message-injector/index.js"
import type { GatewayHook } from "../registry.js"
import { readCombinedToolAfterOutputText } from "../shared/tool-after-output.js"

// Declares minimal session prompt API used for recovery resume.
interface GatewayClient {
  session?: {
    messages?(args: {
      path: { id: string }
      query?: { directory?: string }
    }): Promise<{
      data?: Array<{
        info?: {
          role?: string
          agent?: string
          model?: { providerID?: string; modelID?: string; variant?: string }
          providerID?: string
          modelID?: string
          error?: unknown
          time?: { completed?: number }
        }
        parts?: Array<{
          type?: string
          text?: string
          synthetic?: boolean
          tool?: string
          state?: {
            status?: string
            error?: unknown
            metadata?: { sessionId?: string; sessionID?: string }
          }
        }>
      }>
    }>
    promptAsync(args: {
      path: { id: string }
      body: {
        parts: Array<{ type: string; text: string }>
        agent?: string
        model?: { providerID: string; modelID: string; variant?: string }
      }
      query?: { directory?: string }
    }): Promise<void>
  }
}

// Declares event payload shape for session recovery.
interface SessionEventPayload {
  directory?: string
  properties?: {
    sessionID?: string
    sessionId?: string
    info?: {
      id?: string
      error?: unknown
    }
    error?: unknown
  }
}

interface ToolAfterPayload {
  directory?: string
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
  }
  output?: {
    output?: unknown
  }
}

interface ToolBeforePayload {
  directory?: string
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
  }
}

interface MessageUpdatedPayload {
  directory?: string
  properties?: {
    info?: {
      role?: string
      sessionID?: string
      sessionId?: string
      error?: unknown
      time?: { completed?: number }
    }
  }
}

interface PendingQuestionState {
  tool: string
  startedAt: number
  lastUpdatedAt: number
}

const STALE_QUESTION_PREVENTION_MS = 60_000

function nowMs(): number {
  return Date.now()
}

function resolveToolSessionId(payload: {
  input?: { sessionID?: string; sessionId?: string }
}): string {
  return String(payload.input?.sessionID ?? payload.input?.sessionId ?? "").trim()
}

function resolveMessageSessionId(payload: MessageUpdatedPayload): string {
  return String(
    payload.properties?.info?.sessionID ?? payload.properties?.info?.sessionId ?? "",
  ).trim()
}

function normalizeToolName(raw: unknown): string {
  return String(raw ?? "").trim().toLowerCase()
}

function isQuestionTool(raw: unknown): boolean {
  const tool = normalizeToolName(raw)
  return tool === "question" || tool === "askuserquestion"
}

// Returns true when event error resembles recoverable transient session failure.
function isRecoverableError(error: unknown): boolean {
  const candidate =
    error && typeof error === "object" && "message" in (error as Record<string, unknown>)
      ? String((error as Record<string, unknown>).message ?? "")
      : String(error ?? "")
  const message = candidate.toLowerCase()
  return (
    message.includes("context") ||
    message.includes("rate limit") ||
    message.includes("temporar") ||
    message.includes("network") ||
    message.includes("timeout")
  )
}

// Resolves session id from error event payload.
function resolveSessionId(payload: SessionEventPayload): string {
  const candidates = [
    payload.properties?.sessionID,
    payload.properties?.sessionId,
    payload.properties?.info?.id,
  ]
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) {
      return value.trim()
    }
  }
  return ""
}

function looksLikeDelegatedTaskAbort(output: unknown): {
  aborted: boolean
  childSessionId: string
} {
  const text = readCombinedToolAfterOutputText(output)
  const record = output && typeof output === "object" ? (output as Record<string, unknown>) : null
  const nested =
    record && record.output && typeof record.output === "object"
      ? (record.output as Record<string, unknown>)
      : record
  const state = nested?.state && typeof nested.state === "object" ? (nested.state as Record<string, unknown>) : null
  const metadata =
    state?.metadata && typeof state.metadata === "object" ? (state.metadata as Record<string, unknown>) : null
  const status = String(state?.status ?? "").trim().toLowerCase()
  const error = `${String(state?.error ?? "")}\n${String(nested?.error ?? "")}\n${text}`.toLowerCase()
  const childSessionId = String(metadata?.sessionId ?? metadata?.sessionID ?? "").trim()
  return {
    aborted:
      status === "error" &&
      error.includes("tool execution aborted"),
    childSessionId,
  }
}

function looksLikeSilentDelegatedAbortFromHistory(messages: Array<{
  info?: { role?: string; error?: unknown; time?: { completed?: number } }
  parts?: Array<{
    type?: string
    text?: string
    synthetic?: boolean
    tool?: string
    state?: { status?: string; error?: unknown; metadata?: { sessionId?: string; sessionID?: string } }
  }>
}>): { matched: boolean; childSessionId: string } {
  for (let idx = messages.length - 1; idx >= 0; idx -= 1) {
    const message = messages[idx]
    if (message?.info?.role !== "assistant") {
      continue
    }
    const errored = message.info?.error !== undefined && message.info?.error !== null
    const completed = Number.isFinite(Number(message.info?.time?.completed ?? Number.NaN))
    if (!errored || completed) {
      return { matched: false, childSessionId: "" }
    }
    const parts = Array.isArray(message.parts) ? message.parts : []
    const hasVisibleText = parts.some(
      (part) =>
        part?.type === "text" &&
        typeof part.text === "string" &&
        part.text.trim() &&
        !part.synthetic,
    )
    if (hasVisibleText) {
      return { matched: false, childSessionId: "" }
    }
    for (let partIndex = parts.length - 1; partIndex >= 0; partIndex -= 1) {
      const part = parts[partIndex]
      if (part?.type !== "tool" || String(part.tool ?? "").trim().toLowerCase() !== "task") {
        continue
      }
      const status = String(part.state?.status ?? "").trim().toLowerCase()
      const error = `${String(part.state?.error ?? "")}
${String(message.info?.error ?? "")}`.toLowerCase()
      if ((status === "error" || status === "failed") && error.includes("aborted")) {
        return {
          matched: true,
          childSessionId: String(
            part.state?.metadata?.sessionId ?? part.state?.metadata?.sessionID ?? "",
          ).trim(),
        }
      }
    }
    return { matched: false, childSessionId: "" }
  }
  return { matched: false, childSessionId: "" }
}

function looksLikeSilentQuestionStallFromHistory(messages: Array<{
  info?: { role?: string; error?: unknown; time?: { completed?: number } }
  parts?: Array<{
    type?: string
    text?: string
    synthetic?: boolean
    tool?: string
    state?: { status?: string }
  }>
}>): { matched: boolean; tool: string } {
  const message = messages.at(-1)
  if (message?.info?.role !== "assistant") {
    return { matched: false, tool: "" }
  }
  const errored = message.info?.error !== undefined && message.info?.error !== null
  const completed = Number.isFinite(Number(message.info?.time?.completed ?? Number.NaN))
  if (errored || completed) {
    return { matched: false, tool: "" }
  }
  const parts = Array.isArray(message.parts) ? message.parts : []
  const hasVisibleText = parts.some(
    (part) =>
      part?.type === "text" &&
      typeof part.text === "string" &&
      part.text.trim() &&
      !part.synthetic,
  )
  if (hasVisibleText) {
    return { matched: false, tool: "" }
  }
  const lastToolPart = [...parts].reverse().find((part) => part?.type === "tool")
  const tool = String(lastToolPart?.tool ?? "").trim().toLowerCase()
  if (tool !== "question" && tool !== "askuserquestion") {
    return { matched: false, tool: "" }
  }
  const status = String(lastToolPart?.state?.status ?? "").trim().toLowerCase()
  if (status !== "running") {
    return { matched: false, tool: "" }
  }
  return { matched: true, tool }
}

async function injectRecoveryMessage(args: {
  session: NonNullable<GatewayClient["session"]>
  sessionId: string
  directory: string
  hook: string
  reasonCode: string
  content: string
  allowIncompleteAssistantTurn?: boolean
}): Promise<boolean> {
  const safety = await inspectHookMessageSafety({
    session: args.session,
    sessionId: args.sessionId,
    directory: args.directory,
  })
  if (
    !safety.safe &&
    !(args.allowIncompleteAssistantTurn && safety.reason === "assistant_turn_incomplete")
  ) {
    writeGatewayEventAudit(args.directory, {
      hook: args.hook,
      stage: "skip",
      reason_code: `${args.reasonCode}_${safety.reason}`,
      session_id: args.sessionId,
    })
    return false
  }
  if (!safety.safe && safety.reason === "assistant_turn_incomplete") {
    writeGatewayEventAudit(args.directory, {
      hook: args.hook,
      stage: "state",
      reason_code: `${args.reasonCode}_forcing_incomplete_parent_recovery`,
      session_id: args.sessionId,
    })
  }
  const injected = await injectHookMessage({
    session: args.session,
    sessionId: args.sessionId,
    content: args.content,
    directory: args.directory,
  })
  if (!injected) {
    writeGatewayEventAudit(args.directory, {
      hook: args.hook,
      stage: "skip",
      reason_code: `${args.reasonCode}_inject_failed`,
      session_id: args.sessionId,
    })
    return false
  }
  writeGatewayEventAudit(args.directory, {
    hook: args.hook,
    stage: "state",
    reason_code: `${args.reasonCode}_injected`,
    session_id: args.sessionId,
  })
  return true
}

// Creates session recovery hook that attempts one auto-resume per active error session.
export function createSessionRecoveryHook(options: {
  directory: string
  client?: GatewayClient
  enabled: boolean
  autoResume: boolean
}): GatewayHook {
  const recoveringSessions = new Set<string>()
  const pendingQuestions = new Map<string, PendingQuestionState>()
  return {
    id: "session-recovery",
    priority: 280,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }
      const eventPayload = (payload ?? {}) as SessionEventPayload
      if (type === "session.deleted") {
        const sessionId = resolveSessionId(eventPayload)
        if (sessionId) {
          recoveringSessions.delete(sessionId)
          pendingQuestions.delete(sessionId)
        }
        return
      }
      if (type === "message.updated") {
        const messagePayload = (payload ?? {}) as MessageUpdatedPayload
        const sessionId = resolveMessageSessionId(messagePayload)
        if (!sessionId) {
          return
        }
        const info = messagePayload.properties?.info
        const role = String(info?.role ?? "").trim().toLowerCase()
        if (role === "user") {
          pendingQuestions.delete(sessionId)
          return
        }
        if (role !== "assistant") {
          return
        }
        const completed = Number.isFinite(Number(info?.time?.completed ?? Number.NaN))
        const errored = info?.error !== undefined && info?.error !== null
        if (completed || errored) {
          pendingQuestions.delete(sessionId)
          return
        }
        const existing = pendingQuestions.get(sessionId)
        if (!existing) {
          return
        }
        pendingQuestions.set(sessionId, {
          ...existing,
          lastUpdatedAt: nowMs(),
        })
        return
      }
      if (type === "tool.execute.before") {
        const toolPayload = (payload ?? {}) as ToolBeforePayload
        const sessionId = resolveToolSessionId(toolPayload)
        if (!sessionId || !isQuestionTool(toolPayload.input?.tool)) {
          return
        }
        pendingQuestions.set(sessionId, {
          tool: normalizeToolName(toolPayload.input?.tool),
          startedAt: nowMs(),
          lastUpdatedAt: nowMs(),
        })
        return
      }
      if (type === "tool.execute.before.error") {
        const toolPayload = (payload ?? {}) as ToolBeforePayload
        const sessionId = resolveToolSessionId(toolPayload)
        if (!sessionId || !isQuestionTool(toolPayload.input?.tool)) {
          return
        }
        pendingQuestions.delete(sessionId)
        return
      }
      if (type === "session.idle") {
        const directory =
          typeof eventPayload.directory === "string" && eventPayload.directory.trim()
            ? eventPayload.directory
            : options.directory
        const sessionId = resolveSessionId(eventPayload)
        if (!sessionId || recoveringSessions.has(sessionId) || !options.autoResume) {
          return
        }
        const client = options.client?.session
        if (!client || typeof client.messages !== "function") {
          return
        }
        const pendingQuestion = pendingQuestions.get(sessionId)
        if (pendingQuestion) {
          const ageMs = Math.max(0, nowMs() - Math.max(pendingQuestion.startedAt, pendingQuestion.lastUpdatedAt))
          if (ageMs < STALE_QUESTION_PREVENTION_MS) {
            writeGatewayEventAudit(directory, {
              hook: "session-recovery",
              stage: "skip",
              reason_code: "stale_question_tool_prevention_not_stale",
              session_id: sessionId,
            })
            return
          }
        }
        try {
          const response = await client.messages({
            path: { id: sessionId },
            query: { directory },
          })
          const messages = Array.isArray(response.data) ? response.data : []
          const silentAbort = looksLikeSilentDelegatedAbortFromHistory(messages)
          if (silentAbort.matched) {
            recoveringSessions.add(sessionId)
            try {
              await injectRecoveryMessage({
                session: client,
                sessionId,
                directory,
                hook: "session-recovery",
                reasonCode: "silent_parent_after_delegation_abort_recovery",
                allowIncompleteAssistantTurn: true,
                content: silentAbort.childSessionId
                  ? `[stuck delegated abort detected during idle - continuing in parent turn]\nchild_session: ${silentAbort.childSessionId}`
                  : "[stuck delegated abort detected during idle - continuing in parent turn]",
              })
            } finally {
              recoveringSessions.delete(sessionId)
            }
            return
          }
          const silentQuestion = looksLikeSilentQuestionStallFromHistory(messages)
          if (!silentQuestion.matched) {
            return
          }
          recoveringSessions.add(sessionId)
          try {
            await injectRecoveryMessage({
              session: client,
              sessionId,
              directory,
              hook: "session-recovery",
              reasonCode: "stale_question_tool_recovery",
              allowIncompleteAssistantTurn: true,
              content:
                "[stuck question tool detected during idle - interactive prompt did not complete]\nPlease reply with your preference in a normal message and I will continue.",
            })
          } finally {
            recoveringSessions.delete(sessionId)
            pendingQuestions.delete(sessionId)
          }
        } catch {
          writeGatewayEventAudit(directory, {
            hook: "session-recovery",
            stage: "skip",
            reason_code: "idle_history_recovery_failed",
            session_id: sessionId,
          })
        }
        return
      }
      if (type === "tool.execute.after") {
        const toolPayload = (payload ?? {}) as ToolAfterPayload
        const sessionId = String(toolPayload.input?.sessionID ?? toolPayload.input?.sessionId ?? "").trim()
        if (sessionId && isQuestionTool(toolPayload.input?.tool)) {
          pendingQuestions.delete(sessionId)
          return
        }
        const directory =
          typeof toolPayload.directory === "string" && toolPayload.directory.trim()
            ? toolPayload.directory
            : options.directory
        if (!sessionId || String(toolPayload.input?.tool ?? "").trim().toLowerCase() !== "task") {
          return
        }
        if (recoveringSessions.has(sessionId)) {
          return
        }
        const client = options.client?.session
        if (!client || !options.autoResume) {
          return
        }
        const delegatedAbort = looksLikeDelegatedTaskAbort(toolPayload.output?.output)
        if (!delegatedAbort.aborted) {
          return
        }
        recoveringSessions.add(sessionId)
        try {
          await injectRecoveryMessage({
            session: client,
            sessionId,
            directory,
            hook: "session-recovery",
            reasonCode: "delegated_task_abort_recovery",
            allowIncompleteAssistantTurn: true,
            content: delegatedAbort.childSessionId
              ? `[delegated task aborted - continuing in parent turn]\nchild_session: ${delegatedAbort.childSessionId}`
              : "[delegated task aborted - continuing in parent turn]",
          })
        } catch {
          writeGatewayEventAudit(directory, {
            hook: "session-recovery",
            stage: "skip",
            reason_code: "delegated_task_abort_recovery_failed",
            session_id: sessionId,
          })
        } finally {
          recoveringSessions.delete(sessionId)
        }
        return
      }
      if (type !== "session.error") {
        return
      }
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = resolveSessionId(eventPayload)
      if (!sessionId) {
        writeGatewayEventAudit(directory, {
          hook: "session-recovery",
          stage: "skip",
          reason_code: "missing_session_id",
        })
        return
      }
      if (recoveringSessions.has(sessionId)) {
        writeGatewayEventAudit(directory, {
          hook: "session-recovery",
          stage: "skip",
          reason_code: "recovery_in_progress",
          session_id: sessionId,
        })
        return
      }
      const error = eventPayload.properties?.error ?? eventPayload.properties?.info?.error
      if (!isRecoverableError(error)) {
        writeGatewayEventAudit(directory, {
          hook: "session-recovery",
          stage: "skip",
          reason_code: "error_not_recoverable",
          session_id: sessionId,
        })
        return
      }
      if (!options.autoResume) {
        writeGatewayEventAudit(directory, {
          hook: "session-recovery",
          stage: "skip",
          reason_code: "auto_resume_disabled",
          session_id: sessionId,
        })
        return
      }
      const client = options.client?.session
      if (!client) {
        writeGatewayEventAudit(directory, {
          hook: "session-recovery",
          stage: "skip",
          reason_code: "session_client_unavailable",
          session_id: sessionId,
        })
        return
      }
      recoveringSessions.add(sessionId)
      try {
        await injectRecoveryMessage({
          session: client,
          sessionId,
          directory,
          hook: "session-recovery",
          reasonCode: "session_recovery_resume",
          content: "[session recovered - continuing previous task]",
        })
      } catch {
        writeGatewayEventAudit(directory, {
          hook: "session-recovery",
          stage: "skip",
          reason_code: "session_recovery_resume_failed",
          session_id: sessionId,
        })
      } finally {
        recoveringSessions.delete(sessionId)
      }
    },
  }
}
