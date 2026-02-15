import type { GatewayHook } from "../registry.js"

interface ToolAfterPayload {
  input?: { tool?: string; sessionID?: string; sessionId?: string }
  output?: { output?: unknown }
}

// Creates retry budget guard for repeated failing task output loops.
export function createRetryBudgetGuardHook(options: { enabled: boolean; maxRetries: number }): GatewayHook {
  const failuresBySession = new Map<string, number>()
  const maxRetries = options.maxRetries > 0 ? options.maxRetries : 3
  return {
    id: "retry-budget-guard",
    priority: 420,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.after") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolAfterPayload
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase()
      if (tool !== "task") {
        return
      }
      if (typeof eventPayload.output?.output !== "string") {
        return
      }
      const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "")
      if (!sessionId) {
        return
      }
      const failed = /\[error\]|failed|invalid arguments/i.test(eventPayload.output.output)
      if (!failed) {
        failuresBySession.delete(sessionId)
        return
      }
      const nextCount = (failuresBySession.get(sessionId) ?? 0) + 1
      failuresBySession.set(sessionId, nextCount)
      if (nextCount <= maxRetries) {
        return
      }
      eventPayload.output.output +=
        "\n\n[retry-budget-guard] Retry budget exceeded for this session. Escalate strategy or ask for narrowed scope before retrying again."
    },
  }
}
