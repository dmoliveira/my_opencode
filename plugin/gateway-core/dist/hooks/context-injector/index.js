import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { REASON_CODES } from "../../bridge/reason-codes.js";
import { DEFAULT_INJECTED_TEXT_MAX_CHARS, truncateInjectedText } from "../shared/injected-text-truncator.js";
// Resolves session id from known payload variants.
function resolveSessionId(payload, fallbackSessionId = "") {
    const record = payload;
    const candidates = [
        record.input?.sessionID,
        record.input?.sessionId,
        record.properties?.sessionID,
        record.properties?.sessionId,
        record.properties?.info?.id,
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
            const sessionIdCandidates = [messages[idx]?.info?.sessionID, messages[idx]?.info?.sessionId];
            for (const value of sessionIdCandidates) {
                if (typeof value === "string" && value.trim()) {
                    return value.trim();
                }
            }
        }
    }
    return fallbackSessionId.trim();
}
// Injects pending context into mutable output parts.
function injectIntoParts(parts, merged) {
    const textPart = parts.find((part) => part.type === "text" && typeof part.text === "string");
    if (!textPart || typeof textPart.text !== "string") {
        return false;
    }
    textPart.text = `${merged}\n\n---\n\n${textPart.text}`;
    return true;
}
// Creates context injector that injects pending context on chat and transform hooks.
export function createContextInjectorHook(options) {
    let lastKnownSessionId = "";
    const maxChars = typeof options.maxChars === "number" && Number.isFinite(options.maxChars) && options.maxChars > 0
        ? Math.floor(options.maxChars)
        : DEFAULT_INJECTED_TEXT_MAX_CHARS;
    return {
        id: "context-injector",
        priority: 295,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const eventPayload = (payload ?? {});
                const sessionId = eventPayload.properties?.info?.id;
                if (typeof sessionId === "string" && sessionId.trim()) {
                    const normalized = sessionId.trim();
                    options.collector.clear(normalized);
                    if (lastKnownSessionId === normalized) {
                        lastKnownSessionId = "";
                    }
                }
                return;
            }
            if (type === "chat.message") {
                const eventPayload = (payload ?? {});
                const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                    ? eventPayload.directory
                    : options.directory;
                const sessionId = resolveSessionId(eventPayload, lastKnownSessionId);
                if (sessionId) {
                    lastKnownSessionId = sessionId;
                }
                const parts = eventPayload.output?.parts;
                if (!sessionId || !Array.isArray(parts) || !options.collector.hasPending(sessionId)) {
                    return;
                }
                const pending = options.collector.consume(sessionId);
                if (!pending.hasContent) {
                    return;
                }
                const truncated = truncateInjectedText(pending.merged, maxChars);
                if (truncated.truncated) {
                    writeGatewayEventAudit(directory, {
                        hook: "context-injector",
                        stage: "inject",
                        reason_code: REASON_CODES.CONTEXT_TRUNCATED_CHAT,
                        session_id: sessionId,
                        context_length_before: truncated.originalLength,
                        context_length_after: truncated.text.length,
                    });
                }
                if (!injectIntoParts(parts, truncated.text)) {
                    writeGatewayEventAudit(directory, {
                        hook: "context-injector",
                        stage: "inject",
                        reason_code: REASON_CODES.CONTEXT_REQUEUED_NO_TEXT_PART,
                        session_id: sessionId,
                        context_length: truncated.text.length,
                    });
                    options.collector.register(sessionId, {
                        source: "context-injector-requeue",
                        id: "chat-message-fallback",
                        content: truncated.text,
                        priority: "high",
                    });
                    return;
                }
                writeGatewayEventAudit(directory, {
                    hook: "context-injector",
                    stage: "inject",
                    reason_code: REASON_CODES.CONTEXT_INJECT_CHAT,
                    session_id: sessionId,
                    context_length: truncated.text.length,
                });
                return;
            }
            if (type !== "experimental.chat.messages.transform") {
                return;
            }
            const eventPayload = (payload ?? {});
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = resolveSessionId(eventPayload, lastKnownSessionId);
            if (sessionId) {
                lastKnownSessionId = sessionId;
            }
            const messages = eventPayload.output?.messages;
            if (!sessionId || !Array.isArray(messages) || !options.collector.hasPending(sessionId)) {
                return;
            }
            let lastUserIndex = -1;
            for (let idx = messages.length - 1; idx >= 0; idx -= 1) {
                if (messages[idx]?.info?.role === "user") {
                    lastUserIndex = idx;
                    break;
                }
            }
            if (lastUserIndex < 0) {
                if (options.collector.hasPending(sessionId)) {
                    writeGatewayEventAudit(directory, {
                        hook: "context-injector",
                        stage: "inject",
                        reason_code: REASON_CODES.CONTEXT_TRANSFORM_NO_USER_MESSAGE,
                        session_id: sessionId,
                    });
                }
                return;
            }
            const parts = messages[lastUserIndex].parts;
            if (!Array.isArray(parts)) {
                if (options.collector.hasPending(sessionId)) {
                    writeGatewayEventAudit(directory, {
                        hook: "context-injector",
                        stage: "inject",
                        reason_code: REASON_CODES.CONTEXT_TRANSFORM_NO_PARTS,
                        session_id: sessionId,
                    });
                }
                return;
            }
            const pending = options.collector.consume(sessionId);
            if (!pending.hasContent) {
                return;
            }
            const truncated = truncateInjectedText(pending.merged, maxChars);
            if (truncated.truncated) {
                writeGatewayEventAudit(directory, {
                    hook: "context-injector",
                    stage: "inject",
                    reason_code: REASON_CODES.CONTEXT_TRUNCATED_TRANSFORM,
                    session_id: sessionId,
                    context_length_before: truncated.originalLength,
                    context_length_after: truncated.text.length,
                });
            }
            const synthetic = {
                type: "text",
                text: truncated.text,
                synthetic: true,
            };
            parts.unshift(synthetic);
            writeGatewayEventAudit(directory, {
                hook: "context-injector",
                stage: "inject",
                reason_code: REASON_CODES.CONTEXT_INJECT_TRANSFORM,
                session_id: sessionId,
                context_length: truncated.text.length,
            });
        },
    };
}
