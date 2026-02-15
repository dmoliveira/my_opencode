import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"

interface ToolAfterPayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
  }
  output?: {
    output?: unknown
  }
  directory?: string
}

// Returns true when output from tool is eligible for semantic compression.
function eligibleTool(tool: string): boolean {
  return tool === "bash" || tool === "read"
}

// Returns unique lines that contain diagnostics keywords.
function diagnosticLines(lines: string[], maxLines: number): string[] {
  const collected: string[] = []
  const seen = new Set<string>()
  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed) {
      continue
    }
    if (!/(error|failed|exception|warning|traceback|not found|timeout)/i.test(trimmed)) {
      continue
    }
    if (seen.has(trimmed)) {
      continue
    }
    seen.add(trimmed)
    collected.push(trimmed)
    if (collected.length >= maxLines) {
      break
    }
  }
  return collected
}

// Creates semantic output summarizer for repetitive large tool outputs.
export function createSemanticOutputSummarizerHook(options: {
  directory: string
  enabled: boolean
  minChars: number
  minLines: number
  maxSummaryLines: number
}): GatewayHook {
  const minChars = options.minChars > 0 ? options.minChars : 20000
  const minLines = options.minLines > 0 ? options.minLines : 400
  const maxSummaryLines = options.maxSummaryLines > 0 ? options.maxSummaryLines : 8
  return {
    id: "semantic-output-summarizer",
    priority: 260,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.after") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolAfterPayload
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase()
      if (!eligibleTool(tool) || typeof eventPayload.output?.output !== "string") {
        return
      }
      const raw = eventPayload.output.output
      if (raw.length < minChars) {
        return
      }
      const lines = raw.split(/\r?\n/)
      if (lines.length < minLines) {
        return
      }
      const uniqueLineCount = new Set(lines.map((line) => line.trim())).size
      const repetitionRatio = lines.length <= 1 ? 0 : (lines.length - uniqueLineCount) / lines.length
      if (repetitionRatio < 0.45) {
        return
      }
      const highlights = diagnosticLines(lines, maxSummaryLines)
      const summary = [
        `[semantic-output-summarizer] compressed repetitive output (${lines.length} lines, ${raw.length} chars).`,
        `Repetition ratio: ${(repetitionRatio * 100).toFixed(1)}%.`,
        highlights.length > 0 ? "Key diagnostics:" : "No explicit diagnostics detected in repetitive output.",
        ...highlights.map((line) => `- ${line}`),
      ].join("\n")
      eventPayload.output.output = summary
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "")
      writeGatewayEventAudit(directory, {
        hook: "semantic-output-summarizer",
        stage: "state",
        reason_code: "large_output_semantically_summarized",
        session_id: sessionId,
      })
    },
  }
}
