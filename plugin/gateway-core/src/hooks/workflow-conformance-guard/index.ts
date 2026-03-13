import { execSync } from "node:child_process"
import { basename, resolve } from "node:path"

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
  /(?:^|&&|\|\||;)\s*(?:env\s+(?:[A-Za-z_][A-Za-z0-9_]*=(?:"[^"]*"|'[^']*'|\S+)\s+)*)?(?:[^\s;&|]*\/)?git\s+(commit|merge|rebase|cherry-pick)\b/i

function isProtectedGitMutationCommand(command: string): boolean {
  return PROTECTED_GIT_MUTATION_PATTERN.test(command)
}

function protectedBranchWorktreeHint(directory: string): string {
  const base = basename(directory) || "repo"
  return `For repo maintenance, run \`python3 scripts/worktree_helper_command.py maintenance --directory ${directory}\` or create a throwaway worktree directly, for example: \`git worktree add -b chore/<task> ../${base}-maint HEAD\`.`
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
      if (isProtectedGitMutationCommand(command)) {
        const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "")
        writeGatewayEventAudit(directory, {
          hook: "workflow-conformance-guard",
          stage: "skip",
          reason_code: "commit_on_protected_branch_blocked",
          session_id: sessionId,
        })
        throw new Error(`Git commits are blocked on protected branch '${branch}'. Use a worktree feature branch.`)
      }
      if (isAllowedProtectedShellCommand(command)) {
        return
      }
      const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "")
      writeGatewayEventAudit(directory, {
        hook: "workflow-conformance-guard",
        stage: "skip",
        reason_code: "bash_on_protected_branch_blocked",
        session_id: sessionId,
      })
      throw new Error(
        `Bash commands on protected branch '${branch}' are limited to inspection, validation, and exact sync commands (\`git fetch\`, \`git fetch --prune\`, and \`git pull --rebase\`). Use a worktree feature branch for task mutations. ${protectedBranchWorktreeHint(directory)}`
      )
    },
  }
}
