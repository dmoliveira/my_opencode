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

// Returns true when command triggers PR creation.
function isPrCreate(command: string): boolean {
  return /\bgh\s+pr\s+create\b/i.test(command)
}

// Returns true when command triggers PR merge.
function isPrMerge(command: string): boolean {
  return /\bgh\s+pr\s+merge\b/i.test(command)
}

// Resolves commit distance behind base ref, or null when reference is unavailable.
function commitsBehind(directory: string, baseRef: string): number | null {
  try {
    const output = execFileSync("git", ["rev-list", "--count", `HEAD..${baseRef}`], {
      cwd: directory,
      stdio: ["ignore", "pipe", "ignore"],
    })
      .toString("utf-8")
      .trim()
    const parsed = Number.parseInt(output, 10)
    if (!Number.isFinite(parsed) || parsed < 0) {
      return 0
    }
    return parsed
  } catch {
    return null
  }
}

// Creates branch freshness guard for PR create/merge actions.
export function createBranchFreshnessGuardHook(options: {
  directory: string
  enabled: boolean
  baseRef: string
  maxBehind: number
  enforceOnPrCreate: boolean
  enforceOnPrMerge: boolean
}): GatewayHook {
  const baseRef = options.baseRef.trim() || "origin/main"
  const maxBehind = Number.isFinite(options.maxBehind) && options.maxBehind >= 0 ? options.maxBehind : 0
  return {
    id: "branch-freshness-guard",
    priority: 438,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolBeforePayload
      if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash") {
        return
      }
      const command = String(eventPayload.output?.args?.command ?? "")
      const checkCreate = options.enforceOnPrCreate && isPrCreate(command)
      const checkMerge = options.enforceOnPrMerge && isPrMerge(command)
      if (!checkCreate && !checkMerge) {
        return
      }
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "")
      const behind = commitsBehind(directory, baseRef)
      if (behind === null) {
        writeGatewayEventAudit(directory, {
          hook: "branch-freshness-guard",
          stage: "skip",
          reason_code: "branch_freshness_ref_unavailable",
          session_id: sessionId,
          base_ref: baseRef,
        })
        return
      }
      if (behind <= maxBehind) {
        writeGatewayEventAudit(directory, {
          hook: "branch-freshness-guard",
          stage: "skip",
          reason_code: "branch_freshness_within_budget",
          session_id: sessionId,
          base_ref: baseRef,
          commits_behind: behind,
          max_behind: maxBehind,
        })
        return
      }
      writeGatewayEventAudit(directory, {
        hook: "branch-freshness-guard",
        stage: "skip",
        reason_code: "branch_freshness_blocked",
        session_id: sessionId,
        base_ref: baseRef,
        commits_behind: behind,
        max_behind: maxBehind,
      })
      throw new Error(
        `[branch-freshness-guard] Current branch is behind '${baseRef}' by ${behind} commit(s). Rebase or merge latest base before PR create/merge.`,
      )
    },
  }
}
