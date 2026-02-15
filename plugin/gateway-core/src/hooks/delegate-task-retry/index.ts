import type { GatewayHook } from "../registry.js"

interface DelegateTaskErrorPattern {
  pattern: string
  errorType: string
  fixHint: string
}

const DELEGATE_TASK_ERROR_PATTERNS: DelegateTaskErrorPattern[] = [
  {
    pattern: "run_in_background",
    errorType: "missing_run_in_background",
    fixHint: "Add run_in_background=false (delegation) or run_in_background=true (parallel exploration).",
  },
  {
    pattern: "load_skills",
    errorType: "missing_load_skills",
    fixHint: "Add load_skills=[] (empty array if no skills are needed).",
  },
  {
    pattern: "category OR subagent_type",
    errorType: "mutual_exclusion",
    fixHint: "Provide only one of: category or subagent_type.",
  },
  {
    pattern: "Must provide either category or subagent_type",
    errorType: "missing_category_or_agent",
    fixHint: "Add either category='general' or subagent_type='explore'.",
  },
  {
    pattern: "Unknown category",
    errorType: "unknown_category",
    fixHint: "Use a valid category from the available list in the error output.",
  },
  {
    pattern: "Unknown agent",
    errorType: "unknown_agent",
    fixHint: "Use a valid agent from the available agents list in the error output.",
  },
]

interface ToolAfterPayload {
  input?: {
    tool?: string
  }
  output?: {
    output?: unknown
  }
}

// Detects known delegate task argument errors from task output.
function detectDelegateTaskError(output: string): DelegateTaskErrorPattern | null {
  if (!output.includes("[ERROR]") && !output.includes("Invalid arguments")) {
    return null
  }
  for (const pattern of DELEGATE_TASK_ERROR_PATTERNS) {
    if (output.includes(pattern.pattern)) {
      return pattern
    }
  }
  return null
}

// Creates delegate task retry hook that appends corrective guidance.
export function createDelegateTaskRetryHook(options: { enabled: boolean }): GatewayHook {
  return {
    id: "delegate-task-retry",
    priority: 290,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.after") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolAfterPayload
      const tool = String(eventPayload.input?.tool ?? "").trim().toLowerCase()
      if (tool !== "task") {
        return
      }
      if (typeof eventPayload.output?.output !== "string") {
        return
      }
      const error = detectDelegateTaskError(eventPayload.output.output)
      if (!error) {
        return
      }
      eventPayload.output.output += `\n[task CALL FAILED - IMMEDIATE RETRY REQUIRED]\nError Type: ${error.errorType}\nFix: ${error.fixHint}\nAction: Retry task now with corrected parameters.`
    },
  }
}
