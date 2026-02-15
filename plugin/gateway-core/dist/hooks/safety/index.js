import { REASON_CODES } from "../../bridge/reason-codes.js";
import { cleanupOrphanGatewayLoop, deactivateGatewayLoop, loadGatewayState, } from "../../state/storage.js";
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
                return;
            }
            if (type !== "session.deleted" && type !== "session.error") {
                return;
            }
            const state = loadGatewayState(directory);
            const active = state?.activeLoop;
            if (!state || !active || active.active !== true) {
                return;
            }
            const sessionId = resolveSessionId(eventPayload);
            if (!sessionId || sessionId !== active.sessionId) {
                return;
            }
            deactivateGatewayLoop(directory, REASON_CODES.LOOP_STOPPED);
            return;
        },
    };
}
