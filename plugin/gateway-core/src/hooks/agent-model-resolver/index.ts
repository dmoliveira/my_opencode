import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import { loadAgentMetadata } from "../shared/agent-metadata.js"
import { annotateDelegationMetadata, resolveDelegationTraceId } from "../shared/delegation-trace.js"
import {
  buildCompactDecisionCacheKey,
  type LlmDecisionRuntime,
  writeDecisionComparisonAudit,
} from "../shared/llm-decision-runtime.js"

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
      prompt?: string
      description?: string
    }
    metadata?: unknown
  }
  directory?: string
}

const MODEL_BY_CATEGORY: Record<string, { model: string; reasoning: string }> = {
  quick: { model: "openai/gpt-5.1-codex-mini", reasoning: "low" },
  balanced: { model: "openai/gpt-5.3-codex", reasoning: "medium" },
  deep: { model: "openai/gpt-5.4-codex", reasoning: "medium" },
  critical: { model: "openai/gpt-5.4-codex", reasoning: "medium" },
  visual: { model: "openai/gpt-5.3-codex", reasoning: "medium" },
  writing: { model: "openai/gpt-5.3-codex", reasoning: "medium" },
}

const ROUTING_PATTERNS: Array<{ subagentType: string; patterns: RegExp[] }> = [
  {
    subagentType: "explore",
    patterns: [
      /\b(where|locat(e|ion)|find|search|inventory|map pattern|usage(s)?)\b/i,
      /\bcodebase|repository|module(s)?\b/i,
    ],
  },
  {
    subagentType: "librarian",
    patterns: [
      /\bofficial docs?|upstream|library|framework|api reference\b/i,
      /\bexternal|oss|open\s*source|github\b/i,
    ],
  },
  {
    subagentType: "tasker",
    patterns: [
      /\btasker|planning[-\s]only|planning only|backlog|dependency|dependencies\b/i,
      /\bcodememory|\boc\b|epic|durable note|durable memory|capture plan|plan capture\b/i,
    ],
  },
  {
    subagentType: "verifier",
    patterns: [
      /\b(run|execute)\s+(tests?|lint|build)\b/i,
      /\bverify|validation|triage|failing checks?\b/i,
    ],
  },
  {
    subagentType: "reviewer",
    patterns: [
      /\breview|risk|regression|safety|correctness\b/i,
      /\bquality pass|final pass\b/i,
    ],
  },
  {
    subagentType: "release-scribe",
    patterns: [
      /\brelease notes?|changelog|pr summary|release summary\b/i,
      /\bmilestone|announcement\b/i,
    ],
  },
  {
    subagentType: "oracle",
    patterns: [
      /\barchitecture|trade\s*off|security|performance\b/i,
      /\bdebug|hard problem|uncertainty|repeated failures?\b/i,
    ],
  },
  {
    subagentType: "strategic-planner",
    patterns: [
      /\bplan|milestone|roadmap|sequence|execution plan\b/i,
      /\bbreak down|phase(s)?\b/i,
    ],
  },
  {
    subagentType: "ambiguity-analyst",
    patterns: [/\bambiguity|unknowns?|assumption(s)?|decision fork\b/i],
  },
  {
    subagentType: "plan-critic",
    patterns: [/\bcritique|feasibility|coverage|testability|plan review\b/i],
  },
]

const SUBAGENT_ICON_BY_TYPE: Record<string, { nerd: string; fallback: string }> = {
  explore: { nerd: "󰍉", fallback: "[scan]" },
  tasker: { nerd: "󰚡", fallback: "[plan]" },
  librarian: { nerd: "󰂺", fallback: "[docs]" },
  verifier: { nerd: "󰄬", fallback: "[check]" },
  reviewer: { nerd: "󰦨", fallback: "[review]" },
  "release-scribe": { nerd: "󰜘", fallback: "[notes]" },
  oracle: { nerd: "󱠓", fallback: "[advisor]" },
  "strategic-planner": { nerd: "󱎸", fallback: "[plan]" },
  "ambiguity-analyst": { nerd: "󰋗", fallback: "[clarify]" },
  "plan-critic": { nerd: "󰒠", fallback: "[critic]" },
  orchestrator: { nerd: "󰯲", fallback: "[lead]" },
}

