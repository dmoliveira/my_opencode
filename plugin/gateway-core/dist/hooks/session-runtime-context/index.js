import { writeGatewayEventAudit } from "../../audit/event-audit.js";
const SESSION_CONTEXT_MARKER = "[SESSION CONTEXT]";
function resolveSessionId(payload) {
    const typed = payload;
    const candidates = [
        typed.input?.sessionID,
        typed.input?.sessionId,
        typed.properties?.sessionID,
        typed.properties?.sessionId,
        typed.properties?.info?.id,
    ];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    const transformPayload = payload;
    const messages = transformPayload.output?.messages;
    if (Array.isArray(messages)) {
        for (let idx = messages.length - 1; idx >= 0; idx -= 1) {
            const messageCandidates = [messages[idx]?.info?.sessionID, messages[idx]?.info?.sessionId];
            for (const value of messageCandidates) {
                if (typeof value === "string" && value.trim()) {
                    return value.trim();
                }
            }
        }
    }
    return "";
}
function buildSessionContext(sessionId) {
    return [
        SESSION_CONTEXT_MARKER,
        `authoritative_runtime_session_id=${sessionId}`,
        "Use this exact session id for commits, logs, telemetry, and external tooling created during this runtime session.",
        "If the user asks for the current runtime session id, return this exact session id directly.",
        "Bash tool commands in this session expose OPENCODE_SESSION_ID when available.",
    ].join("\n");
}
function injectIntoParts(parts, content) {
    const textPart = parts.find((part) => part.type === "text" && typeof part.text === "string");
    if (!textPart || typeof textPart.text !== "string") {
        return false;
    }
    if (textPart.text.includes(SESSION_CONTEXT_MARKER)) {
        return false;
    }
    textPart.text = `${content}\n\n---\n\n${textPart.text}`;
    return true;
}
export function createSessionRuntimeContextHook(options) {
    const injectedSessions = new Set();
    return {
        id: "session-runtime-context",
        priority: 294,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const sessionId = resolveSessionId((payload ?? {}));
                if (sessionId) {
                    injectedSessions.delete(sessionId);
                }
                return;
            }
            if (type === "session.compacted") {
                const sessionId = resolveSessionId((payload ?? {}));
                if (sessionId) {
                    injectedSessions.delete(sessionId);
                }
                return;
            }
            if (type !== "experimental.chat.messages.transform") {
                return;
            }
            const eventPayload = (payload ?? {});
            const sessionId = resolveSessionId(eventPayload);
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            if (!sessionId || injectedSessions.has(sessionId)) {
                return;
            }
            const messages = eventPayload.output?.messages;
            if (!Array.isArray(messages)) {
                return;
            }
            let target = -1;
            for (let idx = messages.length - 1; idx >= 0; idx -= 1) {
                if (messages[idx]?.info?.role === "user") {
                    target = idx;
                    break;
                }
            }
            if (target < 0 || !Array.isArray(messages[target]?.parts)) {
                return;
            }
            if (!injectIntoParts(messages[target].parts ?? [], buildSessionContext(sessionId))) {
                return;
            }
            injectedSessions.add(sessionId);
            writeGatewayEventAudit(directory, {
                hook: "session-runtime-context",
                stage: "inject",
                reason_code: "session_runtime_context_injected_transform",
                session_id: sessionId,
            });
        },
    };
}
