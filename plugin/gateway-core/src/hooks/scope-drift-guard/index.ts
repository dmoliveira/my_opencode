import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"

interface ToolBeforePayload {
  input?: { tool?: string; sessionID?: string; sessionId?: string }
  output?: { args?: { filePath?: string; path?: string; file_path?: string } }
  directory?: string
}

// Resolves target path from write/edit tool args.
function targetPath(payload: ToolBeforePayload): string {
  const args = payload.output?.args
  return String(args?.filePath ?? args?.path ?? args?.file_path ?? "").trim()
}

// Creates scope drift guard for file edits outside configured scope prefixes.
export function createScopeDriftGuardHook(options: {
  directory: string
  enabled: boolean
  allowedPaths: string[]
  blockOnDrift: boolean
}): GatewayHook {
  const normalized = options.allowedPaths.map((item) => item.trim()).filter(Boolean)
  return {
    id: "scope-drift-guard",
    priority: 405,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolBeforePayload
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase()
      if (tool !== "write" && tool !== "edit") {
        return
      }
      if (normalized.length === 0) {
        return
      }
      const path = targetPath(eventPayload)
      if (!path) {
        return
      }
      const inScope = normalized.some((prefix) => path.startsWith(prefix))
      if (inScope) {
        return
      }
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "")
      writeGatewayEventAudit(directory, {
        hook: "scope-drift-guard",
        stage: "skip",
        reason_code: "file_scope_drift_detected",
        session_id: sessionId,
      })
      if (options.blockOnDrift) {
        throw new Error("File edit outside allowed scope paths. Update scopeDriftGuard.allowedPaths or adjust file target.")
      }
    },
  }
}
