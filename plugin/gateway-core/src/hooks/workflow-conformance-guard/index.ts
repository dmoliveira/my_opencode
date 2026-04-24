import { execSync } from "node:child_process"
import { existsSync } from "node:fs"
import { basename, resolve } from "node:path"
import { fileURLToPath } from "node:url"

import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import { isAllowedProtectedShellCommand } from "../protected-shell-policy.js"
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

// Resolves current git branch for workflow branch protection.
function currentBranch(directory: string): string {
  try {
    return execSync("git branch --show-current", { cwd: directory, stdio: ["ignore", "pipe", "ignore"] })
      .toString("utf-8")
      .trim()
  } catch {
    return ""
  }
}

function gitPath(directory: string, flag: "--git-dir" | "--git-common-dir"): string {
  return resolve(
    directory,
    execSync(`git rev-parse ${flag}`, { cwd: directory, stdio: ["ignore", "pipe", "ignore"] })
      .toString("utf-8")
      .trim(),
  )
}

function isPrimaryWorktree(directory: string): boolean {
  try {
    return gitPath(directory, "--git-dir") === gitPath(directory, "--git-common-dir")
  } catch {
    return false
  }
}

const PROTECTED_GIT_MUTATION_PATTERN =
  /(?:^|&&|\|\||;)\s*(?:env\s+(?:[A-Za-z_][A-Za-z0-9_]*=(?:"[^"]*"|'[^']*'|\S+)\s+)*)?(?:(?:[^\s;&|]*\/)?rtk\s+)?(?:[^\s;&|]*\/)?git\s+(commit|merge|rebase|cherry-pick)\b/i

function isProtectedGitMutationCommand(command: string): boolean {
  return PROTECTED_GIT_MUTATION_PATTERN.test(command)
}

function protectedBranchWorktreeHint(directory: string): string {
  const base = basename(directory) || "repo"
  return `For repo maintenance, run \`python3 scripts/worktree_helper_command.py maintenance --directory ${directory}\` or create a throwaway worktree directly. Prefer a \`wt-*\` path by default, for example: \`git worktree add -b chore/<task> ../${base}-wt-maintenance HEAD\`. This is guidance, not enforcement.`
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

function maintenanceHelperError(directory: string, originalCommand: string): Error {
  const helperPath = maintenanceHelperPath(directory)
  const rewrittenCommand = maintenanceHelperCommand(directory, originalCommand)
  return new Error(
    `Protected-branch command reroute failed because the maintenance helper does not exist at '${helperPath}'. Original command: ${originalCommand}. Target repo: ${directory}. Intended reroute: ${rewrittenCommand}.`
  )
}

function rerouteGuidance(directory: string, originalCommand: string): string {
  const helperPath = maintenanceHelperPath(directory)
  const rewrittenCommand = maintenanceHelperCommand(directory, originalCommand)
  return `The command was blocked on a protected branch and would be rerouted through '${helperPath}'. Original command: ${originalCommand}. Rerouted command: ${rewrittenCommand}.`
}

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
      hook: "workflow-conformance-guard",
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
    hook: "workflow-conformance-guard",
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

// Creates workflow conformance guard for commit operations on protected branches.
export function createWorkflowConformanceGuardHook(options: {
  directory: string
  enabled: boolean
  protectedBranches: string[]
  blockEditsOnProtectedBranches: boolean
}): GatewayHook {
  const protectedSet = new Set(options.protectedBranches.map((item) => item.trim()).filter(Boolean))
  return {
    id: "workflow-conformance-guard",
    priority: 400,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolBeforePayload
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase()
      const directory = effectiveToolDirectory(eventPayload, options.directory)
      if (!isPrimaryWorktree(directory)) {
        return
      }
      const branch = currentBranch(directory)
      if (!branch || !protectedSet.has(branch)) {
        return
      }
      if (options.blockEditsOnProtectedBranches && (tool === "write" || tool === "edit" || tool === "apply_patch")) {
        const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "")
        writeGatewayEventAudit(directory, {
          hook: "workflow-conformance-guard",
          stage: "skip",
          reason_code: "edit_on_protected_branch_blocked",
          session_id: sessionId,
        })
        throw new Error(`File edits are blocked on protected branch '${branch}'. Use a worktree feature branch.`)
      }
      if (tool !== "bash") {
        return
      }
      const command = String(eventPayload.output?.args?.command ?? "").trim()
      if (isAllowedProtectedShellCommand(command)) {
        return
      }
      if (isProtectedGitMutationCommand(command)) {
        const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "")
        if (rerouteToMaintenanceHelper(eventPayload, directory, sessionId, "commit_on_protected_branch_rerouted")) {
          return
        }
        throw new Error(`Git commits are blocked on protected branch '${branch}'. Use a worktree feature branch. ${protectedBranchWorktreeHint(directory)}`)
      }
      const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "")
      if (rerouteToMaintenanceHelper(eventPayload, directory, sessionId, "bash_on_protected_branch_rerouted")) {
        return
      }
      throw new Error(
        `Bash commands on protected branch '${branch}' are limited to inspection, validation, and safe operational commands such as \`git fetch\`, \`git fetch --prune\`, \`git pull --rebase\`, \`git pull --rebase --autostash\`, \`git pull --rebase origin main\`, \`git merge --no-edit <branch>\`, \`git merge --ff-only <branch>\`, \`git worktree add|remove\`, \`git branch -d\`, \`git stash push|list|show\`, and \`oc current|next|queue|resume|done|end-session\`. Preserve local edits with targeted \`git stash push ...\` or \`git pull --rebase --autostash\` before syncing. Use a worktree feature branch for task mutations. ${protectedBranchWorktreeHint(directory)} ${rerouteGuidance(directory, command)}`
      )
    },
  }
}
