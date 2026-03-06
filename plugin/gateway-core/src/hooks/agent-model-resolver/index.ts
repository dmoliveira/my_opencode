import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import { loadAgentMetadata } from "../shared/agent-metadata.js"

interface ToolBeforePayload {
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

const MODEL_BY_CATEGORY: Record<string, { model: string; reasoning: string }> = {
  quick: { model: "openai/gpt-5.1-codex-mini", reasoning: "low" },
  balanced: { model: "openai/gpt-5.3-codex", reasoning: "medium" },
  deep: { model: "openai/gpt-5.3-codex", reasoning: "high" },
  critical: { model: "openai/gpt-5.3-codex", reasoning: "xhigh" },
  visual: { model: "openai/gpt-5.3-codex", reasoning: "medium" },
  writing: { model: "openai/gpt-5.3-codex", reasoning: "medium" },
}

function sessionId(payload: ToolBeforePayload): string {
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

export function createAgentModelResolverHook(options: {
  directory: string
  enabled: boolean
}): GatewayHook {
  return {
    id: "agent-model-resolver",
    priority: 292,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolBeforePayload
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase().trim()
      if (tool !== "task") {
        return
      }
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const args = eventPayload.output?.args
      if (!args || typeof args !== "object") {
        return
      }
      const subagentType = String(args.subagent_type ?? "").toLowerCase().trim()
      if (!subagentType) {
        return
      }
      const metadata = loadAgentMetadata(directory).get(subagentType)
      const category = metadata?.default_category
      if (!category || !MODEL_BY_CATEGORY[category]) {
        return
      }
      const model = MODEL_BY_CATEGORY[category]
      const hint = `[MODEL ROUTING] Preferred category=${category}; model=${model.model}; reasoning=${model.reasoning}; fallback_policy=${metadata?.fallback_policy ?? "openai-default-with-alt-fallback"}.`
      args.prompt = prependHint(String(args.prompt ?? ""), hint)
      args.description = prependHint(String(args.description ?? ""), hint)
      writeGatewayEventAudit(directory, {
        hook: "agent-model-resolver",
        stage: "state",
        reason_code: "agent_model_routing_hint_injected",
        session_id: sessionId(eventPayload),
        subagent_type: subagentType,
        recommended_category: category,
        model: model.model,
        reasoning: model.reasoning,
      })
    },
  }
}
