import { REASON_CODES } from "../../bridge/reason-codes.js"
import { writeGatewayEventAudit } from "../../audit/event-audit.js"
import { nowIso, transactGatewayStateDomain } from "../../state/storage.js"
import type { GatewayHook } from "../registry.js"

interface SessionIdlePayload {
  properties?: { sessionID?: string; info?: { id?: string } }
  directory?: string
}

// Resolves session id from idle payload.
function resolveSessionId(payload: SessionIdlePayload): string {
  const direct = payload.properties?.sessionID
  if (typeof direct === "string" && direct.trim()) {
    return direct.trim()
  }
  const fallback = payload.properties?.info?.id
  if (typeof fallback === "string" && fallback.trim()) {
    return fallback.trim()
  }
  return ""
}

// Creates stale loop expiry guard for old active loop sessions.
export function createStaleLoopExpiryGuardHook(options: {
  directory: string
  enabled: boolean
  maxAgeMinutes: number
}): GatewayHook {
  const maxAgeMinutes = options.maxAgeMinutes > 0 ? options.maxAgeMinutes : 120
  return {
    id: "stale-loop-expiry-guard",
    priority: 425,
    events: ["session.idle"],
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "session.idle") {
        return
      }
      const eventPayload = (payload ?? {}) as SessionIdlePayload
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : options.directory
      const sessionId = resolveSessionId(eventPayload)
      const expired = transactGatewayStateDomain(directory, "activeLoop", (current) => {
        const active =
          current && typeof current === "object" && !Array.isArray(current)
            ? (current as Record<string, unknown>)
            : null
        if (
          !active ||
          active.active !== true ||
          !sessionId ||
          String(active.sessionId ?? "") !== sessionId
        ) {
          return null
        }
        const startedAt = Date.parse(String(active.startedAt ?? ""))
        if (!Number.isFinite(startedAt)) {
          return null
        }
        const ageMs = Date.now() - startedAt
        const maxAgeMs = maxAgeMinutes * 60 * 1000
        if (ageMs <= maxAgeMs) {
          return null
        }
        return {
          value: { active: false },
          mode: "patch",
          rootUpdates: {
            lastUpdatedAt: nowIso(),
            source: REASON_CODES.LOOP_ORPHAN_CLEANED,
          },
        }
      })
      if (!expired.changed) {
        return
      }
      writeGatewayEventAudit(directory, {
        hook: "stale-loop-expiry-guard",
        stage: "state",
        reason_code: "stale_loop_expired",
        session_id: sessionId,
      })
    },
  }
}
