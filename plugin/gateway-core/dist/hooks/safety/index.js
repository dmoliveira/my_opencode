import { REASON_CODES } from "../../bridge/reason-codes.js";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { cleanupOrphanGatewayLoop, nowIso, transactGatewayStateDomain, } from "../../state/storage.js";
// Resolves session id when present in event payload.
function resolveSessionId(payload) {
    const direct = payload.properties?.sessionID;
    if (typeof direct === "string" && direct.trim()) {
        return direct.trim();
    }
    const infoId = payload.properties?.info?.id;
    if (typeof infoId === "string" && infoId.trim()) {
        return infoId.trim();
    }
    return "";
}
// Creates safety guard hook placeholder for gateway composition.
export function createSafetyHook(options) {
    return {
        id: "safety",
        priority: 300,
        async event(type, payload) {
            const eventPayload = (payload ?? {});
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            if (type === "session.idle") {
                cleanupOrphanGatewayLoop(directory, options.orphanMaxAgeHours);
                writeGatewayEventAudit(directory, {
                    hook: "safety",
                    stage: "maintenance",
                    reason_code: "orphan_cleanup_checked",
                });
                return;
            }
            if (type !== "session.deleted" && type !== "session.error") {
                return;
            }
            const sessionId = resolveSessionId(eventPayload);
            let skipReason = "no_active_loop";
            const deactivated = transactGatewayStateDomain(directory, "activeLoop", (current) => {
                const active = current && typeof current === "object" && !Array.isArray(current)
                    ? current
                    : null;
                if (!active || active.active !== true) {
                    skipReason = "no_active_loop";
                    return null;
                }
                if (!sessionId || String(active.sessionId ?? "") !== sessionId) {
                    skipReason = "session_mismatch";
                    return null;
                }
                return {
                    value: { active: false },
                    mode: "patch",
                    rootUpdates: { lastUpdatedAt: nowIso(), source: REASON_CODES.LOOP_STOPPED },
                };
            });
            if (!deactivated.changed) {
                writeGatewayEventAudit(directory, {
                    hook: "safety",
                    stage: "skip",
                    reason_code: skipReason,
                    has_session_id: sessionId.length > 0,
                });
                return;
            }
            writeGatewayEventAudit(directory, {
                hook: "safety",
                stage: "state",
                reason_code: REASON_CODES.LOOP_STOPPED,
                session_id: sessionId,
            });
            return;
        },
    };
}
