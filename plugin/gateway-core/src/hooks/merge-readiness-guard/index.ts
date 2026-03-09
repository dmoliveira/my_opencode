import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import { gitHubPrMergeHasStrategy, isGitHubPrMergeCommand } from "../shared/github-pr-commands.js"

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

// Creates merge readiness guard for explicit safe merge command usage.
export function createMergeReadinessGuardHook(options: {
  directory: string
  enabled: boolean
  requireDeleteBranch: boolean
  requireStrategy: boolean
  disallowAdminBypass: boolean
}): GatewayHook {
  return {
    id: "merge-readiness-guard",
    priority: 445,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolBeforePayload
      if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash") {
        return
      }
      const command = String(eventPayload.output?.args?.command ?? "").trim()
      if (!isGitHubPrMergeCommand(command)) {
        return
      }
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "")
      const lower = command.toLowerCase()
      if (options.disallowAdminBypass && /\s--admin\b/.test(lower)) {
        writeGatewayEventAudit(directory, {
          hook: "merge-readiness-guard",
          stage: "skip",
          reason_code: "merge_admin_bypass_blocked",
          session_id: sessionId,
        })
        throw new Error("[merge-readiness-guard] `gh pr merge --admin` is blocked by policy.")
      }
      if (options.requireStrategy && !gitHubPrMergeHasStrategy(command)) {
        writeGatewayEventAudit(directory, {
          hook: "merge-readiness-guard",
          stage: "skip",
          reason_code: "merge_strategy_missing",
          session_id: sessionId,
        })
        throw new Error("[merge-readiness-guard] Merge strategy flag is required (--merge/--squash/--rebase).")
      }
      if (options.requireDeleteBranch && !/\s--delete-branch\b/.test(lower)) {
        writeGatewayEventAudit(directory, {
          hook: "merge-readiness-guard",
          stage: "skip",
          reason_code: "merge_delete_branch_missing",
          session_id: sessionId,
        })
        throw new Error("[merge-readiness-guard] Include `--delete-branch` when merging PRs.")
      }
    },
  }
}
