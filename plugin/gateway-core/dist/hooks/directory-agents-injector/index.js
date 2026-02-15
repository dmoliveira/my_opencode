import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { findNearestFile } from "../directory-context/finder.js";
// Resolves stable session id from tool payload.
function resolveSessionId(payload) {
    const candidates = [payload.input?.sessionID, payload.input?.sessionId];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
// Creates AGENTS.md injector hook for local directory context hints.
export function createDirectoryAgentsInjectorHook(options) {
    const agentsPathBySession = new Map();
    return {
        id: "directory-agents-injector",
        priority: 299,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const eventPayload = (payload ?? {});
                const sessionId = eventPayload.properties?.info?.id;
                if (typeof sessionId === "string" && sessionId.trim()) {
                    agentsPathBySession.delete(sessionId.trim());
                }
                return;
            }
            if (type === "tool.execute.before") {
                const eventPayload = (payload ?? {});
                const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                    ? eventPayload.directory
                    : options.directory;
                const sessionId = resolveSessionId(eventPayload);
                if (!sessionId) {
                    return;
                }
                const path = findNearestFile(directory, "AGENTS.md");
                if (path) {
                    agentsPathBySession.set(sessionId, path);
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
            const path = sessionId ? agentsPathBySession.get(sessionId) : null;
            if (!path || typeof eventPayload.output?.output !== "string") {
                return;
            }
            eventPayload.output.output = `${eventPayload.output.output}\n\nLocal instructions loaded from: ${path}`;
            writeGatewayEventAudit(directory, {
                hook: "directory-agents-injector",
                stage: "state",
                reason_code: "directory_agents_context_injected",
                session_id: sessionId,
            });
        },
    };
}
