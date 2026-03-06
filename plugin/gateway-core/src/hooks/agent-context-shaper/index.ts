import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import { loadAgentMetadata, type AgentRoutingMetadata } from "../shared/agent-metadata.js"

interface ToolBeforePayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
  }
  output?: {
    args?: {
      subagent_type?: string
      category?: string
    }
  }
}

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

interface SessionDeletedPayload {
  properties?: {
    info?: {
      id?: string
    }
  }
}

interface StoredContext {
  subagentType: string
  category: string
  metadata: AgentRoutingMetadata
}

function sessionId(payload: {
  input?: { sessionID?: string; sessionId?: string }
  properties?: { info?: { id?: string } }
}): string {
  return String(payload.input?.sessionID ?? payload.input?.sessionId ?? payload.properties?.info?.id ?? "").trim()
}

function looksLikeFailure(text: string): boolean {
  return /(\[error\]|invalid arguments|failed|exception|traceback|unknown\s+agent|unknown\s+category)/i.test(
    text,
  )
}

function buildHint(context: StoredContext): string {
  const trigger = Array.isArray(context.metadata.triggers) && context.metadata.triggers.length > 0
    ? context.metadata.triggers[0]
    : "verify delegation intent"
  const avoid = Array.isArray(context.metadata.avoid_when) && context.metadata.avoid_when.length > 0
    ? context.metadata.avoid_when[0]
    : "avoid mismatched scope"
  return [
    "[agent-context-shaper] delegation context",
    `- subagent: ${context.subagentType}`,
    `- recommended_category: ${context.category}`,
    `- cost_tier: ${context.metadata.cost_tier ?? "unknown"}`,
    `- next_best_trigger: ${trigger}`,
    `- avoid_when: ${avoid}`,
  ].join("\n")
}

export function createAgentContextShaperHook(options: {
  directory: string
  enabled: boolean
}): GatewayHook {
  const contextBySession = new Map<string, StoredContext>()
  return {
    id: "agent-context-shaper",
    priority: 294,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }
      if (type === "session.deleted") {
        const sid = sessionId((payload ?? {}) as SessionDeletedPayload)
        if (sid) {
          contextBySession.delete(sid)
        }
        return
      }
      if (type === "tool.execute.before") {
        const eventPayload = (payload ?? {}) as ToolBeforePayload
        const tool = String(eventPayload.input?.tool ?? "").toLowerCase().trim()
        if (tool !== "task") {
          return
        }
        const sid = sessionId(eventPayload)
        if (!sid) {
          return
        }
        const subagentType = String(eventPayload.output?.args?.subagent_type ?? "").toLowerCase().trim()
        if (!subagentType) {
          contextBySession.delete(sid)
          return
        }
        const metadata = loadAgentMetadata(options.directory).get(subagentType) ?? {}
        const category = String(eventPayload.output?.args?.category ?? metadata.default_category ?? "balanced")
        contextBySession.set(sid, {
          subagentType,
          category,
          metadata,
        })
        return
      }
      if (type !== "tool.execute.after") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolAfterPayload
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase().trim()
      if (tool !== "task" || typeof eventPayload.output?.output !== "string") {
        return
      }
      const sid = sessionId(eventPayload)
      if (!sid) {
        return
      }
      const context = contextBySession.get(sid)
      if (!context) {
        return
      }
      const output = eventPayload.output.output
      if (!looksLikeFailure(output) && output.length < 1200) {
        return
      }
      const hint = buildHint(context)
      if (!output.includes("[agent-context-shaper]")) {
        eventPayload.output.output = `${output}\n\n${hint}`
      }
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      writeGatewayEventAudit(directory, {
        hook: "agent-context-shaper",
        stage: "state",
        reason_code: "agent_context_hint_appended",
        session_id: sid,
        subagent_type: context.subagentType,
        recommended_category: context.category,
      })
    },
  }
}
