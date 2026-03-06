import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import { loadAgentMetadata } from "../shared/agent-metadata.js"

interface ToolPayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
  }
  output?: {
    args?: {
      subagent_type?: string
      category?: string
      prompt?: string
      description?: string
    }
  }
  directory?: string
}

interface BudgetRecord {
  ts: number
  provider: string
  model: string
  estimatedTokens: number
}

const MODEL_BY_CATEGORY: Record<string, string> = {
  quick: "openai/gpt-5.1-codex-mini",
  balanced: "openai/gpt-5.3-codex",
  deep: "openai/gpt-5.3-codex",
  critical: "openai/gpt-5.3-codex",
  visual: "openai/gpt-5.3-codex",
  writing: "openai/gpt-5.3-codex",
}

function sessionId(payload: ToolPayload): string {
  return String(payload.input?.sessionID ?? payload.input?.sessionId ?? "").trim()
}

function estimateTokens(text: string): number {
  if (!text.trim()) {
    return 64
  }
  return Math.max(64, Math.ceil(text.length / 4))
}

export function createProviderModelBudgetEnforcerHook(options: {
  directory: string
  enabled: boolean
  windowMs: number
  maxDelegationsPerWindow: number
  maxEstimatedTokensPerWindow: number
  maxPerModelDelegationsPerWindow: number
}): GatewayHook {
  const records: BudgetRecord[] = []

  return {
    id: "provider-model-budget-enforcer",
    priority: 317,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolPayload
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase().trim()
      if (tool !== "task") {
        return
      }
      const args = eventPayload.output?.args
      if (!args || typeof args !== "object") {
        return
      }
      const subagentType = String(args.subagent_type ?? "").toLowerCase().trim()
      const categoryArg = String(args.category ?? "").toLowerCase().trim()
      if (!subagentType && !categoryArg) {
        return
      }
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory

      const metadata = subagentType ? loadAgentMetadata(directory).get(subagentType) : undefined
      const fallbackCategory = categoryArg.length > 0 ? categoryArg : "balanced"
      const category = String(
        metadata?.default_category ?? fallbackCategory,
      ).toLowerCase()
      const model = MODEL_BY_CATEGORY[category] ?? "openai/gpt-5.3-codex"
      const provider = model.split("/", 1)[0] || "openai"
      const estimatedTokens = estimateTokens(
        `${String(args.prompt ?? "")}\n${String(args.description ?? "")}`,
      )

      const now = Date.now()
      const minTs = now - options.windowMs
      while (records.length > 0 && records[0]!.ts < minTs) {
        records.shift()
      }

      const providerWindow = records.filter((record) => record.provider === provider)
      const modelWindow = providerWindow.filter((record) => record.model === model)
      const providerDelegations = providerWindow.length
      const providerTokens = providerWindow.reduce((sum, record) => sum + record.estimatedTokens, 0)
      const modelDelegations = modelWindow.length

      if (providerDelegations >= options.maxDelegationsPerWindow) {
        writeGatewayEventAudit(directory, {
          hook: "provider-model-budget-enforcer",
          stage: "guard",
          reason_code: "provider_budget_delegations_exceeded",
          session_id: sessionId(eventPayload),
          provider,
          provider_delegations: String(providerDelegations),
        })
        throw new Error(
          `Blocked delegation: provider ${provider} reached maxDelegationsPerWindow=${options.maxDelegationsPerWindow}.`,
        )
      }
      if (providerTokens + estimatedTokens > options.maxEstimatedTokensPerWindow) {
        writeGatewayEventAudit(directory, {
          hook: "provider-model-budget-enforcer",
          stage: "guard",
          reason_code: "provider_budget_tokens_exceeded",
          session_id: sessionId(eventPayload),
          provider,
          provider_tokens: String(providerTokens),
          estimated_tokens: String(estimatedTokens),
        })
        throw new Error(
          `Blocked delegation: provider ${provider} would exceed maxEstimatedTokensPerWindow=${options.maxEstimatedTokensPerWindow}.`,
        )
      }
      if (modelDelegations >= options.maxPerModelDelegationsPerWindow) {
        writeGatewayEventAudit(directory, {
          hook: "provider-model-budget-enforcer",
          stage: "guard",
          reason_code: "model_budget_delegations_exceeded",
          session_id: sessionId(eventPayload),
          model,
          model_delegations: String(modelDelegations),
        })
        throw new Error(
          `Blocked delegation: model ${model} reached maxPerModelDelegationsPerWindow=${options.maxPerModelDelegationsPerWindow}.`,
        )
      }

      records.push({
        ts: now,
        provider,
        model,
        estimatedTokens,
      })
      writeGatewayEventAudit(directory, {
        hook: "provider-model-budget-enforcer",
        stage: "state",
        reason_code: "provider_model_budget_reserved",
        session_id: sessionId(eventPayload),
        provider,
        model,
        estimated_tokens: String(estimatedTokens),
        category,
      })
    },
  }
}
