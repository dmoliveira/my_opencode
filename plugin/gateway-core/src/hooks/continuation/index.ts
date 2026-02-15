import { REASON_CODES } from "../../bridge/reason-codes.js"
import { loadGatewayState, nowIso, saveGatewayState } from "../../state/storage.js"
import type { GatewayState } from "../../state/types.js"
import type { GatewayHook } from "../registry.js"

// Declares minimal session message API used by continuation hook.
interface GatewayClient {
  session?: {
    messages(args: {
      path: { id: string }
      query?: { directory?: string }
    }): Promise<{ data?: Array<{ info?: { role?: string }; parts?: Array<{ type: string; text?: string }> }> }>
    promptAsync(args: {
      path: { id: string }
      body: { parts: Array<{ type: string; text: string }> }
      query?: { directory?: string }
    }): Promise<void>
  }
}

// Declares session idle payload shape.
interface SessionIdlePayload {
  directory?: string
  properties?: {
    sessionID?: string
    info?: { id?: string }
  }
}

// Resolves active session id from event payload.
function resolveSessionId(payload: SessionIdlePayload): string {
  const direct = payload.properties?.sessionID
  if (typeof direct === "string" && direct.trim()) {
    return direct.trim()
  }
  const fallback = payload.properties?.info?.id
  if (typeof fallback === "string" && fallback.trim()) {
    return fallback.trim()
  }
  return ""
}

// Extracts last assistant text from session messages.
function lastAssistantText(
  messages: Array<{ info?: { role?: string }; parts?: Array<{ type: string; text?: string }> }>,
): string {
  const assistantMessages = messages.filter((item) => item.info?.role === "assistant")
  const last = assistantMessages[assistantMessages.length - 1]
  if (!last?.parts) {
    return ""
  }
  return last.parts
    .filter((part) => part.type === "text")
    .map((part) => part.text ?? "")
    .join("\n")
}

// Returns true when assistant text satisfies loop completion criteria.
function isLoopComplete(state: GatewayState, text: string): boolean {
  const active = state.activeLoop
  if (!active || !text.trim()) {
    return false
  }
  if (active.completionMode === "objective") {
    return /<objective-complete>\s*true\s*<\/objective-complete>/i.test(text)
  }
  const token = active.completionPromise.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  return new RegExp(`<promise>\\s*${token}\\s*<\\/promise>`, "i").test(text)
}

// Builds continuation prompt for active gateway loop iteration.
function continuationPrompt(state: GatewayState): string {
  const active = state.activeLoop
  if (!active) {
    return "Continue the current objective."
  }
  const completionGuidance =
    active.completionMode === "objective"
      ? "When fully complete, emit <objective-complete>true</objective-complete>."
      : `When fully complete, emit <promise>${active.completionPromise}</promise>.`
  return [
    `[GATEWAY LOOP ${active.iteration}/${active.maxIterations}]`,
    "Continue execution from the current state and apply concrete validated changes.",
    completionGuidance,
    "Objective:",
    active.objective,
  ].join("\n\n")
}

// Creates continuation helper hook placeholder for gateway composition.
export function createContinuationHook(options: { directory: string; client?: GatewayClient }): GatewayHook {
  return {
    id: "continuation",
    priority: 200,
    async event(type: string, payload: unknown): Promise<void> {
      if (type !== "session.idle") {
        return
      }
      const eventPayload = (payload ?? {}) as SessionIdlePayload
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const state = loadGatewayState(directory)
      const active = state?.activeLoop
      if (!state || !active || active.active !== true) {
        return
      }
      const sessionId = resolveSessionId(eventPayload)
      if (!sessionId || sessionId !== active.sessionId) {
        return
      }

      const client = options.client?.session
      if (client) {
        const response = await client.messages({
          path: { id: sessionId },
          query: { directory },
        })
        const text = lastAssistantText(Array.isArray(response.data) ? response.data : [])
        if (isLoopComplete(state, text)) {
          active.active = false
          state.lastUpdatedAt = nowIso()
          state.source =
            active.completionMode === "objective"
              ? REASON_CODES.LOOP_COMPLETED_OBJECTIVE
              : REASON_CODES.LOOP_COMPLETED_PROMISE
          saveGatewayState(directory, state)
          return
        }
      }

      if (active.iteration >= active.maxIterations) {
        active.active = false
        state.lastUpdatedAt = nowIso()
        state.source = REASON_CODES.LOOP_MAX_ITERATIONS
        saveGatewayState(directory, state)
        return
      }

      active.iteration += 1
      state.lastUpdatedAt = nowIso()
      state.source = REASON_CODES.LOOP_IDLE_CONTINUED
      saveGatewayState(directory, state)

      if (client) {
        await client.promptAsync({
          path: { id: sessionId },
          body: { parts: [{ type: "text", text: continuationPrompt(state) }] },
          query: { directory },
        })
      }
      return
    },
  }
}
