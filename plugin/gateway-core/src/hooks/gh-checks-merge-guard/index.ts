import { execFileSync } from "node:child_process"

import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"

interface ToolBeforePayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
  }
  output?: {
    args?: { command?: string }
  }
  directory?: string
}

interface PrStatusRollupEntry {
  conclusion?: unknown
  status?: unknown
  state?: unknown
}

interface PrViewPayload {
  isDraft?: unknown
  reviewDecision?: unknown
  mergeStateStatus?: unknown
  statusCheckRollup?: unknown
}

interface CheckSummary {
  total: number
  failed: number
  pending: number
}

interface InspectPrInput {
  directory: string
  selector: string
}

const SUCCESS_CONCLUSIONS = new Set(["SUCCESS", "NEUTRAL", "SKIPPED"])
const PENDING_CONCLUSIONS = new Set(["PENDING", "IN_PROGRESS", "QUEUED", "WAITING", "EXPECTED", "REQUESTED"])
const PENDING_STATUSES = new Set(["PENDING", "IN_PROGRESS", "QUEUED", "WAITING", "EXPECTED", "REQUESTED"])

// Returns true when command is gh pr merge.
function isPrMerge(command: string): boolean {
  return /\bgh\s+pr\s+merge\b/i.test(command)
}

// Normalizes token into uppercase trimmed string.
function normalize(value: unknown): string {
  return String(value ?? "")
    .trim()
    .toUpperCase()
}

// Splits command into shell-like tokens with simple quote support.
function tokenize(command: string): string[] {
  const matches = command.match(/"[^"]*"|'[^']*'|\S+/g)
  if (!matches) {
    return []
  }
  return matches.map((token) => {
    if (token.length >= 2 && ((token.startsWith('"') && token.endsWith('"')) || (token.startsWith("'") && token.endsWith("'")))) {
      return token.slice(1, -1)
    }
    return token
  })
}

// Extracts PR selector argument from gh pr merge command.
function mergeSelector(command: string): string {
  const tokens = tokenize(command)
  for (let idx = 0; idx < tokens.length - 2; idx += 1) {
    if (tokens[idx] !== "gh" || tokens[idx + 1] !== "pr" || tokens[idx + 2] !== "merge") {
      continue
    }
    for (let argIndex = idx + 3; argIndex < tokens.length; argIndex += 1) {
      const token = tokens[argIndex]
      if (!token || token === ";" || token === "&&" || token === "||" || token === "|") {
        break
      }
      if (token.startsWith("-")) {
        continue
      }
      return token
    }
    return ""
  }
  return ""
}

// Loads PR metadata from gh cli for merge checks.
function loadPrView(input: InspectPrInput): PrViewPayload {
  const args = ["pr", "view"]
  if (input.selector.trim()) {
    args.push(input.selector.trim())
  }
  args.push("--json", "isDraft,reviewDecision,mergeStateStatus,statusCheckRollup")
  const output = execFileSync("gh", args, {
    cwd: input.directory,
    stdio: ["ignore", "pipe", "pipe"],
  })
    .toString("utf-8")
    .trim()
  return JSON.parse(output) as PrViewPayload
}

// Classifies status check rollup into failed and pending buckets.
function summarizeChecks(rollup: unknown): CheckSummary {
  if (!Array.isArray(rollup)) {
    return { total: 0, failed: 0, pending: 0 }
  }
  let failed = 0
  let pending = 0
  for (const entry of rollup as PrStatusRollupEntry[]) {
    const conclusion = normalize(entry.conclusion ?? entry.state)
    const status = normalize(entry.status)
    if (conclusion) {
      if (SUCCESS_CONCLUSIONS.has(conclusion)) {
        continue
      }
      if (PENDING_CONCLUSIONS.has(conclusion)) {
        pending += 1
        continue
      }
      failed += 1
      continue
    }
    if (status) {
      if (status === "COMPLETED" || status === "SUCCESS" || status === "SUCCESSFUL") {
        continue
      }
      if (PENDING_STATUSES.has(status)) {
        pending += 1
        continue
      }
      failed += 1
      continue
    }
    pending += 1
  }
  return {
    total: rollup.length,
    failed,
    pending,
  }
}

