import {
  parseCompletionMode,
  parseCompletionPromise,
  parseGoal,
  parseMaxIterations,
  parseSlashCommand,
  resolveAutopilotAction,
} from "../../bridge/commands.js"
import { REASON_CODES } from "../../bridge/reason-codes.js"
import { nowIso, saveGatewayState } from "../../state/storage.js"
import type { GatewayState } from "../../state/types.js"
import type { GatewayHook } from "../registry.js"

// Declares gateway loop defaults used when command flags are omitted.
interface AutopilotLoopDefaults {
  enabled: boolean
  maxIterations: number
  completionMode: "promise" | "objective"
  completionPromise: string
}

// Declares slash command hook payload shape used by plugin host.
interface ToolBeforePayload {
  input?: {
    tool?: string
    sessionID?: string
  }
  output?: {
    args?: { command?: string }
  }
  directory?: string
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
}): GatewayHook {
  return {
    id: "autopilot-loop",
    priority: 100,
    async event(type: string, payload: unknown): Promise<void> {
      if (type !== "tool.execute.before") {
        return
      }
      const scopedDir = payloadDirectory(payload, options.directory)
      const eventPayload = (payload ?? {}) as ToolBeforePayload
      const input = eventPayload.input
      const output = eventPayload.output
      if (input?.tool !== "slashcommand") {
        return
      }
      const sessionId = typeof input.sessionID === "string" ? input.sessionID.trim() : ""
      const commandRaw = output?.args?.command
      if (!sessionId || !commandRaw) {
        return
      }

      const parsed = parseSlashCommand(commandRaw)
      const action = resolveAutopilotAction(parsed.name, parsed.args)
      if (action === "none") {
        return
      }

      if (action === "stop") {
        const state: GatewayState = {
          activeLoop: {
            active: false,
            sessionId,
            objective: "stop requested",
            completionMode: options.defaults.completionMode,
            completionPromise: options.defaults.completionPromise,
            iteration: 1,
            maxIterations: options.defaults.maxIterations,
            startedAt: nowIso(),
          },
          lastUpdatedAt: nowIso(),
          source: REASON_CODES.LOOP_STOPPED,
        }
        saveGatewayState(scopedDir, state)
        return
      }

      if (!options.defaults.enabled) {
        return
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
      return
    },
  }
}
