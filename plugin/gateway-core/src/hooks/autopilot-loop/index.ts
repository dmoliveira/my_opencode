import {
  canonicalAutopilotCommandName,
  parseAutopilotTemplateCommand,
  parseCompletionMode,
  parseCompletionPromise,
  parseDoneCriteria,
  parseGoal,
  parseMaxIterations,
  parseSlashCommand,
  resolveAutopilotAction,
} from "../../bridge/commands.js"
import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import { REASON_CODES } from "../../bridge/reason-codes.js"
import { loadGatewayState, nowIso, saveGatewayState } from "../../state/storage.js"
import type { GatewayState } from "../../state/types.js"
import type { GatewayHook } from "../registry.js"
import type { ContextCollector } from "../context-injector/collector.js"

// Declares gateway loop defaults used when command flags are omitted.
interface AutopilotLoopDefaults {
  enabled: boolean
  maxIterations: number
  completionMode: "promise" | "objective"
  completionPromise: string
}

// Declares slash command hook payload shape used by plugin host.
interface ToolBeforePayload {
  type?: string
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

// Resolves session id across plugin host payload variants.
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

// Resolves slash command text across plugin host payload variants.
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

// Returns true when parsed command corresponds to pause action.
function isPauseCommand(name: string, args: string): boolean {
  const command = canonicalAutopilotCommandName(name)
  if (command === "autopilot-pause") {
    return true
  }
  if (command === "autopilot") {
    const head = args.trim().split(/\s+/)[0]?.toLowerCase() ?? ""
    return head === "pause"
  }
  return false
}

// Returns true when parsed command corresponds to resume action.
function isResumeCommand(name: string, args: string): boolean {
  const command = canonicalAutopilotCommandName(name)
  if (command === "autopilot-resume") {
    return true
  }
  if (command === "autopilot") {
    const head = args.trim().split(/\s+/)[0]?.toLowerCase() ?? ""
    return head === "resume"
  }
  return false
}

// Returns true when command includes explicit goal override.
function hasExplicitGoalArg(args: string): boolean {
  return /--goal(?:\s+|=)/i.test(args)
}

// Resolves effective working directory from event payload.
function payloadDirectory(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") {
    return fallback
  }
  const record = payload as Record<string, unknown>
  return typeof record.directory === "string" && record.directory.trim()
    ? record.directory
    : fallback
}

