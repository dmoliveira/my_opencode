import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"

interface ToolBeforePayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
  }
  output?: {
    args?: { command?: string }
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
  directory?: string
}

interface SessionDeletedPayload {
  properties?: {
    info?: { id?: string }
  }
}

// Resolves stable session id from event payload.
function resolveSessionId(payload: {
  input?: { sessionID?: string; sessionId?: string }
  properties?: { info?: { id?: string } }
}): string {
  const candidates = [payload.input?.sessionID, payload.input?.sessionId, payload.properties?.info?.id]
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) {
      return value.trim()
    }
  }
  return ""
}

// Classifies a command when it belongs to parallelizable diagnostics trio.
function diagnosticCommand(command: string): string {
  const value = command.trim().toLowerCase()
  if (/^git\s+status\b/.test(value)) {
    return "git-status"
  }
  if (/^git\s+(-\-no-pager\s+)?diff\b/.test(value)) {
    return "git-diff"
  }
  if (/^git\s+(-\-no-pager\s+)?log\b/.test(value)) {
    return "git-log"
  }
  return ""
}

// Creates detector hook that nudges parallel execution for independent diagnostics.
export function createParallelOpportunityDetectorHook(options: {
  directory: string
  enabled: boolean
}): GatewayHook {
  const commandBySession = new Map<string, string>()
  const seenDiagnosticsBySession = new Map<string, Set<string>>()
  const remindedBySession = new Set<string>()
  return {
    id: "parallel-opportunity-detector",
    priority: 332,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }
      if (type === "session.deleted") {
        const eventPayload = (payload ?? {}) as SessionDeletedPayload
        const sid = resolveSessionId(eventPayload)
        if (sid) {
          commandBySession.delete(sid)
          seenDiagnosticsBySession.delete(sid)
          remindedBySession.delete(sid)
        }
        return
      }
      if (type === "tool.execute.before") {
        const eventPayload = (payload ?? {}) as ToolBeforePayload
        if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash") {
          return
        }
        const sid = resolveSessionId(eventPayload)
        if (!sid) {
          return
        }
        const command = String(eventPayload.output?.args?.command ?? "").trim()
        if (!command) {
          commandBySession.delete(sid)
          return
        }
        commandBySession.set(sid, command)
        return
      }
      if (type !== "tool.execute.after") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolAfterPayload
      if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash") {
        return
      }
      if (typeof eventPayload.output?.output !== "string") {
        return
      }
      const sid = resolveSessionId(eventPayload)
      if (!sid || remindedBySession.has(sid)) {
        return
      }
      const command = commandBySession.get(sid) ?? ""
      const kind = diagnosticCommand(command)
      if (!kind) {
        return
      }
      const seen = seenDiagnosticsBySession.get(sid) ?? new Set<string>()
      seen.add(kind)
      seenDiagnosticsBySession.set(sid, seen)
      if (seen.size !== 1) {
        return
      }
      eventPayload.output.output +=
        "\n\n[parallel-opportunity-detector] Independent git diagnostics can run in parallel: `git status`, `git diff`, and `git log`."
      remindedBySession.add(sid)
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      writeGatewayEventAudit(directory, {
        hook: "parallel-opportunity-detector",
        stage: "state",
        reason_code: "parallel_opportunity_detected",
        session_id: sid,
      })
    },
  }
}
