import {
  DEFAULT_COMPLETION_PROMISE,
  DEFAULT_MAX_ITERATIONS,
  HOOK_NAME,
} from "./constants.js"
import { buildContinuationPrompt } from "./injector.js"
import { detectCompletion, extractLastAssistantText } from "./detector.js"
import { clearState, incrementIteration, loadState, saveState } from "./storage.js"
import type { AutopilotLoopOptions, AutopilotLoopState, HookContext, HookEventPayload } from "./types.js"

// Declares runtime control API for autopilot-loop hook users.
export interface AutopilotLoopHook {
  event(input: HookEventPayload): Promise<void>
  startLoop(args: {
    sessionId: string
    prompt: string
    completionMode?: "promise" | "objective"
    completionPromise?: string
    maxIterations?: number
  }): void
  cancelLoop(sessionId: string): void
  getState(): AutopilotLoopState | null
}

// Resolves session id from event properties.
function eventSessionId(input: HookEventPayload): string | null {
  const props = input.event.properties
  if (!props) {
    return null
  }
  const direct = props.sessionID
  if (typeof direct === "string" && direct.trim()) {
    return direct
  }
  const info = props.info
  if (typeof info === "object" && info) {
    const record = info as Record<string, unknown>
    const id = record.id
    if (typeof id === "string" && id.trim()) {
      return id
    }
  }
  return null
}

// Creates hook implementation for event-driven autopilot continuation.
export function createAutopilotLoopHook(
  ctx: HookContext,
  options?: AutopilotLoopOptions,
): AutopilotLoopHook {
  const stateFile = options?.stateFile

  // Starts loop state for the provided session and prompt.
  function startLoop(args: {
    sessionId: string
    prompt: string
    completionMode?: "promise" | "objective"
    completionPromise?: string
    maxIterations?: number
  }): void {
    const state: AutopilotLoopState = {
      active: true,
      sessionId: args.sessionId,
      prompt: args.prompt,
      iteration: 1,
      maxIterations: args.maxIterations ?? DEFAULT_MAX_ITERATIONS,
      completionMode: args.completionMode ?? "promise",
      completionPromise: args.completionPromise ?? DEFAULT_COMPLETION_PROMISE,
      startedAt: new Date().toISOString(),
    }
    saveState(ctx.directory, state, stateFile)
  }

  // Cancels loop state when requested for matching session.
  function cancelLoop(sessionId: string): void {
    const state = loadState(ctx.directory, stateFile)
    if (state && state.sessionId === sessionId) {
      clearState(ctx.directory, stateFile)
    }
  }

  // Returns current persisted loop state.
  function getState(): AutopilotLoopState | null {
    return loadState(ctx.directory, stateFile)
  }

  // Emits user-facing toast when hook completes or stops.
  async function toast(title: string, message: string, variant: "success" | "warning" | "info"): Promise<void> {
    try {
      await ctx.client.tui?.showToast({
        body: { title, message, variant, duration: 4000 },
      })
    } catch {
      // no-op
    }
  }

  // Handles lifecycle events and injects continuation prompts on idle.
  async function event(input: HookEventPayload): Promise<void> {
    const eventType = input.event.type
    const sessionId = eventSessionId(input)

    if (eventType === "session.deleted" && sessionId) {
      cancelLoop(sessionId)
      return
    }

    if (eventType !== "session.idle" || !sessionId) {
      return
    }

    const state = loadState(ctx.directory, stateFile)
    if (!state || !state.active || state.sessionId !== sessionId) {
      return
    }

    const response = await ctx.client.session.messages({
      path: { id: sessionId },
      query: { directory: ctx.directory },
    })
    const messages = Array.isArray(response.data) ? response.data : []
    const assistantText = extractLastAssistantText(messages)

    if (detectCompletion(state, assistantText)) {
      clearState(ctx.directory, stateFile)
      await toast("Autopilot Loop Complete ✅", `Completed after ${state.iteration} iteration(s).`, "success")
      return
    }

    if (state.iteration >= state.maxIterations) {
      clearState(ctx.directory, stateFile)
      await toast("Autopilot Loop Stopped ⚠️", `Max iterations (${state.maxIterations}) reached.`, "warning")
      return
    }

    const next = incrementIteration(ctx.directory, state, stateFile)
    const prompt = buildContinuationPrompt(next)
    await ctx.client.session.promptAsync({
      path: { id: sessionId },
      body: { parts: [{ type: "text", text: prompt }] },
      query: { directory: ctx.directory },
    })
    await toast(HOOK_NAME, `Injected continuation ${next.iteration}/${next.maxIterations}.`, "info")
  }

  return { event, startLoop, cancelLoop, getState }
}
