import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"

// Declares post-tool payload shape for truncation hook.
interface ToolAfterPayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
  }
  output?: {
    output?: unknown
  }
  properties?: {
    tool?: string
  }
  directory?: string
}

// Truncates text by max lines and max chars.
function truncateText(text: string, maxChars: number, maxLines: number): {
  text: string
  lineTruncated: boolean
  charTruncated: boolean
} {
  const lines = text.split(/\r?\n/)
  const truncatedLines = lines.slice(0, maxLines)
  let byLines = truncatedLines.join("\n")
  const lineTruncated = lines.length > maxLines
  const charTruncated = byLines.length > maxChars
  if (charTruncated) {
    byLines = byLines.slice(0, maxChars)
  }
  return {
    text: byLines,
    lineTruncated,
    charTruncated,
  }
}

// Resolves tool label from post-tool payload variants.
function resolveTool(payload: ToolAfterPayload): string {
  const candidates = [payload.input?.tool, payload.properties?.tool]
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) {
      return value.trim()
    }
  }
  return ""
}

// Creates tool output truncation hook for context-pressure safety.
export function createToolOutputTruncatorHook(options: {
  directory: string
  enabled: boolean
  maxChars: number
  maxLines: number
  tools: string[]
}): GatewayHook {
  const configuredTools = new Set(options.tools)
  const maxChars = options.maxChars >= 200 ? options.maxChars : 12000
  const maxLines = options.maxLines >= 20 ? options.maxLines : 220
  return {
    id: "tool-output-truncator",
    priority: 250,
    async event(type: string, payload: unknown): Promise<void> {
      if (type !== "tool.execute.after") {
        return
      }
      if (!options.enabled) {
        return
      }
      const eventPayload = (payload ?? {}) as ToolAfterPayload
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const tool = resolveTool(eventPayload)
      if (!tool || !configuredTools.has(tool)) {
        writeGatewayEventAudit(directory, {
          hook: "tool-output-truncator",
          stage: "skip",
          reason_code: "tool_not_supported",
          tool,
        })
        return
      }
      if (typeof eventPayload.output?.output !== "string") {
        writeGatewayEventAudit(directory, {
          hook: "tool-output-truncator",
          stage: "skip",
          reason_code: "output_not_text",
          tool,
        })
        return
      }
      const raw = eventPayload.output.output
      const truncated = truncateText(raw, maxChars, maxLines)
      if (!truncated.lineTruncated && !truncated.charTruncated) {
        writeGatewayEventAudit(directory, {
          hook: "tool-output-truncator",
          stage: "skip",
          reason_code: "within_threshold",
          tool,
          output_chars: raw.length,
        })
        return
      }
      eventPayload.output.output = truncated.text
      writeGatewayEventAudit(directory, {
        hook: "tool-output-truncator",
        stage: "state",
        reason_code: "tool_output_truncated",
        tool,
        output_chars_before: raw.length,
        output_chars_after: truncated.text.length,
        line_truncated: truncated.lineTruncated,
        char_truncated: truncated.charTruncated,
      })
    },
  }
}
