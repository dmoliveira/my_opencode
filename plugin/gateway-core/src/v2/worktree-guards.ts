import { isAbsolute } from "node:path"

import { createPrimaryWorktreeGuardHook } from "../hooks/primary-worktree-guard/index.js"
import { createWorkflowConformanceGuardHook } from "../hooks/workflow-conformance-guard/index.js"
import { createWriteExistingFileGuardHook } from "../hooks/write-existing-file-guard/index.js"
import type { ToolHooks } from "./types.js"

/** V2 adapter for the existing write and protected-worktree guards only. */
export async function registerV2WorktreeGuards(
  tool: ToolHooks,
  resolveDirectory: (sessionID: string) => Promise<string>,
  options: {
    directory: string
    writeExisting: { enabled: boolean }
    primary: { enabled: boolean; allowedBranches: string[]; blockEdits: boolean; blockBranchSwitches: boolean }
    workflow: { enabled: boolean; protectedBranches: string[]; blockEditsOnProtectedBranches: boolean }
  },
): Promise<() => Promise<void>> {
  const hooks = [
    createWriteExistingFileGuardHook({ directory: options.directory, ...options.writeExisting }),
    createPrimaryWorktreeGuardHook({ directory: options.directory, ...options.primary }),
    createWorkflowConformanceGuardHook({ directory: options.directory, ...options.workflow }),
  ]
  const registration = await tool.hook("execute.before", async (event) => {
    const legacyTool = event.tool === "shell" ? "bash" : event.tool === "patch" ? "apply_patch" : event.tool
    if (!["bash", "write", "edit", "apply_patch"].includes(legacyTool)) return
    if (!event.input || typeof event.input !== "object" || Array.isArray(event.input)) {
      throw new Error("invalid V2 tool input; refusing unguarded execution")
    }
    const args = event.input as Record<string, unknown>
    if (legacyTool === "bash" && (typeof args.command !== "string" || !args.command.trim())) {
      throw new Error("invalid V2 shell command; refusing unguarded execution")
    }
    if ((legacyTool === "write" || legacyTool === "edit") && (typeof args.path !== "string" || !args.path.trim())) {
      throw new Error("invalid V2 file target; refusing unguarded execution")
    }
    if (legacyTool === "apply_patch" && (typeof args.patchText !== "string" || !args.patchText.trim())) {
      throw new Error("invalid V2 patch; refusing unguarded execution")
    }
    const directory = await resolveDirectory(event.sessionID)
    if (!directory || !isAbsolute(directory)) {
      throw new Error("V2 session directory unavailable; refusing unguarded execution")
    }
    const output = { args }
    const input = { tool: legacyTool, sessionID: event.sessionID, callID: event.id, agent: event.agent }
    for (const hook of hooks) {
      await hook.event("tool.execute.before", { input, output, directory })
    }
    event.input = output.args
  })
  return () => registration.dispose()
}
