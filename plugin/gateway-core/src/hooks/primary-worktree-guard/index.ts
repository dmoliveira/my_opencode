import { execFileSync } from "node:child_process"
import { existsSync } from "node:fs"
import { resolve } from "node:path"
import { fileURLToPath } from "node:url"

import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import { hasDisallowedShellSyntax, isAllowedProtectedShellCommand } from "../protected-shell-policy.js"
import type { GatewayHook } from "../registry.js"
import { effectiveToolDirectory } from "../shared/effective-tool-directory.js"

interface ToolBeforePayload {
  input?: { tool?: string; sessionID?: string; sessionId?: string }
  output?: {
    args?: {
      command?: string
      workdir?: string
      cwd?: string
      filePath?: string
      path?: string
      file_path?: string
    }
  }
  directory?: string
}

function gitPath(directory: string, flag: "--git-dir" | "--git-common-dir"): string {
  const output = execFileSync("git", ["rev-parse", flag], {
    cwd: directory,
    encoding: "utf-8",
    stdio: ["ignore", "pipe", "ignore"],
  }).trim()
  return resolve(directory, output)
}

function isPrimaryWorktree(directory: string): boolean {
  try {
    return gitPath(directory, "--git-dir") === gitPath(directory, "--git-common-dir")
  } catch {
    return false
  }
}

