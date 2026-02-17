const JSON_ERROR_PATTERNS = [
    /json parse error/i,
    /unexpected token .*json/i,
    /invalid json/i,
    /failed to parse json/i,
];
const JSON_RECOVERY_HINT = [
    "[json ERROR RECOVERY]",
    "JSON parsing failed.",
    "- Re-run the command with strict JSON mode flags when available",
    "- Validate output before parsing and handle non-JSON fallback paths",
    "- Retry with narrower command scope to reduce noisy output",
].join("\n");
function hasJsonError(output) {
    return JSON_ERROR_PATTERNS.some((pattern) => pattern.test(output));
}
export function createJsonErrorRecoveryHook(options) {
    return {
        id: "json-error-recovery",
        priority: 356,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            if (typeof eventPayload.output?.output !== "string") {
                return;
            }
            const output = eventPayload.output.output;
            if (!hasJsonError(output) || output.includes("[json ERROR RECOVERY]")) {
                return;
            }
            eventPayload.output.output = `${output}\n\n${JSON_RECOVERY_HINT}`;
        },
    };
}
