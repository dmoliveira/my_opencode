import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
// Returns true when environment contains active reservation marker.
function hasReservation(envKeys) {
    for (const key of envKeys) {
        const value = String(process.env[key] ?? "").trim().toLowerCase();
        if (value === "1" || value === "true" || value === "yes" || value === "on") {
            return true;
        }
    }
    return false;
}
function readReservationState(directory, stateFile) {
    try {
        const content = readFileSync(resolve(directory, stateFile), "utf-8");
        const parsed = JSON.parse(content);
        return parsed && typeof parsed === "object" ? parsed : {};
    }
    catch {
        return {};
    }
}
// Creates reservation guard for multi-agent file edit coordination.
export function createAgentReservationGuardHook(options) {
    return {
        id: "agent-reservation-guard",
        priority: 345,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.before") {
                return;
            }
            const eventPayload = (payload ?? {});
            const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
            if (tool !== "write" && tool !== "edit" && tool !== "apply_patch") {
                return;
            }
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const state = readReservationState(directory, options.stateFile);
            const activeFromState = state.reservationActive === true ||
                state.active === true;
            if (hasReservation(options.reservationEnvKeys) || activeFromState) {
                return;
            }
            const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "");
            writeGatewayEventAudit(directory, {
                hook: "agent-reservation-guard",
                stage: "skip",
                reason_code: "file_reservation_missing",
                session_id: sessionId,
            });
            if (options.enforce) {
                throw new Error("[agent-reservation-guard] Missing active file reservation marker. Reserve files before editing in coordinated runs.");
            }
        },
    };
}
