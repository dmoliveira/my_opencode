import { createHash } from "node:crypto"

import type { GatewayHook } from "../registry.js"

interface ToolAfterPayload {
  input?: { tool?: string }
  output?: { output?: unknown }
}

function hashLine(line: string): string {
  return createHash("sha1").update(line).digest("hex").slice(0, 8)
}

function enhanceReadOutput(text: string): string {
  const lines = text.split(/\r?\n/)
  let touched = false
  const enhanced = lines.map((line) => {
    if (!/^\d+:\s/.test(line)) {
      return line
    }
    if (/\s\[h:[0-9a-f]{8}\]$/.test(line)) {
      return line
    }
    touched = true
    return `${line} [h:${hashLine(line)}]`
  })
  return touched ? enhanced.join("\n") : text
}

export function createHashlineReadEnhancerHook(options: { enabled: boolean }): GatewayHook {
  return {
    id: "hashline-read-enhancer",
    priority: 365,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.after") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolAfterPayload
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase()
      if (tool !== "read") {
        return
      }
      if (typeof eventPayload.output?.output !== "string") {
        return
      }
      eventPayload.output.output = enhanceReadOutput(eventPayload.output.output)
    },
  }
}