const ROUTING_CHAR_BY_AGENT: Record<string, string> = {
  explore: "E",
  tasker: "D",
  librarian: "L",
  verifier: "V",
  reviewer: "R",
  "release-scribe": "S",
  oracle: "O",
  "ambiguity-analyst": "A",
  "strategic-planner": "T",
  "plan-critic": "P",
}

const AGENT_BY_ROUTING_CHAR = new Map<string, string>(
  Object.entries(ROUTING_CHAR_BY_AGENT).map(([agent, code]) => [code, agent]),
)

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

function formatTimestamp(date: Date): { full: string; time: string } {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, "0")
  const day = String(date.getDate()).padStart(2, "0")
  const hours = String(date.getHours()).padStart(2, "0")
  const minutes = String(date.getMinutes()).padStart(2, "0")
  const seconds = String(date.getSeconds()).padStart(2, "0")
  const time = `${hours}:${minutes}:${seconds}`
  return {
    full: `${year}-${month}-${day} ${time}`,
    time,
  }
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

function stripHeaderLine(original: string, header: string): string {
  return original.replace(new RegExp(`^\\[${escapeRegex(header)}(?: [^\\]]+)?\\].*(?:\\n|$)`, "gmi"), "")
}

function stripInjectedHeaders(original: string): string {
  return [
    "SUBAGENT",
    "DELEGATION ROUTER",
    "MODEL ROUTING",
    "TOOL SURFACE",
    "SESSION FLOW",
    "WORKTREE CONTEXT",
    "THINKING EFFORT",
  ]
    .reduce((text, header) => stripHeaderLine(text, header), original)
    .trimStart()
}

function formatHeader(header: string, body: string, timestamp?: string): string {
  const marker = timestamp ? `${header} ${timestamp}` : header
  return `[${marker}] ${body}`
}

function inferSubagentType(text: string, available: Set<string>): { name: string; score: number } | null {
  const source = text.trim()
  if (!source) {
    return null
  }
  const lower = source.toLowerCase()
  for (const candidate of available) {
    if (lower.includes(candidate)) {
      return { name: candidate, score: 3 }
    }
  }
  let best: { name: string; score: number } | null = null
  for (const rule of ROUTING_PATTERNS) {
    if (!available.has(rule.subagentType)) {
      continue
    }
    const score = rule.patterns.reduce((count, pattern) => (pattern.test(source) ? count + 1 : count), 0)
    if (score <= 0) {
      continue
    }
    if (!best || score > best.score) {
      best = { name: rule.subagentType, score }
    }
  }
  return best && best.score >= 1 ? best : null
}

function scoreSubagentIntent(text: string, subagentType: string): number {
  const source = text.trim()
  if (!source) {
    return 0
  }
  const lower = source.toLowerCase()
  let score = lower.includes(subagentType) ? 2 : 0
  const rule = ROUTING_PATTERNS.find((candidate) => candidate.subagentType === subagentType)
  if (!rule) {
    return score
  }
  score += rule.patterns.reduce((count, pattern) => (pattern.test(source) ? count + 1 : count), 0)
  return score
}

function normalizeToolList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value
    .filter((item): item is string => typeof item === "string")
    .map((item) => item.trim())
    .filter((item) => item.length > 0)
}

const MUTATION_TOOL_MARKERS = new Set(["bash", "write", "edit", "task"])

const MUTATING_INTENT_RULES: Array<{ label: string; pattern: RegExp }> = [
  { label: "git_commit", pattern: /\bgit\s+commit\b|\bcommit\s+(changes?|code|files?)\b/i },
  {
    label: "pull_request",
    pattern:
      /\b(create|open|file|submit|merge|close|update)\s+(a\s+)?(pr|pull\s*request)\b|\bgh\s+pr\s+(create|merge)\b/i,
  },
  { label: "git_push", pattern: /\bgit\s+push\b|\bpush\s+(to\s+)?(origin|remote)\b/i },
  { label: "git_rewrite", pattern: /\bgit\s+(rebase|cherry-pick|reset|amend)\b/i },
  {
    label: "code_edit",
    pattern:
      /\b(edit|modify|rewrite|refactor|implement|apply\s+patch|write)\s+(the\s+)?(code|file|files|docs?|documentation)\b/i,
  },
]

