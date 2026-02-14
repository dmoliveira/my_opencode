import type { AutopilotLoopState, SessionMessage } from "./types.js"

// Escapes a string for safe regular-expression embedding.
export function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

// Detects completion token in assistant text.
export function detectPromiseCompletion(text: string, promise: string): boolean {
  if (!text.trim()) {
    return false
  }
  const safePromise = escapeRegExp(promise)
  const pattern = new RegExp(`<promise>\\s*${safePromise}\\s*</promise>`, "i")
  return pattern.test(text)
}

// Extracts last assistant textual response from session messages.
export function extractLastAssistantText(messages: SessionMessage[]): string {
  const assistants = messages.filter((message) => message.info?.role === "assistant")
  const last = assistants[assistants.length - 1]
  if (!last?.parts) {
    return ""
  }
  return last.parts
    .filter((part) => part.type === "text")
    .map((part) => part.text ?? "")
    .join("\n")
}

// Detects objective-mode completion marker in assistant response.
export function detectObjectiveCompletionSignal(text: string): boolean {
  return /<objective-complete>\s*true\s*<\/objective-complete>/i.test(text)
}

// Evaluates completion based on configured completion mode.
export function detectCompletion(state: AutopilotLoopState, assistantText: string): boolean {
  if (state.completionMode === "objective") {
    return detectObjectiveCompletionSignal(assistantText)
  }
  return detectPromiseCompletion(assistantText, state.completionPromise)
}
