const LOW_VALUE_COMMENT_PATTERNS = [/this function/i, /this method/i, /simply/i, /just does/i];
// Creates hook that flags low-value comments in write/edit outputs.
export function createCommentCheckerHook(options) {
    return {
        id: "comment-checker",
        priority: 360,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
            if (tool !== "write" && tool !== "edit") {
                return;
            }
            if (typeof eventPayload.output?.output !== "string") {
                return;
            }
            const outputText = eventPayload.output.output;
            const hasCommentLine = /(^|\n)\s*(\/\/|#|\/\*)/.test(outputText);
            if (!hasCommentLine) {
                return;
            }
            const lowValue = LOW_VALUE_COMMENT_PATTERNS.some((pattern) => pattern.test(outputText));
            if (!lowValue) {
                return;
            }
            eventPayload.output.output +=
                "\n\n[comment-checker] Potential low-value comment detected. Prefer comments that explain non-obvious intent or constraints.";
        },
    };
}
