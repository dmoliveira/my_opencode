import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import { findNearestFile } from "../directory-context/finder.js"
import type { GatewayHook } from "../registry.js"

interface ToolPayload {
  input?: {
    sessionID?: string
    sessionId?: string
  }
  output?: {
    output?: unknown
  }
  directory?: string
}

interface EventPayload {
  properties?: {
    info?: { id?: string }
  }
}

// Resolves stable session id from tool payload.
function resolveSessionId(payload: ToolPayload): string {
  const candidates = [payload.input?.sessionID, payload.input?.sessionId]
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) {
      return value.trim()
    }
  }
  return ""
}

// Creates README injector hook for local docs context hints.
export function createDirectoryReadmeInjectorHook(options: {
  directory: string
  enabled: boolean
}): GatewayHook {
  const readmePathBySession = new Map<string, string>()
  return {
    id: "directory-readme-injector",
    priority: 300,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }
      if (type === "session.deleted") {
        const eventPayload = (payload ?? {}) as EventPayload
        const sessionId = eventPayload.properties?.info?.id
        if (typeof sessionId === "string" && sessionId.trim()) {
          readmePathBySession.delete(sessionId.trim())
        }
        return
      }
      if (type === "tool.execute.before") {
        const eventPayload = (payload ?? {}) as ToolPayload
        const directory =
          typeof eventPayload.directory === "string" && eventPayload.directory.trim()
            ? eventPayload.directory
            : options.directory
        const sessionId = resolveSessionId(eventPayload)
        if (!sessionId) {
          return
        }
        const path = findNearestFile(directory, "README.md")
        if (path) {
          readmePathBySession.set(sessionId, path)
        }
        return
      }
      if (type !== "tool.execute.after") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolPayload
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = resolveSessionId(eventPayload)
      const path = sessionId ? readmePathBySession.get(sessionId) : null
      if (!path || typeof eventPayload.output?.output !== "string") {
        return
      }
      eventPayload.output.output = `${eventPayload.output.output}\n\nLocal README context loaded from: ${path}`
      writeGatewayEventAudit(directory, {
        hook: "directory-readme-injector",
        stage: "state",
        reason_code: "directory_readme_context_injected",
        session_id: sessionId,
      })
    },
  }
}
