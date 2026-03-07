import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import { resolveDelegationTraceId } from "../shared/delegation-trace.js"

interface ToolPayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
  }
  output?: {
    args?: {
      subagent_type?: string
      prompt?: string
      description?: string
    }
  }
  directory?: string
}

function sessionId(payload: ToolPayload): string {
  return String(payload.input?.sessionID ?? payload.input?.sessionId ?? "").trim()
}

function prependHint(original: string, hint: string): string {
  if (!original.trim()) {
    return hint
  }
  if (original.includes(hint)) {
    return original
  }
  return `${hint}\n\n${original}`
}

function detectRewriteSource(text: string): "route" | "fallback" | null {
  if (text.includes("[delegation-fallback-orchestrator]")) {
    return "fallback"
  }
  if (/\[DELEGATION ROUTER(?:\s+[^\]]+)?\]/i.test(text)) {
    return "route"
  }
  return null
}

export function createAgentDiscoverabilityInjectorHook(options: {
  directory: string
  enabled: boolean
  cooldownMs: number
}): GatewayHook {
  const lastInjectedAtBySession = new Map<string, number>()
  return {
    id: "agent-discoverability-injector",
    priority: 294,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolPayload
      if (String(eventPayload.input?.tool ?? "").toLowerCase().trim() !== "task") {
        return
      }
      const args = eventPayload.output?.args
      if (!args || typeof args !== "object") {
        return
      }
      const sid = sessionId(eventPayload)
      const now = Date.now()
      const last = sid ? lastInjectedAtBySession.get(sid) ?? 0 : 0
      if (sid && options.cooldownMs > 0 && now - last < options.cooldownMs) {
        return
      }
      const traceId = resolveDelegationTraceId(args)
      const combined = `${String(args.prompt ?? "")}\n${String(args.description ?? "")}`
      if (combined.includes("/agent-catalog")) {
        return
      }
      const source = detectRewriteSource(combined)
      if (!source) {
        return
      }
      const subagentType = String(args.subagent_type ?? "").toLowerCase().trim()
      const hint = subagentType
        ? `[AGENT CATALOG] Inspect details with: /agent-catalog explain ${subagentType}`
        : "[AGENT CATALOG] Inspect details with: /agent-catalog list"
      args.prompt = prependHint(String(args.prompt ?? ""), hint)
      args.description = prependHint(String(args.description ?? ""), hint)
      if (sid) {
        lastInjectedAtBySession.set(sid, now)
      }
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      writeGatewayEventAudit(directory, {
        hook: "agent-discoverability-injector",
        stage: "state",
        reason_code: "agent_discoverability_hint_injected",
        session_id: sid,
        trace_id: traceId,
        subagent_type: subagentType || undefined,
        trigger_source: source,
        cooldown_ms: String(options.cooldownMs),
      })
    },
  }
}
