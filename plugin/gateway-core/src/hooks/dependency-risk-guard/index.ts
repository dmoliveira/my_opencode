import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"

interface ToolBeforePayload {
  input?: { tool?: string; sessionID?: string; sessionId?: string }
  output?: { args?: { filePath?: string; path?: string; file_path?: string; command?: string } }
  directory?: string
}

// Resolves file path from write/edit tool args.
function targetPath(payload: ToolBeforePayload): string {
  const args = payload.output?.args
  return String(args?.filePath ?? args?.path ?? args?.file_path ?? "").trim()
}

// Creates dependency risk guard requiring explicit handling for lockfile edits.
export function createDependencyRiskGuardHook(options: {
  directory: string
  enabled: boolean
  lockfilePatterns: string[]
  commandPatterns: string[]
}): GatewayHook {
  const patterns = options.lockfilePatterns.map((item) => item.trim()).filter(Boolean)
  const commandPatterns = options.commandPatterns
    .map((item) => {
      try {
        return new RegExp(item, "i")
      } catch {
        return null
      }
    })
    .filter((value): value is RegExp => value !== null)
  return {
    id: "dependency-risk-guard",
    priority: 415,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolBeforePayload
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase()
      if (tool === "bash") {
        const command = String(eventPayload.output?.args?.command ?? "").trim()
        if (!command) {
          return
        }
        const commandHit = commandPatterns.some((pattern) => pattern.test(command))
        if (!commandHit) {
          return
        }
      } else {
        if (tool !== "write" && tool !== "edit") {
          return
        }
        const filePath = targetPath(eventPayload)
        if (!filePath) {
          return
        }
        const hit = patterns.some((pattern) => filePath.endsWith(pattern))
        if (!hit) {
          return
        }
      }
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "")
      writeGatewayEventAudit(directory, {
        hook: "dependency-risk-guard",
        stage: "skip",
        reason_code: "lockfile_edit_guarded",
        session_id: sessionId,
      })
      throw new Error(
        "Lockfile/dependency edits require explicit security validation. Run dependency checks manually and retry with clear justification.",
      )
    },
  }
}