function stripQuotes(token: string): string {
  return token.replace(/^['"]|['"]$/g, "")
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'"'"'`)}'`
}

const DEFAULT_MAINTENANCE_HELPER = fileURLToPath(new URL("../../../../../scripts/worktree_helper_command.py", import.meta.url))

function maintenanceHelperPath(directory: string): string {
  const override = process.env.OPENCODE_MAINTENANCE_HELPER_PATH?.trim()
  if (override) {
    return override
  }
  const repoHelper = resolve(directory, "scripts", "worktree_helper_command.py")
  if (existsSync(repoHelper)) {
    return repoHelper
  }
  return DEFAULT_MAINTENANCE_HELPER
}

function maintenanceHelperCommand(directory: string, originalCommand: string): string {
  return `python3 ${shellQuote(maintenanceHelperPath(directory))} maintenance --directory ${shellQuote(directory)} --command ${shellQuote(originalCommand)} --json`
}

function isMaintenanceHelperInvocation(command: string): boolean {
  return /(?:^|&&|\|\||;)\s*(?:env\s+)?(?:[A-Za-z_][A-Za-z0-9_]*=(?:"[^"]*"|'[^']*'|\S+)\s+)*python3\s+['"]?[^'";&|]*worktree_helper_command\.py['"]?\s+maintenance\b/i.test(command)
}

function maintenanceHelperError(directory: string, originalCommand: string): Error {
  const helperPath = maintenanceHelperPath(directory)
  const rewrittenCommand = maintenanceHelperCommand(directory, originalCommand)
  return new Error(
    `Protected primary-worktree command reroute failed because the maintenance helper does not exist at '${helperPath}'. Original command: ${originalCommand}. Target repo: ${directory}. Intended reroute: ${rewrittenCommand}.`
  )
}

function rerouteGuidance(directory: string, originalCommand: string): string {
  const helperPath = maintenanceHelperPath(directory)
  const rewrittenCommand = maintenanceHelperCommand(directory, originalCommand)
  return `The command was blocked in the primary worktree and would be rerouted through '${helperPath}'. Original command: ${originalCommand}. Rerouted command: ${rewrittenCommand}.`
}

const GIT_PREFIX = String.raw`(?:^|&&|\|\||;)\s*(?:env\s+(?:[A-Za-z_][A-Za-z0-9_]*=(?:"[^"]*"|'[^']*'|\S+)\s+)*)?(?:(?:[^\s;&|]*/)?rtk\s+)?(?:[^\s;&|]*/)?git\s+`

function matchBranchTarget(command: string, pattern: RegExp): string | null {
  const match = command.match(pattern)
  return match?.[1] ? stripQuotes(match[1]) : null
}

function hasPattern(command: string, pattern: RegExp): boolean {
  return pattern.test(command)
}

interface BranchSwitchInfo {
  target: string
  plain: boolean
}

function branchSwitchInfo(command: string): BranchSwitchInfo | null {
  if (new RegExp(`${GIT_PREFIX}checkout\\s+(?:"[^"]+"|'[^']+'|[^\\s;&|]+)\\s+--\\s+`, "i").test(command)) {
    return null
  }
  const destructiveTarget =
    matchBranchTarget(
      command,
      new RegExp(`${GIT_PREFIX}switch\\s+(?:-c|-C|--orphan)\\s+("[^"]+"|'[^']+'|[^\\s;&|]+)`, "i")
    ) ??
    matchBranchTarget(
      command,
      new RegExp(`${GIT_PREFIX}checkout\\s+(?:-b|-B|--orphan)\\s+("[^"]+"|'[^']+'|[^\\s;&|]+)`, "i")
    )
  if (destructiveTarget) {
    return { target: destructiveTarget, plain: false }
  }
  if (hasPattern(command, new RegExp(`${GIT_PREFIX}switch\\s+--detach\\b`, "i"))) {
    return { target: "--detach", plain: false }
  }
  if (hasPattern(command, new RegExp(`${GIT_PREFIX}checkout\\s+--detach\\b`, "i"))) {
    return { target: "--detach", plain: false }
  }
  const plainTarget =
    matchBranchTarget(command, new RegExp(`${GIT_PREFIX}switch\\s+(?!-)("[^"]+"|'[^']+'|[^\\s;&|]+)`, "i")) ??
    matchBranchTarget(command, new RegExp(`${GIT_PREFIX}checkout\\s+(?!-)("[^"]+"|'[^']+'|[^\\s;&|]+)`, "i"))
  return plainTarget ? { target: plainTarget, plain: true } : null
}

export function createPrimaryWorktreeGuardHook(options: {
  directory: string
  enabled: boolean
  allowedBranches: string[]
  blockEdits: boolean
  blockBranchSwitches: boolean
}): GatewayHook {
  const allowedBranches = new Set(options.allowedBranches.map((item) => item.trim()).filter(Boolean))
  function rerouteToMaintenanceHelper(payload: ToolBeforePayload, directory: string, sessionId: string, reasonCode: string): boolean {
    const args = payload.output?.args
    const originalCommand = typeof args?.command === "string" ? args.command.trim() : ""
    if (!args || !originalCommand) {
      return false
    }
    const helperPath = maintenanceHelperPath(directory)
    const rewrittenCommand = maintenanceHelperCommand(directory, originalCommand)
    if (!existsSync(helperPath)) {
      writeGatewayEventAudit(directory, {
        hook: "primary-worktree-guard",
        stage: "skip",
        reason_code: "maintenance_helper_missing",
        session_id: sessionId,
        blocked_command: originalCommand,
        original_command: originalCommand,
        helper_path: helperPath,
        helper_exists: false,
        repo_root: directory,
      })
      throw maintenanceHelperError(directory, originalCommand)
    }
    args.command = rewrittenCommand
    writeGatewayEventAudit(directory, {
      hook: "primary-worktree-guard",
      stage: "state",
      reason_code: reasonCode,
      session_id: sessionId,
      blocked_command: originalCommand,
      original_command: originalCommand,
      rewritten_command: rewrittenCommand,
      helper_path: helperPath,
      helper_exists: true,
      repo_root: directory,
    })
    return true
  }
  return {
    id: "primary-worktree-guard",
    priority: 689,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolBeforePayload
      const directory = effectiveToolDirectory(eventPayload, options.directory)
      if (!isPrimaryWorktree(directory)) {
        return
      }
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase()
      const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "")
      if (options.blockEdits && (tool === "write" || tool === "edit" || tool === "apply_patch")) {
        writeGatewayEventAudit(directory, {
          hook: "primary-worktree-guard",
          stage: "skip",
          reason_code: "edit_in_primary_worktree_blocked",
          session_id: sessionId,
        })
        throw new Error(
          "File edits are blocked in the primary project folder. Create or use a dedicated git worktree branch."
        )
      }
      if (!options.blockBranchSwitches || tool !== "bash") {
        return
      }
      const command = String(eventPayload.output?.args?.command ?? "").trim()
      if (isMaintenanceHelperInvocation(command)) {
        return
      }
      const switchInfo = branchSwitchInfo(command)
      if (switchInfo) {
        if (!hasDisallowedShellSyntax(command) && switchInfo.plain && allowedBranches.has(switchInfo.target)) {
          return
        }
        writeGatewayEventAudit(directory, {
          hook: "primary-worktree-guard",
          stage: "skip",
          reason_code: "branch_switch_in_primary_worktree_blocked",
          session_id: sessionId,
          target_branch: switchInfo.target,
        })
        throw new Error(
          `Branch switching to '${switchInfo.target}' is blocked in the primary project folder. Create or use a dedicated git worktree branch instead.`
        )
      }
      if (isAllowedProtectedShellCommand(command)) {
        return
      }
      if (rerouteToMaintenanceHelper(eventPayload, directory, sessionId, "bash_in_primary_worktree_rerouted")) {
        return
      }
      throw new Error(
        `Bash commands in the primary project folder are limited to inspection, validation, and safe operational commands such as \`git fetch\`, \`git fetch --prune\`, \`git pull --rebase\`, \`git pull --rebase --autostash\`, \`git pull --rebase origin main\`, \`git merge --no-edit <branch>\`, \`git merge --ff-only <branch>\`, \`git worktree add|remove\`, \`git branch -d\`, \`git stash push|list|show\`, and \`oc current|next|queue|resume|done|end-session\`. Preserve local edits with targeted \`git stash push ...\` or \`git pull --rebase --autostash\` before syncing. Create or use a dedicated git worktree branch for task mutations. ${rerouteGuidance(directory, command)}`
      )
    },
  }
}
