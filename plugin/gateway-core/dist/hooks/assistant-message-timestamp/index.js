const TIMESTAMP_PREFIX_LABEL = "[";
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
function prependTimestampToText(text, timestamp) {
    const trimmed = text.trim();
    if (!trimmed || trimmed.startsWith(TIMESTAMP_PREFIX_LABEL)) {
        return text;
    }
    return `${timestamp}\n${trimmed}`;
}
function prependTimestampToLatestAssistantMessage(messages, timestamp) {
    if (!Array.isArray(messages) || messages.length === 0) {
        return;
    }
    for (let index = messages.length - 1; index >= 0; index -= 1) {
        const message = messages[index];
        if (message?.info?.role !== "assistant") {
            continue;
        }
        const parts = Array.isArray(message.parts) ? message.parts : [];
        const firstTextPart = parts.find((part) => part?.type === "text" && typeof part.text === "string");
        if (firstTextPart) {
            firstTextPart.text = prependTimestampToText(firstTextPart.text ?? "", timestamp);
            return;
        }
        parts.unshift({ type: "text", text: timestamp });
        message.parts = parts;
        return;
    }
}
export function createAssistantMessageTimestampHook(options) {
    const now = options.now ?? (() => Date.now());
    return {
        id: "assistant-message-timestamp",
        priority: 341,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            const timestamp = formatAssistantMessageTimestamp(now());
            if (type === "experimental.chat.messages.transform") {
                const eventPayload = (payload ?? {});
                prependTimestampToLatestAssistantMessage(eventPayload.output?.messages, timestamp);
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
