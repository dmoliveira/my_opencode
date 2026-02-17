const MAX_STEP_RECOVERY_MARKER = "[max-step EXHAUSTION RECOVERY]";
const MAX_STEP_PATTERNS = [
    /critical\s*-\s*maximum\s*steps\s*reached/i,
    /tools?\s+are\s+disabled\s+until\s+next\s+user\s+input/i,
];
const MAX_STEP_RECOVERY_HINT = [
    MAX_STEP_RECOVERY_MARKER,
    "Maximum-step exhaustion was detected.",
    "- Summarize completed work in concise bullets",
    "- List remaining tasks that are still pending",
    "- State one concrete next action to continue safely",
].join("\n");
function hasMaxStepExhaustion(output) {
    return MAX_STEP_PATTERNS.every((pattern) => pattern.test(output));
}
export function createMaxStepRecoveryHook(options) {
    return {
        id: "max-step-recovery",
        priority: 354,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            if (typeof eventPayload.output?.output !== "string") {
                return;
            }
            const output = eventPayload.output.output;
            if (!hasMaxStepExhaustion(output) || output.includes(MAX_STEP_RECOVERY_MARKER)) {
                return;
            }
            eventPayload.output.output = `${output}\n\n${MAX_STEP_RECOVERY_HINT}`;
        },
    };
}
