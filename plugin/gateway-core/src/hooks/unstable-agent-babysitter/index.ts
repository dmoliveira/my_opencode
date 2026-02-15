import type { GatewayHook } from "../registry.js"

interface ChatPayload {
  properties?: {
    model?: unknown
    prompt?: unknown
  }
  output?: {
    parts?: Array<{ type: string; text?: string }>
  }
}

// Creates babysitter hook that warns when risky model patterns are detected.
export function createUnstableAgentBabysitterHook(options: {
  enabled: boolean
  riskyPatterns: string[]
}): GatewayHook {
  const patterns = options.riskyPatterns.map((item) => item.toLowerCase()).filter(Boolean)
  return {
    id: "unstable-agent-babysitter",
    priority: 370,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "chat.message") {
        return
      }
      const eventPayload = (payload ?? {}) as ChatPayload
      const modelText = String(eventPayload.properties?.model ?? "").toLowerCase()
      if (!modelText) {
        return
      }
      if (!patterns.some((pattern) => modelText.includes(pattern))) {
        return
      }
      const parts = eventPayload.output?.parts
      if (!Array.isArray(parts) || parts.length === 0) {
        return
      }
      const textPart = parts.find((part) => part.type === "text")
      if (!textPart || typeof textPart.text !== "string") {
        return
      }
      textPart.text +=
        "\n\n[unstable-agent-babysitter] Risky model profile detected. Prefer shorter steps, explicit validation, and conservative edits."
    },
  }
}