const NEGATED_MUTATION_PATTERNS: RegExp[] = [
  /\b(without|do\s+not|don't|avoid|no)\s+(editing|edits?|modifying|changes?|rewriting|refactoring|implementing|writing)\s+(the\s+)?(code|file|files|docs?|documentation)\b/gi,
  /\b(no\s+file\s+edits?|without\s+file\s+edits?|no\s+code\s+changes?|without\s+code\s+changes?)\b/gi,
  /\b(read-?only|non-?mutating)\b/gi,
]

const EPHEMERAL_ARTIFACT_HINT_PATTERN =
  /\b(--output\b|runtime\/|\/tmp\b|temp\b|sqlite\b|\.db\b|\.log\b|artifact\b|cache\b|generated\b)\b/i

function detectMutatingIntent(text: string): string[] {
  const normalized = NEGATED_MUTATION_PATTERNS.reduce(
    (acc, pattern) => acc.replace(pattern, " "),
    text,
  )
  return MUTATING_INTENT_RULES.filter((rule) => rule.pattern.test(normalized)).map((rule) => rule.label)
}

function allowsEphemeralVerifierIntent(subagentType: string, text: string, signals: string[]): boolean {
  if (subagentType !== "verifier") {
    return false
  }
  if (signals.some((label) => label !== "code_edit")) {
    return false
  }
  return EPHEMERAL_ARTIFACT_HINT_PATTERN.test(text)
}

function enforcesReadOnlySurface(deniedTools: string[]): boolean {
  return deniedTools.some((tool) => MUTATION_TOOL_MARKERS.has(String(tool).toLowerCase().trim()))
}

interface AgentRuntimePolicy {
  overrideDelta?: number
  intentThreshold?: number
}

function routingAlphabet(inferredSubagent: string, explicitSubagent: string): string[] {
  const chars = new Set<string>()
  const inferredChar = ROUTING_CHAR_BY_AGENT[inferredSubagent]
  const explicitChar = ROUTING_CHAR_BY_AGENT[explicitSubagent]
  if (inferredChar) {
    chars.add(inferredChar)
  }
  if (explicitChar) {
    chars.add(explicitChar)
  }
  if (explicitSubagent) {
    chars.add("K")
  }
  chars.add("N")
  return [...chars]
}

function buildRoutingInstruction(inferredSubagent: string, explicitSubagent: string): string {
  const options: string[] = []
  const inferredChar = ROUTING_CHAR_BY_AGENT[inferredSubagent]
  const explicitChar = ROUTING_CHAR_BY_AGENT[explicitSubagent]
  if (inferredChar) {
    options.push(`${inferredChar}=${inferredSubagent}`)
  }
  if (explicitChar && explicitSubagent && explicitSubagent !== inferredSubagent) {
    options.push(`${explicitChar}=${explicitSubagent}`)
  }
  if (explicitSubagent) {
    options.push("K=keep explicit choice")
  }
  options.push("N=no-opinion")
  return `Pick the best subagent for this task. ${options.join(", ")}.`
}

function buildRoutingDecisionMeaning(inferredSubagent: string, explicitSubagent: string): Record<string, string> {
  const meaning: Record<string, string> = { N: "no_opinion" }
  const inferredChar = ROUTING_CHAR_BY_AGENT[inferredSubagent]
  const explicitChar = ROUTING_CHAR_BY_AGENT[explicitSubagent]
  if (inferredChar) {
    meaning[inferredChar] = `route_${inferredSubagent}`
  }
  if (explicitChar && explicitSubagent && explicitSubagent !== inferredSubagent) {
    meaning[explicitChar] = `route_${explicitSubagent}`
  }
  if (explicitSubagent) {
    meaning.K = "keep_explicit_choice"
  }
  return meaning
}

function buildRoutingContext(
  prompt: string,
  description: string,
  explicitSubagent: string,
  inferredSubagent: string,
  inferredScore: number,
  explicitScore: number,
): string {
  return [
    `explicit_subagent=${explicitSubagent || "none"}`,
    `heuristic_inferred=${inferredSubagent || "none"}`,
    `heuristic_inferred_score=${String(inferredScore)}`,
    `heuristic_explicit_score=${String(explicitScore)}`,
    "prompt:",
    prompt.trim() || "(empty)",
    "description:",
    description.trim() || "(empty)",
  ].join("\n")
}

function policyForAgent(
  subagentType: string,
  defaults: { overrideDelta: number; intentThreshold: number },
  overrides: Record<string, AgentRuntimePolicy>,
): { overrideDelta: number; intentThreshold: number } {
  const normalized = subagentType.trim().toLowerCase()
  const policy = overrides[normalized] ?? {}
  const overrideDelta = Math.max(0, Number(policy.overrideDelta ?? defaults.overrideDelta))
  const intentThreshold = Math.max(0, Number(policy.intentThreshold ?? defaults.intentThreshold))
  return { overrideDelta, intentThreshold }
}

function formatSubagentLabel(subagentType: string, reasoning: string, timestamp: string): string {
  const icon = SUBAGENT_ICON_BY_TYPE[subagentType] ?? {
    nerd: "󰚩",
    fallback: "[agent]",
  }
  return formatHeader("SUBAGENT", `${icon.nerd} ${subagentType} ${icon.fallback} | effort=${reasoning}`, timestamp)
}

export function createAgentModelResolverHook(options: {
  directory: string
  enabled: boolean
  defaultOverrideDelta: number
  defaultIntentThreshold: number
  agentPolicyOverrides: Record<string, AgentRuntimePolicy>
  decisionRuntime?: LlmDecisionRuntime
}): GatewayHook {
  return {
    id: "agent-model-resolver",
    priority: 289,
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
      const traceId = resolveDelegationTraceId(args)
      annotateDelegationMetadata(eventPayload.output ?? {}, args)
      const sid = sessionId(eventPayload)

      const metadataByAgent = loadAgentMetadata(directory)
      const knownAgents = new Set(metadataByAgent.keys())
      const combinedText = `${String(args.prompt ?? "")}\n${String(args.description ?? "")}`

      const originalExplicitSubagent = String(args.subagent_type ?? "").toLowerCase().trim()
      let subagentType = originalExplicitSubagent
      let routeSource = "explicit_subagent_type"
      const hadExplicitSubagent = Boolean(originalExplicitSubagent && knownAgents.has(originalExplicitSubagent))
      const inferred = inferSubagentType(combinedText, knownAgents)
      let explicitScore = 0
      let policy = {
        overrideDelta: options.defaultOverrideDelta,
        intentThreshold: options.defaultIntentThreshold,
      }
      if (!hadExplicitSubagent) {
        if (inferred) {
          subagentType = inferred.name
          args.subagent_type = inferred.name
          routeSource = "inferred_subagent_type"
        }
      } else {
        policy = policyForAgent(
          subagentType,
          {
            overrideDelta: options.defaultOverrideDelta,
            intentThreshold: options.defaultIntentThreshold,
          },
          options.agentPolicyOverrides,
        )
        explicitScore = scoreSubagentIntent(combinedText, subagentType)
        if (
          inferred &&
          inferred.name !== subagentType &&
          inferred.score >= explicitScore + policy.overrideDelta &&
          explicitScore < policy.intentThreshold
        ) {
          const previous = subagentType
          subagentType = inferred.name
          args.subagent_type = inferred.name
          routeSource = "overridden_low_confidence"
          writeGatewayEventAudit(directory, {
            hook: "agent-model-resolver",
            stage: "guard",
            reason_code: "delegation_route_overridden_low_confidence",
            session_id: sessionId(eventPayload),
            trace_id: traceId,
            original_subagent_type: previous,
            inferred_subagent_type: inferred.name,
            original_score: String(explicitScore),
            inferred_score: String(inferred.score),
            override_delta: String(policy.overrideDelta),
            intent_threshold: String(policy.intentThreshold),
          })
        }
      }

      const aiInferred = inferred
      const alphabet = aiInferred ? routingAlphabet(aiInferred.name, originalExplicitSubagent) : []
      const shouldRunLlmDecision = Boolean(
        options.decisionRuntime &&
          aiInferred &&
          alphabet.length > 1 &&
          (!hadExplicitSubagent || explicitScore <= policy.intentThreshold),
      )
      if (shouldRunLlmDecision && options.decisionRuntime && aiInferred) {
        const decision = await options.decisionRuntime.decide({
          hookId: "agent-model-resolver",
          sessionId: sid,
          traceId,
          templateId: "delegation-route-v1",
          instruction: buildRoutingInstruction(aiInferred.name, originalExplicitSubagent),
          context: buildRoutingContext(
            String(args.prompt ?? ""),
            String(args.description ?? ""),
            originalExplicitSubagent,
            aiInferred.name,
            aiInferred.score,
            explicitScore,
          ),
          allowedChars: alphabet,
          decisionMeaning: buildRoutingDecisionMeaning(aiInferred.name, originalExplicitSubagent),
          cacheKey: buildCompactDecisionCacheKey({
            prefix: "route",
            parts: [originalExplicitSubagent || "none", aiInferred.name],
            text: buildRoutingContext(
              String(args.prompt ?? ""),
              String(args.description ?? ""),
              originalExplicitSubagent,
              aiInferred.name,
              aiInferred.score,
              explicitScore,
            ),
          }),
        })
        if (decision.accepted) {
          const resolvedChar = decision.char.toUpperCase()
          const aiCandidate =
            resolvedChar === "K"
              ? subagentType
              : resolvedChar === "N"
                ? ""
                : (AGENT_BY_ROUTING_CHAR.get(resolvedChar) ?? "")
          writeDecisionComparisonAudit({
            directory,
            hookId: "agent-model-resolver",
            sessionId: sid,
            traceId,
            mode: options.decisionRuntime.config.mode,
            deterministicMeaning: hadExplicitSubagent
              ? `route_${originalExplicitSubagent}`
              : aiInferred.name
                ? `route_${aiInferred.name}`
                : "no_opinion",
            aiMeaning:
              decision.meaning ||
              (aiCandidate ? `route_${aiCandidate}` : resolvedChar === "N" ? "no_opinion" : "keep_explicit_choice"),
            deterministicValue: hadExplicitSubagent ? originalExplicitSubagent : aiInferred.name,
            aiValue: aiCandidate || resolvedChar,
          })
          writeGatewayEventAudit(directory, {
            hook: "agent-model-resolver",
            stage: "state",
            reason_code: "llm_route_decision_recorded",
            session_id: sid,
            trace_id: traceId,
            subagent_type: subagentType,
            inferred_subagent_type: aiInferred.name,
            llm_decision_char: resolvedChar,
            llm_decision_mode: options.decisionRuntime.config.mode,
            llm_candidate_subagent_type: aiCandidate || undefined,
          })
          const canApplyInferenceOnly =
            !hadExplicitSubagent &&
            options.decisionRuntime.config.mode !== "shadow" &&
            aiCandidate === aiInferred.name
          const canOverrideExplicit =
            hadExplicitSubagent &&
            options.decisionRuntime.config.mode === "enforce" &&
            aiCandidate &&
            knownAgents.has(aiCandidate) &&
            aiCandidate !== subagentType
          if (canApplyInferenceOnly || canOverrideExplicit) {
            const previous = subagentType
            subagentType = aiCandidate
            args.subagent_type = aiCandidate
            routeSource = hadExplicitSubagent
              ? "llm_decision_runtime"
              : "llm_confirmed_inferred_subagent_type"
            writeGatewayEventAudit(directory, {
              hook: "agent-model-resolver",
              stage: "guard",
              reason_code: "llm_route_decision_applied",
              session_id: sid,
              trace_id: traceId,
              original_subagent_type: previous || undefined,
              inferred_subagent_type: aiCandidate,
              llm_decision_char: resolvedChar,
              llm_decision_mode: options.decisionRuntime.config.mode,
            })
          }
        }
      }
      if (!subagentType || !knownAgents.has(subagentType)) {
        return
      }

      const metadata = metadataByAgent.get(subagentType)
      const deniedTools = normalizeToolList(metadata?.denied_tools)
      const mutatingSignals = detectMutatingIntent(combinedText)
      if (
        mutatingSignals.length > 0 &&
        enforcesReadOnlySurface(deniedTools) &&
        !allowsEphemeralVerifierIntent(subagentType, combinedText, mutatingSignals)
      ) {
        writeGatewayEventAudit(directory, {
          hook: "agent-model-resolver",
          stage: "guard",
          reason_code: "delegation_mutation_intent_blocked",
          session_id: sid,
          trace_id: traceId,
          subagent_type: subagentType,
          mutating_signals: mutatingSignals.join(","),
          route_source: routeSource,
        })
        throw new Error(
          `Blocked task delegation for ${subagentType}: prompt requests mutating work but this subagent is read-only. Run commit/PR/edit actions directly with the primary agent.`,
        )
      }
      const explicitCategory = String(args.category ?? "").toLowerCase().trim()
      const requestedCategory =
        explicitCategory && MODEL_BY_CATEGORY[explicitCategory] ? explicitCategory : ""
      const category =
        requestedCategory || String(metadata?.default_category ?? "").toLowerCase().trim()
      if (!category || !MODEL_BY_CATEGORY[category]) {
        return
      }

      args.category = category
      const model = MODEL_BY_CATEGORY[category]
      const stamp = formatTimestamp(new Date())
      const modelHintPrompt = formatHeader(
        "MODEL ROUTING",
        `Preferred category=${category}; model=${model.model}; reasoning=${model.reasoning}; fallback_policy=${metadata?.fallback_policy ?? "openai-default-with-alt-fallback"}.`,
        stamp.full,
      )
      const modelHintDescription = formatHeader(
        "MODEL ROUTING",
        `Preferred category=${category}; model=${model.model}; reasoning=${model.reasoning}; fallback_policy=${metadata?.fallback_policy ?? "openai-default-with-alt-fallback"}.`,
      )
      const allowedTools = normalizeToolList(metadata?.allowed_tools)
      const toolSurface = formatHeader(
        "TOOL SURFACE",
        `subagent=${subagentType}; allowed=${allowedTools.join(",") || "none"}; denied=${deniedTools.join(",") || "none"}.`,
      )
      const routeHint =
        routeSource !== "explicit_subagent_type"
          ? formatHeader("DELEGATION ROUTER", `inferred subagent_type=${subagentType} from delegation intent.`)
          : ""
      const composedPromptHint = [modelHintPrompt, routeHint, toolSurface]
        .filter((part) => part.length > 0)
        .join("\n")
      const composedDescriptionHint = [modelHintDescription, routeHint, toolSurface]
        .filter((part) => part.length > 0)
        .join("\n")
      const flowHint = formatHeader("SESSION FLOW", `parent_session_id=${sid || "unknown"}; trace_id=${traceId}`)
      const worktreeHint = formatHeader(
        "WORKTREE CONTEXT",
        `cwd=${directory}; execute file discovery and validation relative to this path unless prompt explicitly overrides.`,
      )
      const subagentLabel = formatSubagentLabel(subagentType, model.reasoning, stamp.full)

      const cleanPrompt = stripInjectedHeaders(String(args.prompt ?? ""))
      const cleanDescription = stripInjectedHeaders(String(args.description ?? ""))
      args.prompt = prependHint(prependHint(prependHint(cleanPrompt, worktreeHint), flowHint), composedPromptHint)
      args.description = prependHint(
        prependHint(prependHint(prependHint(cleanDescription, composedDescriptionHint), worktreeHint), flowHint),
        subagentLabel,
      )
      annotateDelegationMetadata(eventPayload.output ?? {}, args)

      writeGatewayEventAudit(directory, {
        hook: "agent-model-resolver",
        stage: "state",
        reason_code: "agent_model_routing_hint_injected",
        session_id: sid,
        trace_id: traceId,
        subagent_type: subagentType,
        recommended_category: category,
        model: model.model,
        reasoning: model.reasoning,
        route_source: routeSource,
        tool_surface_injected: "true",
      })
    },
  }
}
