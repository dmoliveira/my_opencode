import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"

interface ToolBeforePayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
  }
  properties?: {
    isSubagent?: unknown
  }
  directory?: string
}

// Returns true when session appears to belong to a subagent.
function isSubagentSession(payload: ToolBeforePayload, patterns: string[]): boolean {
  if (payload.properties?.isSubagent === true) {
    return true
  }
  const sessionId = payload.input?.sessionID ?? payload.input?.sessionId ?? ""
  const lower = String(sessionId).toLowerCase()
  return patterns.some((pattern) => lower.includes(pattern.toLowerCase()))
}

// Creates blocker hook preventing subagent use of question tool.
export function createSubagentQuestionBlockerHook(options: {
  directory: string
  enabled: boolean
  sessionPatterns: string[]
}): GatewayHook {
  return {
    id: "subagent-question-blocker",
    priority: 320,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolBeforePayload
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? ""
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase()
      if (tool !== "question" && tool !== "askuserquestion") {
        return
      }
      if (!isSubagentSession(eventPayload, options.sessionPatterns)) {
        return
      }
      writeGatewayEventAudit(directory, {
        hook: "subagent-question-blocker",
        stage: "skip",
        reason_code: "subagent_question_blocked",
        session_id: String(sessionId),
      })
      throw new Error(
        "Question tool is disabled for subagent sessions. Subagents should complete work autonomously and report back to the parent agent.",
      )
    },
  }
}
