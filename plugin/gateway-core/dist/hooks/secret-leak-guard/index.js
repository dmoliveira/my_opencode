import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { createSecretRedactor, } from "../shared/secret-redaction.js";
function mergeStats(target, source) {
    target.matches += source.matches;
    target.redactedFields += source.redactedFields;
    target.scannedChars += source.scannedChars;
    target.scannedNodes += source.scannedNodes;
}
// Creates secret leak guard hook that redacts likely secrets from every tool output channel.
export function createSecretLeakGuardHook(options) {
    const redactor = createSecretRedactor(options);
    return {
        id: "secret-leak-guard",
        priority: 395,
        events: ["tool.execute.after"],
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            const mutableOutput = eventPayload.output;
            if (!mutableOutput) {
                return;
            }
            const rawOutput = mutableOutput.output;
            const stats = {
                matches: 0,
                redactedFields: 0,
                scannedChars: 0,
                scannedNodes: 0,
            };
            const outputShape = typeof rawOutput === "string" ? "string" : "structured";
            if (typeof rawOutput === "string") {
                const result = redactor.redactText(rawOutput);
                mergeStats(stats, result.stats);
                if (result.text !== rawOutput) {
                    mutableOutput.output = result.text;
                }
            }
            else if (rawOutput && typeof rawOutput === "object") {
                mergeStats(stats, redactor.redactMutableValue(rawOutput));
            }
            else {
                return;
            }
            if (stats.matches === 0) {
                return;
            }
            const directory = eventPayload.directory?.trim() || options.directory;
            const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "");
            writeGatewayEventAudit(directory, {
                hook: "secret-leak-guard",
                stage: "state",
                reason_code: "secret_output_redacted",
                session_id: sessionId,
                match_count: stats.matches,
                redacted_field_count: stats.redactedFields,
                scanned_chars: stats.scannedChars,
                output_shape: outputShape,
            });
        },
    };
}
