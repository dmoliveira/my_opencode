import { sanitizeGatewayAuditText, writeGatewayEventAudit, } from "../../audit/event-audit.js";
import { describeHookFailure, isCriticalGatewayHookId, isIntentionalHookBlock, normalizeHookError, surfaceGatewayHookFailure, } from "./hook-failure.js";
function startLatency(recorder) {
    try {
        return recorder?.start() ?? null;
    }
    catch {
        return null;
    }
}
function captureLatency(recorder, startedAt) {
    try {
        return recorder?.capture(startedAt) ?? null;
    }
    catch {
        return null;
    }
}
function recordLatency(recorder, input) {
    try {
        recorder?.record(input);
    }
    catch {
        // Instrumentation is isolated from hook behavior.
    }
}
export async function dispatchGatewayHookEvent(input) {
    const startedAt = input.latency ? startLatency(input.latency) : null;
    try {
        await input.hook.event(input.eventType, input.payload);
        if (input.latency) {
            recordLatency(input.latency, {
                hookId: input.hook.id,
                eventType: input.eventType,
                outcome: "success",
                measurement: captureLatency(input.latency, startedAt),
            });
        }
        return {
            ok: true,
            critical: isCriticalGatewayHookId(input.hook.id),
            blocked: false,
        };
    }
    catch (error) {
        const measurement = input.latency
            ? captureLatency(input.latency, startedAt)
            : null;
        const critical = isCriticalGatewayHookId(input.hook.id);
        const blocked = isIntentionalHookBlock(error);
        if (input.latency) {
            recordLatency(input.latency, {
                hookId: input.hook.id,
                eventType: input.eventType,
                outcome: blocked ? "blocked" : "failure",
                measurement,
            });
        }
        const failure = sanitizeGatewayAuditText(describeHookFailure(error));
        try {
            writeGatewayEventAudit(input.directory, {
                hook: input.hook.id,
                stage: "dispatch",
                reason_code: blocked
                    ? "hook_execution_blocked"
                    : critical
                        ? "critical_hook_execution_failed"
                        : "hook_execution_failed",
                event_type: input.eventType,
                critical,
                blocked,
                error_message: failure,
            });
        }
        catch {
            // Audit isolation is defense-in-depth; hook outcomes remain authoritative.
        }
        if (!blocked) {
            surfaceGatewayHookFailure(`${critical ? "critical " : ""}hook ${input.hook.id} failed during ${input.eventType}: ${failure}`);
        }
        return {
            ok: false,
            critical,
            blocked,
            error: normalizeHookError(error, `hook ${input.hook.id} failed during ${input.eventType}: ${failure}`),
        };
    }
}
