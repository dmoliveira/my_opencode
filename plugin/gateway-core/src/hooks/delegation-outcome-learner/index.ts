import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import { getRecentDelegationOutcomes } from "../shared/delegation-runtime-state.js"
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
      category?: string
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

export function createDelegationOutcomeLearnerHook(options: {
  directory: string
  enabled: boolean
  windowMs: number
  minSamples: number
  highFailureRate: number
  agentPolicyOverrides: Record<string, {
    minSamples?: number
    highFailureRate?: number
    protectCategories?: string[]
  }>
}): GatewayHook {
  return {
    id: "delegation-outcome-learner",
    priority: 293,
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
      const subagentType = String(args.subagent_type ?? "").toLowerCase().trim()
      if (!subagentType) {
        return
      }
      const policy = options.agentPolicyOverrides[subagentType] ?? {}
      const minSamples = Math.max(1, Number(policy.minSamples ?? options.minSamples))
      const highFailureRate = Number(policy.highFailureRate ?? options.highFailureRate)
      const outcomes = getRecentDelegationOutcomes(options.windowMs).filter(
        (record) => record.subagentType === subagentType,
      )
      if (outcomes.length < minSamples) {
        return
      }
      const failed = outcomes.filter((record) => record.status === "failed").length
      const failureRate = failed / outcomes.length
      if (failureRate < highFailureRate) {
        return
      }
      const currentCategory =
        String(args.category ?? "balanced").toLowerCase().trim() || "balanced"
      const protectedCategories = new Set(
        Array.isArray(policy.protectCategories)
          ? policy.protectCategories.map((item) => String(item).toLowerCase().trim()).filter(Boolean)
          : [],
      )
      const adaptedCategory =
        protectedCategories.has(currentCategory)
          ? currentCategory
          :
        currentCategory === "critical" || currentCategory === "deep"
          ? "balanced"
          : currentCategory
      if (adaptedCategory !== currentCategory) {
        args.category = adaptedCategory
      }
      const hint = `[DELEGATION LEARNER] Recent outcomes for ${subagentType}: failures=${failed}/${outcomes.length} (${failureRate.toFixed(2)}). Prefer resilient, scoped delegation with explicit validation and fallback steps.`
      args.prompt = prependHint(String(args.prompt ?? ""), hint)
      args.description = prependHint(String(args.description ?? ""), hint)

      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      writeGatewayEventAudit(directory, {
        hook: "delegation-outcome-learner",
        stage: "state",
        reason_code: "delegation_policy_adapted_from_outcomes",
        session_id: sessionId(eventPayload),
        trace_id: traceId,
        subagent_type: subagentType,
        failures: String(failed),
        samples: String(outcomes.length),
        failure_rate: String(failureRate),
        min_samples: String(minSamples),
        high_failure_rate: String(highFailureRate),
        original_category: currentCategory,
        adapted_category: adaptedCategory,
      })
    },
  }
}
