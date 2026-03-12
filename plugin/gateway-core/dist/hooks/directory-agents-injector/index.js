import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { findNearestFile } from "../directory-context/finder.js";
import { readFilePrefix } from "../shared/read-file-prefix.js";
import { truncateInjectedText } from "../shared/injected-text-truncator.js";
const AGENTS_SYSTEM_MARKER = "Local instructions loaded from:";
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
function buildAgentsContextLine(path, maxChars) {
    const guidanceText = readFilePrefix(path, maxChars);
    const normalizedGuidance = guidanceText.trim();
    let contextLine = `Local instructions loaded from: ${path}`;
    let reasonCode = "directory_agents_context_injected";
    if (normalizedGuidance) {
        const truncated = truncateInjectedText(normalizedGuidance, maxChars);
        contextLine = `${contextLine}\n\nAGENTS.md guidance excerpt:\n${truncated.text}`;
        if (truncated.truncated) {
            reasonCode = "directory_agents_context_truncated";
        }
    }
    return { text: contextLine, reasonCode };
}
// Creates AGENTS.md injector hook for local directory context hints.
export function createDirectoryAgentsInjectorHook(options) {
    const agentsPathBySession = new Map();
    const lastInjectedPathBySession = new Map();
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
                    const key = sessionId.trim();
                    agentsPathBySession.delete(key);
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
                const path = findNearestFile(directory, "AGENTS.md");
                if (path) {
                    agentsPathBySession.set(sessionId, path);
                }
                else {
                    agentsPathBySession.delete(sessionId);
                }
                return;
            }
            if (type === "experimental.chat.system.transform") {
                const eventPayload = (payload ?? {});
                const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                    ? eventPayload.directory
                    : options.directory;
                const system = eventPayload.output?.system;
                if (!Array.isArray(system) || system.some((entry) => typeof entry === "string" && entry.includes(AGENTS_SYSTEM_MARKER))) {
                    return;
                }
                const path = findNearestFile(directory, "AGENTS.md");
                if (!path) {
                    return;
                }
                const sessionId = resolveSessionId(eventPayload);
                const context = buildAgentsContextLine(path, options.maxChars);
                system.unshift(context.text);
                if (sessionId) {
                    agentsPathBySession.set(sessionId, path);
                    lastInjectedPathBySession.set(sessionId, path);
                }
                writeGatewayEventAudit(directory, {
                    hook: "directory-agents-injector",
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
            const path = sessionId ? agentsPathBySession.get(sessionId) : null;
            if (!path || typeof eventPayload.output?.output !== "string") {
                return;
            }
            if (lastInjectedPathBySession.get(sessionId) === path) {
                return;
            }
            const context = buildAgentsContextLine(path, options.maxChars);
            eventPayload.output.output = `${eventPayload.output.output}\n\n${context.text}`;
            lastInjectedPathBySession.set(sessionId, path);
            writeGatewayEventAudit(directory, {
                hook: "directory-agents-injector",
                stage: "state",
                reason_code: context.reasonCode,
                session_id: sessionId,
            });
        },
    };
}
