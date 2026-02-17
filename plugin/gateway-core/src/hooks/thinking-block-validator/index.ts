import type { GatewayHook } from "../registry.js"

interface ChatPayload {
  output?: {
    parts?: Array<{ type: string; text?: string }>
  }
}

const THINKING_WARNING =
  "[thinking validator] Detected malformed thinking block. Ensure every <thinking> has a matching </thinking>."

// Returns true when text has malformed <thinking> tag ordering.
function hasMalformedThinkingBlocks(text: string): boolean {
  const tokens = text.match(/<thinking>|<\/thinking>/g) ?? []
  let depth = 0
  for (const token of tokens) {
    if (token === "<thinking>") {
      depth += 1
      continue
    }
    depth -= 1
    if (depth < 0) {
      return true
    }
  }
  return depth !== 0
}

// Creates validator hook for malformed thinking block output.
export function createThinkingBlockValidatorHook(options: { enabled: boolean }): GatewayHook {
  return {
    id: "thinking-block-validator",
    priority: 368,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "chat.message") {
        return
      }
      const eventPayload = (payload ?? {}) as ChatPayload
      const parts = eventPayload.output?.parts
      if (!Array.isArray(parts) || parts.length === 0) {
        return
      }
      const textParts = parts.filter((part) => part.type === "text" && typeof part.text === "string")
      if (textParts.length === 0) {
        return
      }
      const hasMalformed = textParts.some((part) => hasMalformedThinkingBlocks(String(part.text)))
      if (!hasMalformed) {
        return
      }
      const firstText = textParts[0]
      if (typeof firstText.text !== "string" || firstText.text.includes(THINKING_WARNING)) {
        return
      }
      firstText.text = `${firstText.text}\n\n${THINKING_WARNING}`
    },
  }
}
