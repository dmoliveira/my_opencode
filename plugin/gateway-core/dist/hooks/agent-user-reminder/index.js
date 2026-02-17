const COMPLEX_TASK_PATTERN = /(debug|architecture|refactor|research|investigate|root cause|postmortem|optimi[sz]e)/;
// Extracts prompt text from chat payload properties.
function promptText(payload) {
    const props = payload.properties ?? {};
    const candidates = [props.prompt, props.message, props.text];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
// Resolves session id from event payload.
function resolveSessionId(payload) {
    const candidates = [
        payload.properties?.info?.id,
        payload.properties?.sessionID,
        payload.properties?.sessionId,
    ];
    for (const id of candidates) {
        if (typeof id === "string" && id.trim()) {
            return id.trim();
        }
    }
    return "";
}
// Creates session guidance hook for complex tasks.
export function createAgentUserReminderHook(options) {
    const remindedSessions = new Set();
    return {
        id: "agent-user-reminder",
        priority: 365,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted" || type === "session.compacted") {
                const sessionPayload = (payload ?? {});
                const sessionId = resolveSessionId(sessionPayload);
                if (sessionId) {
                    remindedSessions.delete(sessionId);
                }
                return;
            }
            if (type !== "chat.message") {
                return;
            }
            const eventPayload = (payload ?? {});
            const sessionId = resolveSessionId(eventPayload);
            if (sessionId && remindedSessions.has(sessionId)) {
                return;
            }
            const prompt = promptText(eventPayload).toLowerCase();
            if (!prompt || !COMPLEX_TASK_PATTERN.test(prompt)) {
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
            firstText.text = `${firstText.text}\n\n[session guidance] For complex work, use focused passes: discover with explore, validate with verifier, and run reviewer before final delivery.`;
            if (sessionId) {
                remindedSessions.add(sessionId);
            }
        },
    };
}
