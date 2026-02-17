import type { GatewayHook } from "../registry.js"

interface ToolAfterPayload {
  input?: { sessionID?: string; sessionId?: string }
  output?: { output?: unknown }
  properties?: { sessionID?: string; sessionId?: string; info?: { id?: string } }
}

interface SessionDeletedPayload {
  properties?: { sessionID?: string; sessionId?: string; info?: { id?: string } }
}

type HandoffMode = "plan_enter" | "plan_exit"

const MARKER = "[plan HANDOFF REMINDER]"

const PLAN_ENTER_PATTERNS = [/switch(?:ing)?\s+to\s+plan agent/i, /benefit from planning first/i]
const PLAN_EXIT_PATTERNS = [/completed the planning phase/i, /switch to build agent/i]

const PLAN_ENTER_HINT = [
  MARKER,
  "Plan-enter handoff reminder detected.",
  "- Draft the plan before implementation changes",
  "- Keep execution actions paused until plan is finalized",
].join("\n")

const PLAN_EXIT_HINT = [
  MARKER,
  "Plan-exit handoff reminder detected.",
  "- Move from planning to implementation now",
  "- Execute checks before declaring completion",
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

function detectMode(output: string): HandoffMode | null {
  if (PLAN_ENTER_PATTERNS.every((pattern) => pattern.test(output))) {
    return "plan_enter"
  }
  if (PLAN_EXIT_PATTERNS.every((pattern) => pattern.test(output))) {
    return "plan_exit"
  }
  return null
}

export function createPlanHandoffReminderHook(options: { enabled: boolean }): GatewayHook {
  const lastModeBySession = new Map<string, HandoffMode>()
  return {
    id: "plan-handoff-reminder",
    priority: 357,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }
      if (type === "session.deleted") {
        const sessionId = resolveSessionId((payload ?? {}) as SessionDeletedPayload)
        if (sessionId) {
          lastModeBySession.delete(sessionId)
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
      if (output.includes(MARKER)) {
        return
      }
      const mode = detectMode(output)
      if (!mode) {
        return
      }
      const sessionId = resolveSessionId(eventPayload)
      if (sessionId && lastModeBySession.get(sessionId) === mode) {
        return
      }
      eventPayload.output.output = `${output}\n\n${mode === "plan_enter" ? PLAN_ENTER_HINT : PLAN_EXIT_HINT}`
      if (sessionId) {
        lastModeBySession.set(sessionId, mode)
      }
    },
  }
}
