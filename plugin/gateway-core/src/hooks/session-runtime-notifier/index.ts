import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"

interface ToastClient {
  showToast(args?: {
    title?: string
    message?: string
    variant?: "info" | "success" | "warning" | "error"
    duration?: number
    directory?: string
    workspace?: string
  }): Promise<unknown>
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

async function safeToast(client: ToastClient | undefined, args: Parameters<ToastClient["showToast"]>[0]): Promise<boolean> {
  if (!client?.showToast) {
    return false
  }
  try {
    await client.showToast(args)
    return true
  } catch {
    return false
  }
}

export function createSessionRuntimeNotifierHook(options: {
  directory: string
  enabled: boolean
  durationMs: number
  client?: { tui?: ToastClient }
}): GatewayHook {
  const announcedSessions = new Set<string>()
  const compactedSessions = new Set<string>()

  return {
    id: "session-runtime-notifier",
    priority: 293,
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

      if (type === "session.deleted") {
        if (sessionId) {
          announcedSessions.delete(sessionId)
          compactedSessions.delete(sessionId)
        }
        return
      }

      if (type === "chat.message" || type === "session.created" || type === "session.updated") {
        compactedSessions.delete(sessionId)
        if (!sessionId || announcedSessions.has(sessionId)) {
          return
        }
        const shown = await safeToast(options.client?.tui, {
          directory,
          title: "Runtime session",
          message: sessionId,
          variant: "info",
          duration: options.durationMs,
        })
        if (!shown) {
          return
        }
        announcedSessions.add(sessionId)
        writeGatewayEventAudit(directory, {
          hook: "session-runtime-notifier",
          stage: "notify",
          reason_code: "session_runtime_toast_shown",
          session_id: sessionId,
          event_type: type,
        })
        return
      }

      const command = String(eventPayload.input?.command ?? "").trim().toLowerCase()
      const compacted = type === "session.compacted" || (type === "command.execute.after" && command === "compact")
      if (!compacted || !sessionId) {
        return
      }
      if (compactedSessions.has(sessionId)) {
        return
      }
      compactedSessions.add(sessionId)
      announcedSessions.delete(sessionId)
      const shown = await safeToast(options.client?.tui, {
        directory,
        title: "Session compacted",
        message: `Runtime session: ${sessionId}`,
        variant: "info",
        duration: options.durationMs,
      })
      if (!shown) {
        return
      }
      writeGatewayEventAudit(directory, {
        hook: "session-runtime-notifier",
        stage: "notify",
        reason_code: "session_runtime_compaction_toast_shown",
        session_id: sessionId,
      })
    },
  }
}
