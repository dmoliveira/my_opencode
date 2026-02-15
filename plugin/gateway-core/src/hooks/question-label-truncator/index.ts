import type { GatewayHook } from "../registry.js"

interface ToolBeforePayload {
  input?: { tool?: string }
  output?: {
    args?: {
      questions?: Array<{
        options?: Array<{ label?: unknown }>
      }>
    }
  }
}

// Truncates option label when it exceeds configured maximum length.
function truncateLabel(value: string, maxLength: number): string {
  if (value.length <= maxLength) {
    return value
  }
  return `${value.slice(0, Math.max(1, maxLength - 3))}...`
}

// Creates hook that truncates overly long question option labels.
export function createQuestionLabelTruncatorHook(options: {
  enabled: boolean
  maxLength: number
}): GatewayHook {
  const maxLength = options.maxLength >= 8 ? options.maxLength : 30
  return {
    id: "question-label-truncator",
    priority: 380,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolBeforePayload
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase()
      if (tool !== "question") {
        return
      }
      const questions = eventPayload.output?.args?.questions
      if (!Array.isArray(questions)) {
        return
      }
      for (const question of questions) {
        if (!Array.isArray(question.options)) {
          continue
        }
        for (const option of question.options) {
          if (typeof option.label !== "string") {
            continue
          }
          option.label = truncateLabel(option.label, maxLength)
        }
      }
    },
  }
}
