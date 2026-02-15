import { existsSync } from "node:fs"
import { isAbsolute, join, normalize, resolve, sep } from "node:path"

import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"

interface ToolBeforePayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
  }
  output?: {
    args?: { filePath?: string; path?: string; file_path?: string }
  }
  directory?: string
}

// Resolves write target file path from tool arguments.
function targetPath(payload: ToolBeforePayload): string {
  const args = payload.output?.args
  const value = args?.filePath ?? args?.path ?? args?.file_path
  return typeof value === "string" ? value.trim() : ""
}

// Creates write-existing-file guard hook for safer file mutations.
export function createWriteExistingFileGuardHook(options: {
  directory: string
  enabled: boolean
}): GatewayHook {
  return {
    id: "write-existing-file-guard",
    priority: 310,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolBeforePayload
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? ""
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase()
      if (tool !== "write") {
        return
      }
      const filePath = targetPath(eventPayload)
      if (!filePath) {
        return
      }
      const resolved = normalize(isAbsolute(filePath) ? filePath : resolve(directory, filePath))
      if (!existsSync(resolved)) {
        return
      }
      const sisyphusRoot = join(directory, ".sisyphus") + sep
      if (resolved.startsWith(sisyphusRoot) && resolved.endsWith(".md")) {
        return
      }
      writeGatewayEventAudit(directory, {
        hook: "write-existing-file-guard",
        stage: "skip",
        reason_code: "blocked_existing_write",
        session_id: typeof sessionId === "string" ? sessionId : "",
        file_path: filePath,
      })
      throw new Error("File already exists. Use edit tool instead.")
    },
  }
}
