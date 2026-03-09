import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import {
  clearValidationEvidence,
  markValidationEvidence,
} from "./evidence.js"
import { classifyValidationCommand } from "../shared/validation-command-matcher.js"

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

// Resolves stable session id across gateway payload variants.
function sessionId(payload: {
  input?: { sessionID?: string; sessionId?: string }
  properties?: { info?: { id?: string } }
}): string {
  const candidates = [payload.input?.sessionID, payload.input?.sessionId, payload.properties?.info?.id]
  for (const item of candidates) {
    if (typeof item === "string" && item.trim()) {
      return item.trim()
    }
  }
  return ""
}

// Returns true when command output indicates failure.
function commandFailed(output: string): boolean {
  const lower = output.toLowerCase()
  if (
    /npm err!|command failed|traceback|exception|cannot find|not found|elifecycle|exit code \d+/i.test(
      lower,
    )
  ) {
    return true
  }
  if (/\bfailed\b/i.test(lower) && !/\b(?:0\s+failed|failed\s*:\s*0|failures?\s*:\s*0)\b/i.test(lower)) {
    return true
  }
  return false
}

// Creates validation evidence ledger hook to track successful validation commands.
export function createValidationEvidenceLedgerHook(options: {
  directory: string
  enabled: boolean
}): GatewayHook {
  const pendingCommandsBySession = new Map<string, string[]>()
  return {
    id: "validation-evidence-ledger",
    priority: 330,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }
      if (type === "session.deleted") {
        const eventPayload = (payload ?? {}) as SessionDeletedPayload
        const sid = sessionId(eventPayload)
        if (!sid) {
          return
        }
        pendingCommandsBySession.delete(sid)
        clearValidationEvidence(sid)
        return
      }
      if (type === "tool.execute.before") {
        const eventPayload = (payload ?? {}) as ToolBeforePayload
        const tool = String(eventPayload.input?.tool ?? "").toLowerCase()
        if (tool !== "bash") {
          return
        }
        const sid = sessionId(eventPayload)
        if (!sid) {
          return
        }
        const command = String(eventPayload.output?.args?.command ?? "").trim()
        if (!command) {
          return
        }
        const queue = pendingCommandsBySession.get(sid) ?? []
        queue.push(command)
        pendingCommandsBySession.set(sid, queue)
        return
      }
      if (type !== "tool.execute.after") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolAfterPayload
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase()
      if (tool !== "bash") {
        return
      }
      const sid = sessionId(eventPayload)
      if (!sid) {
        return
      }
      const queue = pendingCommandsBySession.get(sid) ?? []
      const command = queue.shift() ?? ""
      if (queue.length > 0) {
        pendingCommandsBySession.set(sid, queue)
      } else {
        pendingCommandsBySession.delete(sid)
      }
      if (!command) {
        return
      }
      if (typeof eventPayload.output?.output !== "string") {
        return
      }
      const categories = classifyValidationCommand(command)
      if (categories.length === 0) {
        return
      }
      if (commandFailed(eventPayload.output.output)) {
        return
      }
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      markValidationEvidence(sid, categories, directory)
      writeGatewayEventAudit(directory, {
        hook: "validation-evidence-ledger",
        stage: "state",
        reason_code: "validation_evidence_recorded",
        session_id: sid,
        evidence: categories.join(","),
      })
    },
  }
}
