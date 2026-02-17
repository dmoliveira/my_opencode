const EDIT_ERROR_PATTERNS = [
    /no matching lines/i,
    /failed to apply/i,
    /invalid patch/i,
    /file .* not found/i,
    /unable to edit/i,
];
const EDIT_RECOVERY_HINT = [
    "[edit ERROR RECOVERY]",
    "The edit attempt failed.",
    "- Re-read the target file section before retrying",
    "- Verify exact line context and patch anchors",
    "- Retry with a smaller, focused edit",
].join("\n");
function hasEditError(output) {
    return EDIT_ERROR_PATTERNS.some((pattern) => pattern.test(output));
}
export function createEditErrorRecoveryHook(options) {
    return {
        id: "edit-error-recovery",
        priority: 355,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
            if (tool !== "edit") {
                return;
            }
            if (typeof eventPayload.output?.output !== "string") {
                return;
            }
            const output = eventPayload.output.output;
            if (!hasEditError(output) || output.includes("[edit ERROR RECOVERY]")) {
                return;
            }
            eventPayload.output.output = `${output}\n\n${EDIT_RECOVERY_HINT}`;
        },
    };
}
