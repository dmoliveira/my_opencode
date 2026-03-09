import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import { injectHookMessage } from "../hook-message-injector/index.js"
import type { GatewayHook } from "../registry.js"

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
  }): Promise<{
    data?: Array<{
      info?: { role?: string }
      parts?: Array<{ type?: string; text?: string }>
    }>
  }>
}

interface HookPayload {
  directory?: string
  properties?: {
    sessionID?: string
    sessionId?: string
    info?: { id?: string }
  }
  input?: {
    sessionID?: string
    sessionId?: string
    command?: string
  }
}

const VISIBLE_NOTE_MARKER = "[Runtime session]"

function resolveSessionId(payload: HookPayload): string {
  const candidates = [
    payload.input?.sessionID,
    payload.input?.sessionId,
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

function buildVisibleNote(sessionId: string): string {
  return `${VISIBLE_NOTE_MARKER}
${sessionId}`
}

async function recentVisibleNoteExists(args: {
  session?: SessionClient
  sessionId: string
  directory: string
  note: string
}): Promise<boolean> {
  if (typeof args.session?.messages !== "function") {
    return false
  }
  try {
    const response = await args.session.messages({
      path: { id: args.sessionId },
      query: { directory: args.directory },
    })
    const messages = Array.isArray(response.data) ? response.data : []
    for (let idx = messages.length - 1; idx >= 0; idx -= 1) {
      const message = messages[idx]
      const parts = Array.isArray(message?.parts) ? message.parts : []
      for (const part of parts) {
        if (part?.type === "text" && String(part.text ?? "").trim() === args.note) {
          return true
        }
      }
    }
  } catch {
    return false
  }
  return false
}

export function createSessionRuntimeVisibleNoteHook(options: {
  directory: string
  enabled: boolean
  client?: { session?: SessionClient }
}): GatewayHook {
  const injectedSessions = new Set<string>()
  const compactedSessions = new Set<string>()

  return {
    id: "session-runtime-visible-note",
    priority: 292,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }
      const eventPayload = (payload ?? {}) as HookPayload
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = resolveSessionId(eventPayload)
      if (!sessionId) {
        return
      }

      if (type === "session.deleted") {
        injectedSessions.delete(sessionId)
        compactedSessions.delete(sessionId)
        return
      }

      const command = String(eventPayload.input?.command ?? "").trim().toLowerCase()
      const compacted =
        type === "session.compacted" || (type === "command.execute.after" && command === "compact")
      const shouldInject = type === "session.created" || type === "session.updated" || compacted
      if (!shouldInject) {
        return
      }

      if (!compacted) {
        compactedSessions.delete(sessionId)
      }
      if (compacted) {
        if (compactedSessions.has(sessionId)) {
          return
        }
        compactedSessions.add(sessionId)
        injectedSessions.delete(sessionId)
      }
      if (injectedSessions.has(sessionId)) {
        return
      }

      const client = options.client?.session
      if (!client) {
        return
      }
      const note = buildVisibleNote(sessionId)
      if (!compacted && (await recentVisibleNoteExists({ session: client, sessionId, directory, note }))) {
        injectedSessions.add(sessionId)
        return
      }

      const injected = await injectHookMessage({
        session: client,
        sessionId,
        content: note,
        directory,
      })
      if (!injected) {
        writeGatewayEventAudit(directory, {
          hook: "session-runtime-visible-note",
          stage: "inject",
          reason_code: "session_runtime_visible_note_inject_failed",
          session_id: sessionId,
          event_type: type,
        })
        return
      }
      injectedSessions.add(sessionId)
      writeGatewayEventAudit(directory, {
        hook: "session-runtime-visible-note",
        stage: "inject",
        reason_code: "session_runtime_visible_note_injected",
        session_id: sessionId,
        event_type: type,
      })
    },
  }
}