// Creates autopilot loop hook placeholder for gateway composition.
export function createAutopilotLoopHook(options: {
  directory: string
  defaults: AutopilotLoopDefaults
  collector?: ContextCollector
}): GatewayHook {
  return {
    id: "autopilot-loop",
    priority: 100,
    async event(type: string, payload: unknown): Promise<void> {
      if (type !== "tool.execute.before" && type !== "command.execute.before") {
        return
      }
      const scopedDir = payloadDirectory(payload, options.directory)
      const eventPayload = (payload ?? {}) as ToolBeforePayload
      const input = eventPayload.input
      const sessionId = resolveSessionId(eventPayload)
      const commandRaw = resolveCommand(eventPayload)
      if (!sessionId || !commandRaw) {
        writeGatewayEventAudit(scopedDir, {
          hook: "autopilot-loop",
          stage: "skip",
          reason_code: "missing_session_or_command",
          has_session_id: sessionId.length > 0,
          has_command: commandRaw.length > 0,
        })
        return
      }

      let parsed = parseSlashCommand(commandRaw)
      const toolName = String(input?.tool || "")
      if (!commandRaw.trim().startsWith("/") && toolName !== "slashcommand") {
        const templateParsed = parseAutopilotTemplateCommand(commandRaw)
        if (templateParsed) {
          parsed = templateParsed
        } else {
          writeGatewayEventAudit(scopedDir, {
            hook: "autopilot-loop",
            stage: "skip",
            reason_code: "non_slash_tool",
            tool: toolName,
          })
          return
        }
      }
      const action = resolveAutopilotAction(parsed.name, parsed.args)
      if (action === "none") {
        writeGatewayEventAudit(scopedDir, {
          hook: "autopilot-loop",
          stage: "skip",
          reason_code: "non_autopilot_command",
          command: parsed.name,
        })
        return
      }

      if (action === "stop") {
        const previousState = loadGatewayState(scopedDir)
        const previousLoop = previousState?.activeLoop
        const pauseMode = isPauseCommand(parsed.name, parsed.args)
        const nextLoop =
          previousLoop && previousLoop.sessionId === sessionId
            ? {
                ...previousLoop,
                active: false,
              }
            : {
                active: false,
                sessionId,
                objective: "stop requested",
                completionMode: options.defaults.completionMode,
                completionPromise: options.defaults.completionPromise,
                iteration: 1,
                maxIterations: options.defaults.maxIterations,
                startedAt: nowIso(),
              }
        const state: GatewayState = {
          activeLoop: nextLoop,
          lastUpdatedAt: nowIso(),
          source: REASON_CODES.LOOP_STOPPED,
        }
        saveGatewayState(scopedDir, state)
        writeGatewayEventAudit(scopedDir, {
          hook: "autopilot-loop",
          stage: "state",
          reason_code: REASON_CODES.LOOP_STOPPED,
          session_id: sessionId,
          command: parsed.name,
          pause_mode: pauseMode,
        })
        return
      }

      if (!options.defaults.enabled) {
        writeGatewayEventAudit(scopedDir, {
          hook: "autopilot-loop",
          stage: "skip",
          reason_code: "autopilot_loop_disabled",
          command: parsed.name,
        })
        return
      }

      const resumeMode = isResumeCommand(parsed.name, parsed.args)
      if (resumeMode && !hasExplicitGoalArg(parsed.args)) {
        const previousState = loadGatewayState(scopedDir)
        const previousLoop = previousState?.activeLoop
        if (previousLoop && previousLoop.sessionId === sessionId && previousLoop.active !== true) {
          const resumedState: GatewayState = {
            activeLoop: {
              ...previousLoop,
              active: true,
            },
            lastUpdatedAt: nowIso(),
            source: REASON_CODES.LOOP_STARTED,
          }
          saveGatewayState(scopedDir, resumedState)
          writeGatewayEventAudit(scopedDir, {
            hook: "autopilot-loop",
            stage: "state",
            reason_code: REASON_CODES.LOOP_STARTED,
            session_id: sessionId,
            command: parsed.name,
            resumed_from_paused: true,
          })
          return
        }
      }

      const completionMode =
        parsed.name === "autopilot-objective"
          ? "objective"
          : parseCompletionMode(parsed.args)
      const state: GatewayState = {
        activeLoop: {
          active: true,
          sessionId,
          objective: parseGoal(parsed.args),
          doneCriteria: parseDoneCriteria(parsed.args),
          completionMode,
          completionPromise: parseCompletionPromise(
            parsed.args,
            options.defaults.completionPromise,
          ),
          iteration: 1,
          maxIterations: parseMaxIterations(parsed.args, options.defaults.maxIterations),
          startedAt: nowIso(),
        },
        lastUpdatedAt: nowIso(),
        source: REASON_CODES.LOOP_STARTED,
      }
      saveGatewayState(scopedDir, state)
      const criteria = parseDoneCriteria(parsed.args)
      const objectiveSummary = [
        "Autopilot objective activated.",
        `Goal: ${parseGoal(parsed.args)}`,
        criteria.length > 0
          ? `Done criteria: ${criteria.join("; ")}`
          : "Done criteria: follow objective context and complete all remaining actionable items.",
        completionMode === "objective"
          ? "Completion mode: objective (<objective-complete>true</objective-complete>)."
          : `Completion mode: promise (<promise>${parseCompletionPromise(parsed.args, options.defaults.completionPromise)}</promise>).`,
      ].join("\n")
      options.collector?.register(sessionId, {
        source: "autopilot-loop",
        content: objectiveSummary,
        priority: "high",
      })
      writeGatewayEventAudit(scopedDir, {
        hook: "autopilot-loop",
        stage: "state",
        reason_code: REASON_CODES.LOOP_STARTED,
        session_id: sessionId,
        command: parsed.name,
        completion_mode: completionMode,
      })
      return
    },
  }
}
