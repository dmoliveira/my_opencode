import {
  parseAutopilotTemplateCommand,
  parseSlashCommand,
  resolveAutopilotAction,
} from "../../bridge/commands.js"
import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"

// Declares guard interface exposed to continuation hook.
export interface StopContinuationGuard {
  isStopped(sessionId: string): boolean
  forceStop(sessionId: string, reasonCode?: string): void
}

interface ToolBeforePayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
    args?: { command?: string }
    command?: string
    arguments?: string
  }
  output?: {
    args?: { command?: string }
  }
  properties?: {
    command?: string
    sessionID?: string
    sessionId?: string
  }
  directory?: string
}

interface ChatPayload {
  properties?: {
    sessionID?: string
  }
}

interface EventPayload {
  properties?: {
    info?: { id?: string }
  }
}

// Resolves session id across payload variants.
function resolveSessionId(payload: ToolBeforePayload): string {
  const candidates = [
    payload.input?.sessionID,
    payload.input?.sessionId,
    payload.properties?.sessionID,
    payload.properties?.sessionId,
  ]
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) {
      return value.trim()
    }
  }
  return ""
}

// Resolves command text across payload variants.
function resolveCommand(payload: ToolBeforePayload): string {
  const commandName =
    typeof payload.input?.command === "string" && payload.input.command.trim()
      ? payload.input.command.trim().replace(/^\//, "")
      : ""
  const commandArgs =
    typeof payload.input?.arguments === "string" && payload.input.arguments.trim()
      ? payload.input.arguments.trim()
      : ""
  const commandExecuteBefore = commandName
    ? `/${commandName}${commandArgs ? ` ${commandArgs}` : ""}`
    : ""
  const candidates = [
    payload.output?.args?.command,
    payload.input?.args?.command,
    payload.properties?.command,
    commandExecuteBefore,
  ]
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) {
      return value.trim()
    }
  }
  return ""
}

// Creates continuation stop guard hook and shared state query API.
export function createStopContinuationGuardHook(options: {
  directory: string
  enabled: boolean
}): GatewayHook & StopContinuationGuard {
  const stoppedSessions = new Set<string>()
  return {
    id: "stop-continuation-guard",
    priority: 295,
    isStopped(sessionId: string): boolean {
      return stoppedSessions.has(sessionId)
    },
    forceStop(sessionId: string, reasonCode = "continuation_stopped_forced"): void {
      if (!sessionId.trim()) {
        return
      }
      const resolvedSessionId = sessionId.trim()
      stoppedSessions.add(resolvedSessionId)
      writeGatewayEventAudit(options.directory, {
        hook: "stop-continuation-guard",
        stage: "state",
        reason_code: reasonCode,
        session_id: resolvedSessionId,
      })
    },
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }
      if (type === "chat.message") {
        const chatPayload = (payload ?? {}) as ChatPayload
        const sessionId = chatPayload.properties?.sessionID
        if (typeof sessionId === "string" && sessionId.trim()) {
          stoppedSessions.delete(sessionId.trim())
        }
        return
      }
      if (type === "session.deleted") {
        const eventPayload = (payload ?? {}) as EventPayload
        const sessionId = eventPayload.properties?.info?.id
        if (typeof sessionId === "string" && sessionId.trim()) {
          stoppedSessions.delete(sessionId.trim())
        }
        return
      }
      if (type !== "tool.execute.before" && type !== "command.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolBeforePayload
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = resolveSessionId(eventPayload)
      const command = resolveCommand(eventPayload)
      if (!sessionId || !command) {
        return
      }
      const toolName = String(eventPayload.input?.tool || "")
      let parsed = parseSlashCommand(command)
      if (!command.trim().startsWith("/") && toolName !== "slashcommand") {
        const templateParsed = parseAutopilotTemplateCommand(command)
        if (templateParsed) {
          parsed = templateParsed
        } else {
          return
        }
      }
      const action = resolveAutopilotAction(parsed.name, parsed.args)
      if (action !== "stop") {
        return
      }
      stoppedSessions.add(sessionId)
      writeGatewayEventAudit(directory, {
        hook: "stop-continuation-guard",
        stage: "state",
        reason_code: "continuation_stopped",
        session_id: sessionId,
      })
    },
  }
}
