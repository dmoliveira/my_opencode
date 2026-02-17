const TODOREAD_MARKER = "[todoread CADENCE REMINDER]";
const START_HINT = [
    TODOREAD_MARKER,
    "Session start checkpoint detected.",
    "- Run TodoRead now to align pending priorities before new work",
].join("\n");
const CHECKPOINT_HINT = [
    TODOREAD_MARKER,
    "Progress checkpoint detected.",
    "- Run TodoRead before starting the next task block",
    "- Re-sync pending/in-progress/completed statuses first",
].join("\n");
const START_PATTERNS = [/session start/i, /starting new session/i, /beginning of conversations/i];
const CHECKPOINT_PATTERNS = [
    /\b(next\s+(step|action|task|block))\b/i,
    /\b(completed?|done|merged|checks?\s+passed)\b/i,
];
function resolveSessionId(payload) {
    const candidates = [
        payload.input?.sessionID,
        payload.input?.sessionId,
        payload.properties?.sessionID,
        payload.properties?.sessionId,
        payload.properties?.info?.id,
    ];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
function getSessionState(store, sessionId) {
    const existing = store.get(sessionId);
    if (existing) {
        return existing;
    }
    const created = { startReminderSent: false, eventsSinceReminder: 0 };
    store.set(sessionId, created);
    return created;
}
function hasStartSignal(output) {
    return START_PATTERNS.some((pattern) => pattern.test(output));
}
function hasCheckpointSignal(output) {
    return CHECKPOINT_PATTERNS.some((pattern) => pattern.test(output));
}
export function createTodoreadCadenceReminderHook(options) {
    const sessionState = new Map();
    return {
        id: "todoread-cadence-reminder",
        priority: 359,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const sessionId = resolveSessionId((payload ?? {}));
                if (sessionId) {
                    sessionState.delete(sessionId);
                }
                return;
            }
            if (type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            const sessionId = resolveSessionId(eventPayload);
            if (!sessionId || typeof eventPayload.output?.output !== "string") {
                return;
            }
            const output = eventPayload.output.output;
            if (output.includes(TODOREAD_MARKER)) {
                return;
            }
            const state = getSessionState(sessionState, sessionId);
            const cooldownEvents = Math.max(1, Math.floor(options.cooldownEvents));
            if (!state.startReminderSent && hasStartSignal(output)) {
                eventPayload.output.output = `${output}\n\n${START_HINT}`;
                state.startReminderSent = true;
                state.eventsSinceReminder = 0;
                return;
            }
            state.eventsSinceReminder += 1;
            if (state.eventsSinceReminder < cooldownEvents || !hasCheckpointSignal(output)) {
                return;
            }
            eventPayload.output.output = `${output}\n\n${CHECKPOINT_HINT}`;
            state.eventsSinceReminder = 0;
        },
    };
}
