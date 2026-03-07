import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { clearDelegationSession, configureDelegationRuntimeState, registerDelegationOutcome, registerDelegationStart, } from "../shared/delegation-runtime-state.js";
import { resolveDelegationTraceId } from "../shared/delegation-trace.js";
function sessionId(payload) {
    return String(payload.input?.sessionID ?? payload.input?.sessionId ?? payload.properties?.info?.id ?? "").trim();
}
function isFailureOutput(output) {
    return /(\[error\]|invalid arguments|failed|exception|traceback|unknown\s+agent|unknown\s+category|blocked delegation)/i.test(output);
}
export function createSubagentTelemetryTimelineHook(options) {
    configureDelegationRuntimeState({
        directory: options.directory,
        persistState: options.persistState,
        stateFile: options.stateFile,
        stateMaxEntries: options.stateMaxEntries,
    });
    return {
        id: "subagent-telemetry-timeline",
        priority: 296,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const sid = sessionId((payload ?? {}));
                if (sid) {
                    clearDelegationSession(sid);
                }
                return;
            }
            if (type === "tool.execute.before") {
                const eventPayload = (payload ?? {});
                if (String(eventPayload.input?.tool ?? "").toLowerCase().trim() !== "task") {
                    return;
                }
                const sid = sessionId(eventPayload);
                if (!sid) {
                    return;
                }
                const args = eventPayload.output?.args;
                const traceId = resolveDelegationTraceId(args ?? {});
                const subagentType = String(args?.subagent_type ?? "").toLowerCase().trim();
                const category = String(args?.category ?? "balanced").toLowerCase().trim() || "balanced";
                if (!subagentType && !category) {
                    return;
                }
                registerDelegationStart({
                    sessionId: sid,
                    subagentType,
                    category,
                    startedAt: Date.now(),
                    traceId,
                });
                return;
            }
            if (type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            if (String(eventPayload.input?.tool ?? "").toLowerCase().trim() !== "task") {
                return;
            }
            const sid = sessionId(eventPayload);
            if (!sid) {
                return;
            }
            const output = typeof eventPayload.output?.output === "string" ? eventPayload.output.output : "";
            const failed = isFailureOutput(output);
            const record = registerDelegationOutcome({
                sessionId: sid,
                status: failed ? "failed" : "completed",
                reasonCode: failed
                    ? "subagent_telemetry_failed"
                    : "subagent_telemetry_completed",
                endedAt: Date.now(),
            }, options.maxTimelineEntries);
            if (!record) {
                return;
            }
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            writeGatewayEventAudit(directory, {
                hook: "subagent-telemetry-timeline",
                stage: "state",
                reason_code: record.reasonCode,
                session_id: record.sessionId,
                subagent_type: record.subagentType || undefined,
                category: record.category,
                duration_ms: String(record.durationMs),
                status: record.status,
                trace_id: record.traceId,
            });
        },
    };
}
