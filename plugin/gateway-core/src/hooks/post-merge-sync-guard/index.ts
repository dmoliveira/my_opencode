import { execFileSync } from "node:child_process"

import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"
import { isGitHubPrMergeCommand } from "../shared/github-pr-commands.js"
import {
  listToolAfterOutputTexts,
  writeToolAfterOutputChannelText,
} from "../shared/tool-after-output.js"

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

const BENIGN_GH_WORKTREE_MERGE_WARNING =
  /failed to run git:\s*fatal:\s*'main' is already used by worktree at '([^']+)'\s*/i

// Returns true when command includes inline main sync action.
function hasInlineMainSync(command: string): boolean {
  return /\bgit\s+pull\s+--rebase\b/i.test(command)
}

function currentBranch(directory: string): string {
  try {
    return execFileSync("git", ["rev-parse", "--abbrev-ref", "HEAD"], {
      cwd: directory,
      encoding: "utf-8",
    }).trim()
  } catch {
    return ""
  }
}

function mainWorktreePath(directory: string): string {
  try {
    const output = execFileSync("git", ["worktree", "list", "--porcelain"], {
      cwd: directory,
      encoding: "utf-8",
    })
    const blocks = output
      .split(/\n\n+/)
      .map((block: string) => block.trim())
      .filter(Boolean)
    for (const block of blocks) {
      const lines = block.split(/\r?\n/)
      const worktreeLine = lines.find((line: string) => line.startsWith("worktree "))
      const branchLine = lines.find((line: string) => line.startsWith("branch "))
      if (!worktreeLine || !branchLine) {
        continue
      }
      const branchRef = branchLine.replace(/^branch\s+/, "").trim()
      if (branchRef === "refs/heads/main") {
        return worktreeLine.replace(/^worktree\s+/, "").trim()
      }
    }
  } catch {
    return ""
  }
  return ""
}

function resolveReminder(directory: string, defaults: string[]): { intro: string; commands: string[] } {
  const branch = currentBranch(directory)
  const mainPath = mainWorktreePath(directory)
  if (!mainPath) {
    if (branch !== "main") {
      return {
        intro: "Merge complete. No checked-out main worktree was found; inspect worktrees before syncing:",
        commands: ["git worktree list", "git status --short --branch"],
      }
    }
    return {
      intro: "Merge complete. Run cleanup sync:",
      commands: defaults,
    }
  }
  const mainBranch = currentBranch(mainPath)
  if (branch === "main" && mainPath === directory) {
    return {
      intro: "Merge complete. Run cleanup sync:",
      commands: ["git pull --rebase"],
    }
  }
  if (mainBranch === "main") {
    return {
      intro: "Merge complete. Run cleanup sync:",
      commands: [`git -C "${mainPath}" pull --rebase`],
    }
  }
  return {
    intro: "Merge complete. Main worktree is not on 'main'; inspect it before syncing:",
    commands: ["git worktree list", `git -C "${mainPath}" status --short --branch`],
  }
}


function normalizeMergeOutput(output: string): string {
  const match = output.match(BENIGN_GH_WORKTREE_MERGE_WARNING)
  if (!match) {
    return output
  }
  const note = `[post-merge-sync-guard] PR merged on GitHub. Skipping redundant local branch checkout because 'main' is already active in the primary worktree (${match[1]}).`
  const cleaned = output.replace(BENIGN_GH_WORKTREE_MERGE_WARNING, "").trim()
  if (!cleaned) {
    return note
  }
  return `${cleaned}\n\n${note}`
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
        if (!isGitHubPrMergeCommand(command)) {
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
      const entries = listToolAfterOutputTexts(toolOutput?.output)
      if (entries.length === 0) {
        return
      }
      let rewrote = false
      if (reminderCommands.length === 0) {
        for (const entry of entries) {
          rewrote =
            writeToolAfterOutputChannelText(toolOutput?.output, entry.channel, normalizeMergeOutput(entry.text)) ||
            rewrote
        }
        if (!rewrote && toolOutput) {
          toolOutput.output = normalizeMergeOutput(entries[0].text)
        }
        return
      }
      const reminderState = resolveReminder(directory, reminderCommands)
      const reminder = `\n\n[post-merge-sync-guard] ${reminderState.intro}\n${reminderState.commands.map((cmd) => `- ${cmd}`).join("\n")}`
      for (const [index, entry] of entries.entries()) {
        const nextText = `${normalizeMergeOutput(entry.text)}${index === 0 ? reminder : ""}`
        rewrote = writeToolAfterOutputChannelText(toolOutput?.output, entry.channel, nextText) || rewrote
      }
      if (!rewrote && toolOutput) {
        toolOutput.output = `${normalizeMergeOutput(entries[0].text)}${reminder}`
      }
      writeGatewayEventAudit(directory, {
        hook: "post-merge-sync-guard",
        stage: "state",
        reason_code: "post_merge_sync_reminder_appended",
        session_id: sessionId,
      })
    },
  }
}
