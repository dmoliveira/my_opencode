import { execSync } from "node:child_process"

import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import { missingValidationMarkers } from "../validation-evidence-ledger/evidence.js"

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

// Returns true when git worktree has no pending tracked or untracked changes.
function isWorktreeClean(directory: string): boolean {
  try {
    const output = execSync("git status --porcelain", {
      cwd: directory,
      stdio: ["ignore", "pipe", "ignore"],
    })
      .toString("utf-8")
      .trim()
    return output.length === 0
  } catch {
    return true
  }
}

// Creates PR readiness guard that blocks creation when validation gates are missing.
export function createPrReadinessGuardHook(options: {
  directory: string
  enabled: boolean
  requireCleanWorktree: boolean
  requireValidationEvidence: boolean
  requiredMarkers: string[]
}): GatewayHook {
  const required = options.requiredMarkers.map((item) => item.trim().toLowerCase()).filter(Boolean)
  return {
    id: "pr-readiness-guard",
    priority: 440,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolBeforePayload
      if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash") {
        return
      }
      const command = String(eventPayload.output?.args?.command ?? "")
      if (!isPrCreate(command)) {
        return
      }
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "").trim()
      if (options.requireCleanWorktree && !isWorktreeClean(directory)) {
        writeGatewayEventAudit(directory, {
          hook: "pr-readiness-guard",
          stage: "skip",
          reason_code: "pr_create_dirty_worktree",
          session_id: sessionId,
        })
        throw new Error("[pr-readiness-guard] Worktree is dirty. Commit/stash changes before creating PR.")
      }
      if (!options.requireValidationEvidence || !sessionId || required.length === 0) {
        return
      }
      const missing = missingValidationMarkers(sessionId, required)
      if (missing.length === 0) {
        return
      }
      writeGatewayEventAudit(directory, {
        hook: "pr-readiness-guard",
        stage: "skip",
        reason_code: "pr_create_missing_validation",
        session_id: sessionId,
      })
      throw new Error(
        `[pr-readiness-guard] Missing validation evidence before PR create: ${missing.join(", ")}.`,
      )
    },
  }
}
