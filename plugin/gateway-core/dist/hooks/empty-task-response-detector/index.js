// Creates detector hook for empty task outputs and appends remediation guidance.
export function createEmptyTaskResponseDetectorHook(options) {
    return {
        id: "empty-task-response-detector",
        priority: 350,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
            if (tool !== "task") {
                return;
            }
            if (typeof eventPayload.output?.output !== "string") {
                return;
            }
            if (eventPayload.output.output.trim().length > 0) {
                return;
            }
            eventPayload.output.output =
                "[task WARNING] Empty task output detected. Retry with clearer task instructions or inspect task logs before continuing.";
        },
    };
}
