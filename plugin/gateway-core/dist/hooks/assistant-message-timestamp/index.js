import { writeGatewayEventAudit } from "../../audit/event-audit.js";
const TIMESTAMP_PREFIX_LABEL = "[";
const TARGET_EVENT_TYPES = new Set([
    "message.updated",
    "message.part.updated",
    "message.part.delta",
]);
export function formatAssistantMessageTimestamp(timestamp) {
    const value = new Date(timestamp);
    const year = value.getFullYear();
    const month = value.getMonth() + 1;
    const day = value.getDate();
    const hours = String(value.getHours()).padStart(2, "0");
    const minutes = String(value.getMinutes()).padStart(2, "0");
    const seconds = String(value.getSeconds()).padStart(2, "0");
    return `[${year}-${month}-${day} ${hours}:${minutes}:${seconds}]`;
}
function debugAuditEnabled() {
    return process.env.MY_OPENCODE_ASSISTANT_TIMESTAMP_DEBUG === "1";
}
function prependTimestampToText(text, timestamp) {
    const trimmed = text.trim();
    if (!trimmed || trimmed.startsWith(TIMESTAMP_PREFIX_LABEL)) {
        return text;
    }
    return `${timestamp}\n${trimmed}`;
}
function prependTimestampToParts(parts, timestamp) {
    if (!Array.isArray(parts) || parts.length === 0) {
        return false;
    }
    const textPart = parts.find((part) => part?.type === "text" && typeof part.text === "string");
    if (!textPart) {
        return false;
    }
    const next = prependTimestampToText(textPart.text ?? "", timestamp);
    if (next === textPart.text) {
        return false;
    }
    textPart.text = next;
    return true;
}
function prependTimestampToLatestAssistantMessage(messages, timestamp) {
    if (!Array.isArray(messages) || messages.length === 0) {
        return false;
    }
    for (let index = messages.length - 1; index >= 0; index -= 1) {
        const message = messages[index];
        if (message?.info?.role !== "assistant") {
            continue;
        }
        const parts = Array.isArray(message.parts) ? message.parts : [];
        if (prependTimestampToParts(parts, timestamp)) {
            return true;
        }
        parts.unshift({ type: "text", text: timestamp });
        message.parts = parts;
        return true;
    }
    return false;
}
function assistantRole(properties) {
    return String(properties?.info?.role ?? properties?.role ?? "").trim();
}
function resolveMessageId(properties) {
    return String(properties?.info?.id ??
        properties?.messageID ??
        properties?.messageId ??
        properties?.part?.messageID ??
        properties?.part?.messageId ??
        "").trim();
}
function resolvePartId(properties) {
    return String(properties?.partID ?? properties?.partId ?? properties?.part?.id ?? "").trim();
}
function prependTimestampToAssistantLifecyclePayload(properties, timestamp) {
    if (!properties || assistantRole(properties) !== "assistant") {
        return false;
    }
    if (prependTimestampToParts(properties.parts, timestamp)) {
        return true;
    }
    if (prependTimestampToParts(properties.messageParts, timestamp)) {
        return true;
    }
    if (properties.message &&
        typeof properties.message === "object" &&
        prependTimestampToParts(properties.message.parts, timestamp)) {
        return true;
    }
    if (properties.part?.type === "text" && typeof properties.part.text === "string") {
        const next = prependTimestampToText(properties.part.text, timestamp);
        if (next !== properties.part.text) {
            properties.part.text = next;
            return true;
        }
    }
    if (properties.message && typeof properties.message === "object") {
        const messageText = properties.message.text;
        if (typeof messageText === "string") {
            const next = prependTimestampToText(messageText, timestamp);
            if (next !== messageText) {
                properties.message.text = next;
                return true;
            }
        }
    }
    for (const key of ["text", "content", "delta"]) {
        const value = properties[key];
        if (typeof value !== "string") {
            continue;
        }
        const next = prependTimestampToText(value, timestamp);
        if (next !== value) {
            properties[key] = next;
            return true;
        }
    }
    return false;
}
function writeDebugAudit(directory, type, properties, applied) {
    if (!debugAuditEnabled() || !directory || !TARGET_EVENT_TYPES.has(type)) {
        return;
    }
    const messageValue = properties?.message;
    writeGatewayEventAudit(directory, {
        hook: "assistant-message-timestamp",
        stage: applied ? "inject" : "state",
        reason_code: applied
            ? "assistant_timestamp_lifecycle_applied"
            : "assistant_timestamp_lifecycle_noop",
        event_type: type,
        role: assistantRole(properties),
        message_id: resolveMessageId(properties),
        part_id: resolvePartId(properties),
        field: String(properties?.field ?? ""),
        top_level_keys: properties ? Object.keys(properties).join(",") : "",
        info_keys: properties?.info && typeof properties.info === "object"
            ? Object.keys(properties.info).join(",")
            : "",
        part_keys: properties?.part && typeof properties.part === "object"
            ? Object.keys(properties.part).join(",")
            : "",
        has_part: Boolean(properties?.part),
        has_parts: Array.isArray(properties?.parts),
        has_message_parts: Boolean(messageValue) &&
            typeof messageValue === "object" &&
            Array.isArray(messageValue.parts),
        text_preview: typeof properties?.text === "string"
            ? properties.text.slice(0, 80)
            : typeof properties?.delta === "string"
                ? properties.delta.slice(0, 80)
                : typeof properties?.part?.text === "string"
                    ? properties.part.text.slice(0, 80)
                    : Array.isArray(properties?.parts) && typeof properties.parts[0]?.text === "string"
                        ? properties.parts[0].text.slice(0, 80)
                        : "",
    });
}
export function createAssistantMessageTimestampHook(options) {
    const now = options.now ?? (() => Date.now());
    const assistantMessageIds = new Set();
    const stampedPartIds = new Set();
    const stampedMessageIds = new Set();
    return {
        id: "assistant-message-timestamp",
        priority: 341,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                assistantMessageIds.clear();
                stampedPartIds.clear();
                stampedMessageIds.clear();
                return;
            }
            const timestamp = formatAssistantMessageTimestamp(now());
            if (type === "experimental.chat.messages.transform") {
                const eventPayload = (payload ?? {});
                prependTimestampToLatestAssistantMessage(eventPayload.output?.messages, timestamp);
                return;
            }
            if (type === "experimental.text.complete") {
                const eventPayload = (payload ?? {});
                if (typeof eventPayload.output?.text === "string") {
                    eventPayload.output.text = prependTimestampToText(eventPayload.output.text, timestamp);
                }
                return;
            }
            if (TARGET_EVENT_TYPES.has(type)) {
                const eventPayload = (payload ?? {});
                const properties = eventPayload.properties;
                let applied = false;
                if (type === "message.updated") {
                    const messageId = resolveMessageId(properties);
                    if (assistantRole(properties) === "assistant" && messageId) {
                        assistantMessageIds.add(messageId);
                    }
                    applied = prependTimestampToAssistantLifecyclePayload(properties, timestamp);
                }
                else if (type === "message.part.updated") {
                    const messageId = resolveMessageId(properties);
                    const partId = resolvePartId(properties);
                    if (messageId &&
                        assistantMessageIds.has(messageId) &&
                        properties?.part?.type === "text" &&
                        typeof properties.part.text === "string" &&
                        !stampedPartIds.has(partId || messageId)) {
                        const next = prependTimestampToText(properties.part.text, timestamp);
                        if (next !== properties.part.text) {
                            properties.part.text = next;
                            stampedPartIds.add(partId || messageId);
                            stampedMessageIds.add(messageId);
                            applied = true;
                        }
                    }
                }
                else if (type === "message.part.delta") {
                    const messageId = resolveMessageId(properties);
                    const partId = resolvePartId(properties);
                    const stampKey = partId || messageId;
                    const deltaText = properties?.delta;
                    if (messageId &&
                        assistantMessageIds.has(messageId) &&
                        typeof deltaText === "string" &&
                        !stampedPartIds.has(stampKey)) {
                        const next = prependTimestampToText(deltaText, timestamp);
                        if (next !== deltaText && properties) {
                            properties.delta = next;
                            stampedPartIds.add(stampKey);
                            stampedMessageIds.add(messageId);
                            applied = true;
                        }
                    }
                }
                writeDebugAudit(eventPayload.directory, type, eventPayload.properties, applied);
                return;
            }
            if (type !== "session.idle") {
                return;
            }
            const eventPayload = (payload ?? {});
            if (typeof eventPayload.output?.output !== "string") {
                return;
            }
            eventPayload.output.output = prependTimestampToText(eventPayload.output.output, timestamp);
        },
    };
}
