import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import { REASON_CODES } from "../../bridge/reason-codes.js"
import type { GatewayHook } from "../registry.js"

const COMPACTION_CONTEXT_TEXT = [
  "[COMPACTION CONTEXT]",
  "When summarizing this session, include:",
  "1) User requests as originally stated",
  "2) Final goal",
  "3) Work completed",
  "4) Remaining tasks",
  "5) Active working context (files, code in progress, external refs, state)",
  "6) Explicit constraints (verbatim only)",
  "7) Verification state (current agent, completed checks, pending checks, blockers)",
].join("\n")

interface CommandPayload {
  directory?: string
  input?: {
    sessionID?: string
    command?: string
  }
  output?: {
    parts?: Array<{ type: string; text?: string }>
  }
}

// Returns true when command should receive compaction context instruction.
function isCompactionCommand(command: string): boolean {
  const normalized = command.trim().toLowerCase().replace(/^\//, "")
  return normalized === "summarize" || normalized === "compact"
}

// Returns true when output already contains compaction context marker.
function hasCompactionMarker(parts: Array<{ type: string; text?: string }>): boolean {
  return parts.some(
    (part) => part.type === "text" && typeof part.text === "string" && part.text.includes("[COMPACTION CONTEXT]"),
  )
}

// Creates compaction context injector for summarize-like commands.
export function createCompactionContextInjectorHook(options: {
  directory: string
  enabled: boolean
}): GatewayHook {
  return {
    id: "compaction-context-injector",
    priority: 298,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "command.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as CommandPayload
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const command = typeof eventPayload.input?.command === "string" ? eventPayload.input.command : ""
      if (!isCompactionCommand(command)) {
        return
      }
      if (eventPayload.output && !Array.isArray(eventPayload.output.parts)) {
        eventPayload.output.parts = []
      }
      const parts = eventPayload.output?.parts
      if (!Array.isArray(parts)) {
        return
      }
      if (hasCompactionMarker(parts)) {
        writeGatewayEventAudit(directory, {
          hook: "compaction-context-injector",
          stage: "inject",
          reason_code: REASON_CODES.COMPACTION_CONTEXT_ALREADY_PRESENT,
          session_id: typeof eventPayload.input?.sessionID === "string" ? eventPayload.input.sessionID : "",
          command: command.trim(),
        })
        return
      }
      parts.unshift({ type: "text", text: COMPACTION_CONTEXT_TEXT })
      writeGatewayEventAudit(directory, {
        hook: "compaction-context-injector",
        stage: "inject",
        reason_code: REASON_CODES.COMPACTION_CONTEXT_INJECTED,
        session_id: typeof eventPayload.input?.sessionID === "string" ? eventPayload.input.sessionID : "",
        command: command.trim(),
      })
    },
  }
}
