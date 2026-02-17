const MARKER = "[plan HANDOFF REMINDER]";
const PLAN_ENTER_PATTERNS = [/switch(?:ing)?\s+to\s+plan agent/i, /benefit from planning first/i];
const PLAN_EXIT_PATTERNS = [/completed the planning phase/i, /switch to build agent/i];
const PLAN_ENTER_HINT = [
    MARKER,
    "Plan-enter handoff reminder detected.",
    "- Draft the plan before implementation changes",
    "- Keep execution actions paused until plan is finalized",
].join("\n");
const PLAN_EXIT_HINT = [
    MARKER,
    "Plan-exit handoff reminder detected.",
    "- Move from planning to implementation now",
    "- Execute checks before declaring completion",
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
    if (PLAN_ENTER_PATTERNS.every((pattern) => pattern.test(output))) {
        return "plan_enter";
    }
    if (PLAN_EXIT_PATTERNS.every((pattern) => pattern.test(output))) {
        return "plan_exit";
    }
    return null;
}
export function createPlanHandoffReminderHook(options) {
    const lastModeBySession = new Map();
    return {
        id: "plan-handoff-reminder",
        priority: 357,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const sessionId = resolveSessionId((payload ?? {}));
                if (sessionId) {
                    lastModeBySession.delete(sessionId);
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
            if (output.includes(MARKER)) {
                return;
            }
            const mode = detectMode(output);
            if (!mode) {
                return;
            }
            const sessionId = resolveSessionId(eventPayload);
            if (sessionId && lastModeBySession.get(sessionId) === mode) {
                return;
            }
            eventPayload.output.output = `${output}\n\n${mode === "plan_enter" ? PLAN_ENTER_HINT : PLAN_EXIT_HINT}`;
            if (sessionId) {
                lastModeBySession.set(sessionId, mode);
            }
        },
    };
}
