import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import { loadAgentMetadata } from "../shared/agent-metadata.js"
import { resolveDelegationTraceId } from "../shared/delegation-trace.js"

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

function sessionId(payload: ToolBeforePayload): string {
  return String(payload.input?.sessionID ?? payload.input?.sessionId ?? "").trim()
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

function referencesDeniedTool(text: string, tool: string): boolean {
  const escaped = escapeRegex(tool)
  const patterns = [
    new RegExp(`\\b(use|run|execute|call|invoke)\\s+(?:the\\s+)?(?:tool\\s+)?${escaped}\\b`, "i"),
    new RegExp(`\\b${escaped}\\s+tool\\b`, "i"),
    new RegExp(`\\bfunctions\\.${escaped}\\b`, "i"),
    new RegExp(`(?:^|\\s)["'\`]${escaped}["'\`](?:$|\\s)`, "i"),
  ]
  return patterns.some((pattern) => pattern.test(text))
}

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

const MUTATION_TOOL_MARKERS = new Set(["bash", "write", "edit", "task"])

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

function enforcesReadOnlySurface(deniedTools: string[]): boolean {
  return deniedTools.some((tool) => MUTATION_TOOL_MARKERS.has(String(tool).toLowerCase().trim()))
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

function collectStrings(value: unknown, depth = 0): string[] {
  if (depth > 4) {
    return []
  }
  if (typeof value === "string") {
    return [value]
  }
  if (Array.isArray(value)) {
    return value.flatMap((item) => collectStrings(item, depth + 1))
  }
  if (value && typeof value === "object") {
    return Object.values(value as Record<string, unknown>).flatMap((nested) =>
      collectStrings(nested, depth + 1),
    )
  }
  return []
}

function suggestAllowedTool(deniedTool: string, allowedTools: string[]): string | null {
  if (!allowedTools.length) {
    return null
  }
  const replacementMatrix: Record<string, string[]> = {
    bash: ["read", "glob", "grep"],
    write: ["edit", "read"],
    edit: ["read", "write"],
    task: ["read", "glob", "grep"],
    webfetch: ["read", "grep"],
    todowrite: ["todoread", "read"],
  }
  const preferred = replacementMatrix[deniedTool] ?? []
  for (const candidate of preferred) {
    if (allowedTools.includes(candidate)) {
      return candidate
    }
  }
  return allowedTools[0] ?? null
}

export function createAgentDeniedToolEnforcerHook(options: {
  directory: string
  enabled: boolean
}): GatewayHook {
  return {
    id: "agent-denied-tool-enforcer",
    priority: 290,
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
      const subagentType = String(args.subagent_type ?? "").toLowerCase().trim()
      if (!subagentType) {
        return
      }
      const metadata = loadAgentMetadata(directory).get(subagentType)
      const allowed = Array.isArray(metadata?.allowed_tools) ? metadata?.allowed_tools : []
      const denied = Array.isArray(metadata?.denied_tools) ? metadata?.denied_tools : []
      if (!denied || denied.length === 0) {
        return
      }
      const combinedText = collectStrings({
        prompt: args.prompt,
        description: args.description,
      }).join("\n")

      const mutatingSignals = detectMutatingIntent(combinedText)
      if (
        mutatingSignals.length > 0 &&
        enforcesReadOnlySurface(denied) &&
        !allowsEphemeralVerifierIntent(subagentType, combinedText, mutatingSignals)
      ) {
        writeGatewayEventAudit(directory, {
          hook: "agent-denied-tool-enforcer",
          stage: "guard",
          reason_code: "delegation_mutation_intent_blocked",
          session_id: sessionId(eventPayload),
          trace_id: traceId,
          subagent_type: subagentType,
          mutating_signals: mutatingSignals.join(","),
        })
        throw new Error(
          `Blocked task delegation for ${subagentType}: prompt requests mutating work (${mutatingSignals.join(", ")}) but this subagent is read-only. Run commit/PR/edit actions directly with the primary agent.`,
        )
      }

      const violating = denied.filter((deniedTool) =>
        referencesDeniedTool(combinedText, String(deniedTool).toLowerCase().trim()),
      )
      if (violating.length === 0) {
        return
      }
      const suggestion = suggestAllowedTool(String(violating[0]), allowed)
      writeGatewayEventAudit(directory, {
        hook: "agent-denied-tool-enforcer",
        stage: "guard",
        reason_code: "tool_surface_enforced_runtime",
        session_id: sessionId(eventPayload),
        trace_id: traceId,
        subagent_type: subagentType,
        denied_tools: violating.join(","),
        suggested_tool: suggestion ?? undefined,
      })
      throw new Error(
        `Blocked task delegation for ${subagentType}: prompt requests denied tools (${violating.join(", ")}).${
          suggestion ? ` Use allowed tool '${suggestion}' instead.` : ""
        } Remove forbidden tool instructions and retry.`,
      )
    },
  }
}
