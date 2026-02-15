// Truncates option label when it exceeds configured maximum length.
function truncateLabel(value, maxLength) {
    if (value.length <= maxLength) {
        return value;
    }
    return `${value.slice(0, Math.max(1, maxLength - 3))}...`;
}
// Creates hook that truncates overly long question option labels.
export function createQuestionLabelTruncatorHook(options) {
    const maxLength = options.maxLength >= 8 ? options.maxLength : 30;
    return {
        id: "question-label-truncator",
        priority: 380,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.before") {
                return;
            }
            const eventPayload = (payload ?? {});
            const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
            if (tool !== "question") {
                return;
            }
            const questions = eventPayload.output?.args?.questions;
            if (!Array.isArray(questions)) {
                return;
            }
            for (const question of questions) {
                if (!Array.isArray(question.options)) {
                    continue;
                }
                for (const option of question.options) {
                    if (typeof option.label !== "string") {
                        continue;
                    }
                    option.label = truncateLabel(option.label, maxLength);
                }
            }
        },
    };
}
