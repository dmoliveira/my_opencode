import type { GatewayHook } from "../registry.js"

interface ToolAfterPayload {
  input?: { sessionID?: string; sessionId?: string }
  output?: { output?: unknown }
}

interface SessionDeletedPayload {
  properties?: { sessionID?: string; sessionId?: string; info?: { id?: string } }
}

const MODE_REMINDER_MARKER = "[mode-transition REMINDER]"
const PLAN_MODE = "plan"
const BUILD_MODE = "build"

const PLAN_MODE_PATTERNS = [/plan mode is active/i]
const BUILD_MODE_PATTERNS = [
  /operational mode has changed from plan to build/i,
  /you are no longer in read-only mode/i,
]

const PLAN_MODE_HINT = [
  MODE_REMINDER_MARKER,
  "Plan mode reminder detected.",
  "- Stay read-only for investigation and planning steps",
  "- Write/update only the designated plan artifact",
  "- Exit plan mode before mutating commands or file edits",
].join("\n")

const BUILD_MODE_HINT = [
  MODE_REMINDER_MARKER,
  "Plan-to-build transition detected.",
  "- Resume implementation and command execution now",
  "- Run required validation checks before completion claims",
  "- Continue the active worktree flow until completion or blocker",
].join("\n")

function resolveSessionId(payload: {
  input?: { sessionID?: string; sessionId?: string }
  properties?: { sessionID?: string; sessionId?: string; info?: { id?: string } }
}): string {
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

function detectMode(output: string): typeof PLAN_MODE | typeof BUILD_MODE | null {
  if (BUILD_MODE_PATTERNS.every((pattern) => pattern.test(output))) {
    return BUILD_MODE
  }
  if (PLAN_MODE_PATTERNS.some((pattern) => pattern.test(output))) {
    return PLAN_MODE
  }
  return null
}

export function createModeTransitionReminderHook(options: { enabled: boolean }): GatewayHook {
  const sessionModeState = new Map<string, string>()
  return {
    id: "mode-transition-reminder",
    priority: 358,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }
      if (type === "session.deleted") {
        const sessionId = resolveSessionId((payload ?? {}) as SessionDeletedPayload)
        if (sessionId) {
          sessionModeState.delete(sessionId)
        }
        return
      }
      if (type !== "tool.execute.after") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolAfterPayload
      if (typeof eventPayload.output?.output !== "string") {
        return
      }
      const output = eventPayload.output.output
      if (output.includes(MODE_REMINDER_MARKER)) {
        return
      }
      const mode = detectMode(output)
      if (!mode) {
        return
      }
      const sessionId = resolveSessionId(eventPayload)
      if (sessionId && sessionModeState.get(sessionId) === mode) {
        return
      }
      eventPayload.output.output = `${output}\n\n${mode === BUILD_MODE ? BUILD_MODE_HINT : PLAN_MODE_HINT}`
      if (sessionId) {
        sessionModeState.set(sessionId, mode)
      }
    },
  }
}
