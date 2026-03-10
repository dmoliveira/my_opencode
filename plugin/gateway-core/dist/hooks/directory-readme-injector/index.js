import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { findNearestFile } from "../directory-context/finder.js";
import { readFilePrefix } from "../shared/read-file-prefix.js";
import { truncateInjectedText } from "../shared/injected-text-truncator.js";
const README_SYSTEM_MARKER = "Local README context loaded from:";
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
function buildReadmeContextLine(path, maxChars) {
    const readmeText = readFilePrefix(path, maxChars);
    const normalizedReadme = readmeText.trim();
    let contextLine = `Local README context loaded from: ${path}`;
    let reasonCode = "directory_readme_context_injected";
    if (normalizedReadme) {
        const truncated = truncateInjectedText(normalizedReadme, maxChars);
        contextLine = `${contextLine}\n\nREADME.md excerpt:\n${truncated.text}`;
        if (truncated.truncated) {
            reasonCode = "directory_readme_context_truncated";
        }
    }
    return { text: contextLine, reasonCode };
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
            if (type === "experimental.chat.system.transform") {
                const eventPayload = (payload ?? {});
                const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                    ? eventPayload.directory
                    : options.directory;
                const system = eventPayload.output?.system;
                if (!Array.isArray(system) || system.some((entry) => typeof entry === "string" && entry.includes(README_SYSTEM_MARKER))) {
                    return;
                }
                const path = findNearestFile(directory, "README.md");
                if (!path) {
                    return;
                }
                const sessionId = resolveSessionId(eventPayload);
                const context = buildReadmeContextLine(path, options.maxChars);
                system.unshift(context.text);
                if (sessionId) {
                    readmePathBySession.set(sessionId, path);
                    lastInjectedPathBySession.set(sessionId, path);
                }
                writeGatewayEventAudit(directory, {
                    hook: "directory-readme-injector",
                    stage: "inject",
                    reason_code: `${context.reasonCode}_system`,
                    session_id: sessionId || undefined,
                });
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
            const context = buildReadmeContextLine(path, options.maxChars);
            eventPayload.output.output = `${eventPayload.output.output}\n\n${context.text}`;
            lastInjectedPathBySession.set(sessionId, path);
            writeGatewayEventAudit(directory, {
                hook: "directory-readme-injector",
                stage: "state",
                reason_code: context.reasonCode,
                session_id: sessionId,
            });
        },
    };
}
