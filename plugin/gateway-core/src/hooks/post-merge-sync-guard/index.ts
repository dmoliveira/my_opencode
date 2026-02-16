import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"

interface ToolBeforeInput {
  tool?: string
  sessionID?: string
  sessionId?: string
}

interface ToolBeforeOutput {
  args?: {
    command?: string
  }
}

interface ToolAfterOutput {
  output?: unknown
}

interface HookPayload {
  input?: ToolBeforeInput
  output?: ToolBeforeOutput | ToolAfterOutput
  directory?: string
}

// Returns true when command is gh pr merge.
function isPrMerge(command: string): boolean {
  return /\bgh\s+pr\s+merge\b/i.test(command)
}

// Returns true when command includes inline main sync action.
function hasInlineMainSync(command: string): boolean {
  return /\bgit\s+pull\s+--rebase\b/i.test(command)
}

// Creates post-merge sync guard with cleanup enforcement and reminder injection.
export function createPostMergeSyncGuardHook(options: {
  directory: string
  enabled: boolean
  requireDeleteBranch: boolean
  enforceMainSyncInline: boolean
  reminderCommands: string[]
}): GatewayHook {
  const pendingReminderSessions = new Set<string>()
  const reminderCommands = options.reminderCommands.map((item) => item.trim()).filter(Boolean)
  return {
    id: "post-merge-sync-guard",
    priority: 447,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return
      }
      const eventPayload = (payload ?? {}) as HookPayload
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "")
      if (type === "tool.execute.before") {
        if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash") {
          return
        }
        const command = String((eventPayload.output as ToolBeforeOutput | undefined)?.args?.command ?? "").trim()
        if (!isPrMerge(command)) {
          return
        }
        const lower = command.toLowerCase()
        if (options.requireDeleteBranch && !/\s--delete-branch\b/.test(lower)) {
          writeGatewayEventAudit(directory, {
            hook: "post-merge-sync-guard",
            stage: "skip",
            reason_code: "post_merge_delete_branch_missing",
            session_id: sessionId,
          })
          throw new Error("[post-merge-sync-guard] Include `--delete-branch` when merging PRs.")
        }
        if (options.enforceMainSyncInline && !hasInlineMainSync(lower)) {
          writeGatewayEventAudit(directory, {
            hook: "post-merge-sync-guard",
            stage: "skip",
            reason_code: "post_merge_main_sync_missing",
            session_id: sessionId,
          })
          throw new Error(
            "[post-merge-sync-guard] Include inline main sync (`git pull --rebase`) or disable enforceMainSyncInline.",
          )
        }
        if (!hasInlineMainSync(lower) && sessionId) {
          pendingReminderSessions.add(sessionId)
        }
        return
      }
      if (type !== "tool.execute.after") {
        return
      }
      if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash") {
        return
      }
      if (!sessionId || !pendingReminderSessions.has(sessionId)) {
        return
      }
      pendingReminderSessions.delete(sessionId)
      const toolOutput = eventPayload.output as ToolAfterOutput | undefined
      if (typeof toolOutput?.output !== "string") {
        return
      }
      if (reminderCommands.length === 0) {
        return
      }
      const reminder = `\n\n[post-merge-sync-guard] Merge complete. Run cleanup sync:\n${reminderCommands.map((cmd) => `- ${cmd}`).join("\n")}`
      toolOutput.output = `${toolOutput.output}${reminder}`
      writeGatewayEventAudit(directory, {
        hook: "post-merge-sync-guard",
        stage: "state",
        reason_code: "post_merge_sync_reminder_appended",
        session_id: sessionId,
      })
    },
  }
}
