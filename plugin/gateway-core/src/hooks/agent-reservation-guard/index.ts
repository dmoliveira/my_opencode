import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import type { GatewayHook } from "../registry.js"

interface ToolBeforePayload {
  input?: {
    tool?: string
    sessionID?: string
    sessionId?: string
  }
  directory?: string
}

// Returns true when environment contains active reservation marker.
function hasReservation(envKeys: string[]): boolean {
  for (const key of envKeys) {
    const value = String(process.env[key] ?? "").trim().toLowerCase()
    if (value === "1" || value === "true" || value === "yes" || value === "on") {
      return true
    }
  }
  return false
}

// Creates reservation guard for multi-agent file edit coordination.
export function createAgentReservationGuardHook(options: {
  directory: string
  enabled: boolean
  enforce: boolean
  reservationEnvKeys: string[]
}): GatewayHook {
  return {
    id: "agent-reservation-guard",
    priority: 345,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.before") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolBeforePayload
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase()
      if (tool !== "write" && tool !== "edit" && tool !== "apply_patch") {
        return
      }
      if (hasReservation(options.reservationEnvKeys)) {
        return
      }
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "")
      writeGatewayEventAudit(directory, {
        hook: "agent-reservation-guard",
        stage: "skip",
        reason_code: "file_reservation_missing",
        session_id: sessionId,
      })
      if (options.enforce) {
        throw new Error(
          "[agent-reservation-guard] Missing active file reservation marker. Reserve files before editing in coordinated runs.",
        )
      }
    },
  }
}