// Creates merge checks guard that requires draft/review/check readiness before merge.
export function createGhChecksMergeGuardHook(options: {
  directory: string
  enabled: boolean
  blockDraft: boolean
  requireApprovedReview: boolean
  requirePassingChecks: boolean
  blockedMergeStates: string[]
  failOpenOnError: boolean
  inspectPr?: (input: InspectPrInput) => PrViewPayload
}): GatewayHook {
  const blockedStates = new Set(options.blockedMergeStates.map((item) => normalize(item)).filter(Boolean))
  const inspectPr = options.inspectPr ?? loadPrView
  return {
    id: "gh-checks-merge-guard",
    priority: 446,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolBeforePayload
      if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash") {
        return
      }
      const command = String(eventPayload.output?.args?.command ?? "").trim()
      if (!isPrMerge(command)) {
        return
      }
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "")
      const selector = mergeSelector(command)
      let prView: PrViewPayload
      try {
        prView = inspectPr({
          directory,
          selector,
        })
      } catch (error) {
        writeGatewayEventAudit(directory, {
          hook: "gh-checks-merge-guard",
          stage: "skip",
          reason_code: "merge_checks_lookup_failed",
          session_id: sessionId,
          selector,
        })
        if (options.failOpenOnError) {
          return
        }
        throw new Error(
          `[gh-checks-merge-guard] Unable to verify PR checks before merge: ${error instanceof Error ? error.message : String(error)}.`,
        )
      }

      const isDraft = Boolean(prView.isDraft)
      const reviewDecision = normalize(prView.reviewDecision)
      const mergeState = normalize(prView.mergeStateStatus)
      const checks = summarizeChecks(prView.statusCheckRollup)

      if (options.blockDraft && isDraft) {
        writeGatewayEventAudit(directory, {
          hook: "gh-checks-merge-guard",
          stage: "skip",
          reason_code: "merge_draft_blocked",
          session_id: sessionId,
          selector,
        })
        throw new Error("[gh-checks-merge-guard] PR is draft. Mark ready for review before merging.")
      }
      if (blockedStates.has(mergeState)) {
        writeGatewayEventAudit(directory, {
          hook: "gh-checks-merge-guard",
          stage: "skip",
          reason_code: "merge_state_blocked",
          session_id: sessionId,
          selector,
          merge_state: mergeState,
        })
        throw new Error(`[gh-checks-merge-guard] PR merge state '${mergeState}' is blocked by policy.`)
      }
      if (options.requireApprovedReview && reviewDecision !== "APPROVED") {
        writeGatewayEventAudit(directory, {
          hook: "gh-checks-merge-guard",
          stage: "skip",
          reason_code: "merge_review_not_approved",
          session_id: sessionId,
          selector,
          review_decision: reviewDecision,
        })
        throw new Error(
          `[gh-checks-merge-guard] Review decision is '${reviewDecision || "UNKNOWN"}'. Approval is required before merge.`,
        )
      }
      if (options.requirePassingChecks && (checks.failed > 0 || checks.pending > 0)) {
        writeGatewayEventAudit(directory, {
          hook: "gh-checks-merge-guard",
          stage: "skip",
          reason_code: "merge_checks_not_green",
          session_id: sessionId,
          selector,
          checks_failed: checks.failed,
          checks_pending: checks.pending,
          checks_total: checks.total,
        })
        throw new Error(
          `[gh-checks-merge-guard] PR checks are not green (failed=${checks.failed}, pending=${checks.pending}).`,
        )
      }
      writeGatewayEventAudit(directory, {
        hook: "gh-checks-merge-guard",
        stage: "state",
        reason_code: "merge_checks_verified",
        session_id: sessionId,
        selector,
        checks_total: checks.total,
      })
    },
  }
}
