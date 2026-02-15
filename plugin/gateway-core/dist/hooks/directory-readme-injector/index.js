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
// Creates README injector hook for local docs context hints.
export function createDirectoryReadmeInjectorHook(options) {
    const readmePathBySession = new Map();
    const lastInjectedPathBySession = new Map();
    return {
        id: "directory-readme-injector",
        priority: 300,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const eventPayload = (payload ?? {});
                const sessionId = eventPayload.properties?.info?.id;
                if (typeof sessionId === "string" && sessionId.trim()) {
                    const key = sessionId.trim();
                    readmePathBySession.delete(key);
                    lastInjectedPathBySession.delete(key);
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
                const path = findNearestFile(directory, "README.md");
                if (path) {
                    readmePathBySession.set(sessionId, path);
                }
                else {
                    readmePathBySession.delete(sessionId);
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
            const path = sessionId ? readmePathBySession.get(sessionId) : null;
            if (!path || typeof eventPayload.output?.output !== "string") {
                return;
            }
            if (lastInjectedPathBySession.get(sessionId) === path) {
                return;
            }
            eventPayload.output.output = `${eventPayload.output.output}\n\nLocal README context loaded from: ${path}`;
            lastInjectedPathBySession.set(sessionId, path);
            writeGatewayEventAudit(directory, {
                hook: "directory-readme-injector",
                stage: "state",
                reason_code: "directory_readme_context_injected",
                session_id: sessionId,
            });
        },
    };
}
