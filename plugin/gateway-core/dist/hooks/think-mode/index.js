const THINK_PROMPT_PATTERN = /(think(ing)?|step by step|reason(ing)?|analy[sz]e)/;
const THINK_HINT = "[think mode] Keep reasoning structured: state assumptions, break down steps, and verify conclusions before action.";
// Resolves stable session id from lifecycle/chat payloads.
function resolveSessionId(payload) {
    const candidates = [
        payload.properties?.info?.id,
        payload.properties?.sessionID,
        payload.properties?.sessionId,
    ];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
// Extracts prompt text from chat payload.
function resolvePrompt(payload) {
    const candidates = [payload.properties?.prompt, payload.properties?.message, payload.properties?.text];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
// Creates think-mode hook that appends structured reasoning guidance.
export function createThinkModeHook(options) {
    const sessionsWithHint = new Set();
    return {
        id: "think-mode",
        priority: 367,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted" || type === "session.compacted") {
                const sessionId = resolveSessionId((payload ?? {}));
                if (sessionId) {
                    sessionsWithHint.delete(sessionId);
                }
                return;
            }
            if (type !== "chat.message") {
                return;
            }
            const eventPayload = (payload ?? {});
            const prompt = resolvePrompt(eventPayload).toLowerCase();
            if (!prompt || !THINK_PROMPT_PATTERN.test(prompt)) {
                return;
            }
            const sessionId = resolveSessionId(eventPayload);
            if (sessionId && sessionsWithHint.has(sessionId)) {
                return;
            }
            const parts = eventPayload.output?.parts;
            if (!Array.isArray(parts) || parts.length === 0) {
                return;
            }
            const firstText = parts.find((part) => part.type === "text");
            if (!firstText || typeof firstText.text !== "string") {
                return;
            }
            if (!firstText.text.includes(THINK_HINT)) {
                firstText.text = `${firstText.text}\n\n${THINK_HINT}`;
            }
            if (sessionId) {
                sessionsWithHint.add(sessionId);
            }
        },
    };
}
