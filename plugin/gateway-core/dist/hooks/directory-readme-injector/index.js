import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { findNearestFile } from "../directory-context/finder.js";
import { readFilePrefix } from "../shared/read-file-prefix.js";
import { truncateInjectedText } from "../shared/injected-text-truncator.js";
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
            const readmeText = readFilePrefix(path, options.maxChars);
            const normalizedReadme = readmeText.trim();
            let contextLine = `Local README context loaded from: ${path}`;
            let reasonCode = "directory_readme_context_injected";
            if (normalizedReadme) {
                const truncated = truncateInjectedText(normalizedReadme, options.maxChars);
                contextLine = `${contextLine}\n\nREADME.md excerpt:\n${truncated.text}`;
                if (truncated.truncated) {
                    reasonCode = "directory_readme_context_truncated";
                }
            }
            eventPayload.output.output = `${eventPayload.output.output}\n\n${contextLine}`;
            lastInjectedPathBySession.set(sessionId, path);
            writeGatewayEventAudit(directory, {
                hook: "directory-readme-injector",
                stage: "state",
                reason_code: reasonCode,
                session_id: sessionId,
            });
        },
    };
}
