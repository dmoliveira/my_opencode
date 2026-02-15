import { writeGatewayEventAudit } from "../../audit/event-audit.js";
const DEFAULT_ACTUAL_LIMIT = 200_000;
// Resolves effective session id across payload variants.
function resolveSessionId(payload) {
    const candidates = [payload.input?.sessionID, payload.input?.sessionId];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
// Resolves Anthropic actual token limit from runtime environment flags.
function anthropicActualLimit() {
    return process.env.ANTHROPIC_1M_CONTEXT === "true" || process.env.VERTEX_ANTHROPIC_1M_CONTEXT === "true"
        ? 1_000_000
        : DEFAULT_ACTUAL_LIMIT;
}
// Creates preemptive compaction hook for high context pressure sessions.
export function createPreemptiveCompactionHook(options) {
    const compactionInProgress = new Set();
    const compactedSessions = new Set();
    return {
        id: "preemptive-compaction",
        priority: 270,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const eventPayload = (payload ?? {});
                const sessionId = eventPayload.properties?.info?.id;
                if (typeof sessionId === "string" && sessionId.trim()) {
                    compactionInProgress.delete(sessionId.trim());
                    compactedSessions.delete(sessionId.trim());
                }
                return;
            }
            if (type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = resolveSessionId(eventPayload);
            if (!sessionId) {
                return;
            }
            if (compactedSessions.has(sessionId) || compactionInProgress.has(sessionId)) {
                return;
            }
            const client = options.client?.session;
            if (!client) {
                return;
            }
            try {
                const response = await client.messages({ path: { id: sessionId }, query: { directory } });
                const messages = Array.isArray(response.data) ? response.data : [];
                const assistants = messages
                    .filter((item) => item.info?.role === "assistant")
                    .map((item) => item.info);
                const last = assistants[assistants.length - 1];
                if (!last) {
                    return;
                }
                const actualLimit = last.providerID === "anthropic" ? anthropicActualLimit() : DEFAULT_ACTUAL_LIMIT;
                const totalInputTokens = (last.tokens?.input ?? 0) + (last.tokens?.cache?.read ?? 0);
                const usageRatio = totalInputTokens / actualLimit;
                if (usageRatio < options.warningThreshold) {
                    return;
                }
                const providerID = typeof last.providerID === "string" ? last.providerID : "";
                const modelID = typeof last.modelID === "string" ? last.modelID : "";
                if (!providerID || !modelID) {
                    return;
                }
                compactionInProgress.add(sessionId);
                await client.summarize({
                    path: { id: sessionId },
                    body: { providerID, modelID, auto: true },
                    query: { directory },
                });
                compactedSessions.add(sessionId);
                writeGatewayEventAudit(directory, {
                    hook: "preemptive-compaction",
                    stage: "state",
                    reason_code: "session_compacted_preemptively",
                    session_id: sessionId,
                });
            }
            catch {
                writeGatewayEventAudit(directory, {
                    hook: "preemptive-compaction",
                    stage: "skip",
                    reason_code: "session_compaction_failed",
                    session_id: sessionId,
                });
            }
            finally {
                compactionInProgress.delete(sessionId);
            }
        },
    };
}
