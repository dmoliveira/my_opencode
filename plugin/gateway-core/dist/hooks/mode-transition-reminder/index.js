const MODE_REMINDER_MARKER = "[mode-transition REMINDER]";
const PLAN_MODE = "plan";
const BUILD_MODE = "build";
const PLAN_MODE_PATTERNS = [/plan mode is active/i];
const BUILD_MODE_PATTERNS = [
    /operational mode has changed from plan to build/i,
    /you are no longer in read-only mode/i,
];
const PLAN_MODE_HINT = [
    MODE_REMINDER_MARKER,
    "Plan mode reminder detected.",
    "- Stay read-only for investigation and planning steps",
    "- Write/update only the designated plan artifact",
    "- Exit plan mode before mutating commands or file edits",
].join("\n");
const BUILD_MODE_HINT = [
    MODE_REMINDER_MARKER,
    "Plan-to-build transition detected.",
    "- Resume implementation and command execution now",
    "- Run required validation checks before completion claims",
    "- Continue the active worktree flow until completion or blocker",
].join("\n");
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
function detectMode(output) {
    if (BUILD_MODE_PATTERNS.every((pattern) => pattern.test(output))) {
        return BUILD_MODE;
    }
    if (PLAN_MODE_PATTERNS.some((pattern) => pattern.test(output))) {
        return PLAN_MODE;
    }
    return null;
}
export function createModeTransitionReminderHook(options) {
    const sessionModeState = new Map();
    return {
        id: "mode-transition-reminder",
        priority: 358,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const sessionId = resolveSessionId((payload ?? {}));
                if (sessionId) {
                    sessionModeState.delete(sessionId);
                }
                return;
            }
            if (type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            if (typeof eventPayload.output?.output !== "string") {
                return;
            }
            const output = eventPayload.output.output;
            if (output.includes(MODE_REMINDER_MARKER)) {
                return;
            }
            const mode = detectMode(output);
            if (!mode) {
                return;
            }
            const sessionId = resolveSessionId(eventPayload);
            if (sessionId && sessionModeState.get(sessionId) === mode) {
                return;
            }
            eventPayload.output.output = `${output}\n\n${mode === BUILD_MODE ? BUILD_MODE_HINT : PLAN_MODE_HINT}`;
            if (sessionId) {
                sessionModeState.set(sessionId, mode);
            }
        },
    };
}
