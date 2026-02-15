import { writeGatewayEventAudit } from "../../audit/event-audit.js";
// Returns true when event error resembles recoverable transient session failure.
function isRecoverableError(error) {
    const candidate = error && typeof error === "object" && "message" in error
        ? String(error.message ?? "")
        : String(error ?? "");
    const message = candidate.toLowerCase();
    return (message.includes("context") ||
        message.includes("rate limit") ||
        message.includes("temporar") ||
        message.includes("network") ||
        message.includes("timeout"));
}
// Resolves session id from error event payload.
function resolveSessionId(payload) {
    const candidates = [payload.properties?.sessionID, payload.properties?.info?.id];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
// Creates session recovery hook that attempts one auto-resume per active error session.
export function createSessionRecoveryHook(options) {
    const recoveringSessions = new Set();
    return {
        id: "session-recovery",
        priority: 280,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            const eventPayload = (payload ?? {});
            if (type === "session.deleted") {
                const sessionId = resolveSessionId(eventPayload);
                if (sessionId) {
                    recoveringSessions.delete(sessionId);
                }
                return;
            }
            if (type !== "session.error") {
                return;
            }
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = resolveSessionId(eventPayload);
            if (!sessionId) {
                writeGatewayEventAudit(directory, {
                    hook: "session-recovery",
                    stage: "skip",
                    reason_code: "missing_session_id",
                });
                return;
            }
            if (recoveringSessions.has(sessionId)) {
                writeGatewayEventAudit(directory, {
                    hook: "session-recovery",
                    stage: "skip",
                    reason_code: "recovery_in_progress",
                    session_id: sessionId,
                });
                return;
            }
            const error = eventPayload.properties?.error ?? eventPayload.properties?.info?.error;
            if (!isRecoverableError(error)) {
                writeGatewayEventAudit(directory, {
                    hook: "session-recovery",
                    stage: "skip",
                    reason_code: "error_not_recoverable",
                    session_id: sessionId,
                });
                return;
            }
            if (!options.autoResume) {
                writeGatewayEventAudit(directory, {
                    hook: "session-recovery",
                    stage: "skip",
                    reason_code: "auto_resume_disabled",
                    session_id: sessionId,
                });
                return;
            }
            const client = options.client?.session;
            if (!client) {
                writeGatewayEventAudit(directory, {
                    hook: "session-recovery",
                    stage: "skip",
                    reason_code: "session_client_unavailable",
                    session_id: sessionId,
                });
                return;
            }
            recoveringSessions.add(sessionId);
            try {
                await client.promptAsync({
                    path: { id: sessionId },
                    body: {
                        parts: [
                            {
                                type: "text",
                                text: "[session recovered - continuing previous task]",
                            },
                        ],
                    },
                    query: { directory },
                });
                writeGatewayEventAudit(directory, {
                    hook: "session-recovery",
                    stage: "state",
                    reason_code: "session_recovery_resume_injected",
                    session_id: sessionId,
                });
            }
            catch {
                writeGatewayEventAudit(directory, {
                    hook: "session-recovery",
                    stage: "skip",
                    reason_code: "session_recovery_resume_failed",
                    session_id: sessionId,
                });
            }
            finally {
                recoveringSessions.delete(sessionId);
            }
        },
    };
}
