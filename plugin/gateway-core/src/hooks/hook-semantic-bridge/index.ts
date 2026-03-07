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

const SEMANTIC_MAP: Array<{ upstream: RegExp; local: string; key: string }> = [
  { upstream: /\bsisyphus\b/i, local: "orchestrator", key: "sisyphus" },
  {
    upstream: /\bmodel-fallback\b|\bruntime-fallback\b/i,
    local: "provider-error-classifier + provider-retry-backoff-guidance",
    key: "fallback",
  },
  {
    upstream: /\bstart-work\b/i,
    local: "autopilot and workflow runtime commands",
    key: "start-work",
  },
  {
    upstream: /\bstartup-toast\b|\bsession-notification\b|\bbackground-notification\b/i,
    local: "notify-events hook",
    key: "notifications",
  },
]

export function createHookSemanticBridgeHook(options: {
  directory: string
  enabled: boolean
}): GatewayHook {
  return {
    id: "hook-semantic-bridge",
    priority: 288,
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
      const traceId = resolveDelegationTraceId(args)
      const combined = `${String(args.prompt ?? "")}\n${String(args.description ?? "")}`
      const matches = SEMANTIC_MAP.filter((entry) => entry.upstream.test(combined))
      if (matches.length === 0) {
        return
      }
      const mapping = matches.map((entry) => `${entry.key}->${entry.local}`).join("; ")
      const hint = `[HOOK SEMANTIC BRIDGE] Upstream semantics detected. Local runtime mappings: ${mapping}.`
      args.prompt = prependHint(String(args.prompt ?? ""), hint)
      args.description = prependHint(String(args.description ?? ""), hint)
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      writeGatewayEventAudit(directory, {
        hook: "hook-semantic-bridge",
        stage: "state",
        reason_code: "hook_semantic_bridge_applied",
        session_id: sessionId(eventPayload),
        trace_id: traceId,
        mapping_count: String(matches.length),
        mappings: mapping,
      })
    },
  }
}
