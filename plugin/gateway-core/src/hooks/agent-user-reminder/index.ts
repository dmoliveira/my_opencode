import type { GatewayHook } from "../registry.js"

interface ChatPayload {
  properties?: {
    prompt?: unknown
    message?: unknown
    text?: unknown
  }
  output?: {
    parts?: Array<{ type: string; text?: string }>
  }
}

// Extracts prompt text from chat payload properties.
function promptText(payload: ChatPayload): string {
  const props = payload.properties ?? {}
  const candidates = [props.prompt, props.message, props.text]
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) {
      return value.trim()
    }
  }
  return ""
}

// Creates reminder hook recommending specialist agents for complex tasks.
export function createAgentUserReminderHook(options: { enabled: boolean }): GatewayHook {
  return {
    id: "agent-user-reminder",
    priority: 365,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "chat.message") {
        return
      }
      const eventPayload = (payload ?? {}) as ChatPayload
      const prompt = promptText(eventPayload).toLowerCase()
      if (!prompt) {
        return
      }
      if (!/(debug|architecture|refactor|research|investigate)/.test(prompt)) {
        return
      }
      const parts = eventPayload.output?.parts
      if (!Array.isArray(parts) || parts.length === 0) {
        return
      }
      const firstText = parts.find((part) => part.type === "text")
      if (!firstText || typeof firstText.text !== "string") {
        return
      }
      firstText.text =
        `${firstText.text}\n\n[agent reminder] Consider specialist subagents (explore/reviewer/oracle) for faster high-confidence progress.`
    },
  }
}
