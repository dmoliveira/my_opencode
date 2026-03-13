import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { readToolAfterOutputText } from "../shared/tool-after-output.js";
import { clearDelegationChildSessionLink, getDelegationChildSessionLink, registerDelegationChildSession, } from "../shared/delegation-child-session.js";
import { clearActiveDelegation, clearDelegationSession, configureDelegationRuntimeState, registerDelegationOutcome, registerDelegationStart, } from "../shared/delegation-runtime-state.js";
import { annotateDelegationMetadata, extractDelegationChildRunId, resolveDelegationTraceId, } from "../shared/delegation-trace.js";
function sessionId(payload) {
    return String(payload.input?.sessionID ??
        payload.input?.sessionId ??
        payload.properties?.sessionID ??
        payload.properties?.sessionId ??
        payload.properties?.info?.id ??
        "").trim();
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
            if (type === "session.created" || type === "session.updated") {
                registerDelegationChildSession((payload ?? {}));
                return;
            }
            if (type === "session.idle") {
                const childSessionId = sessionId((payload ?? {}));
                const link = getDelegationChildSessionLink(childSessionId);
                if (!link) {
                    return;
                }
                const record = registerDelegationOutcome({
                    sessionId: link.parentSessionId,
                    status: "completed",
                    reasonCode: "subagent_telemetry_child_idle_reconciled",
                    endedAt: Date.now(),
                    childRunId: link.childRunId || undefined,
                }, options.maxTimelineEntries);
                if (!record) {
                    return;
                }
                clearDelegationChildSessionLink(childSessionId);
                writeGatewayEventAudit(options.directory, {
                    hook: "subagent-telemetry-timeline",
                    stage: "state",
                    reason_code: record.reasonCode,
                    session_id: record.sessionId,
                    child_run_id: record.childRunId,
                    subagent_type: record.subagentType || undefined,
                    category: record.category,
                    duration_ms: String(record.durationMs),
                    status: record.status,
                    trace_id: record.traceId,
                });
                return;
            }
            if (type === "message.updated") {
                const eventPayload = (payload ?? {});
                const info = eventPayload.properties?.info;
                if (String(info?.role ?? "").toLowerCase().trim() !== "assistant") {
                    return;
                }
                const childSessionId = String(info?.sessionID ?? info?.sessionId ?? "").trim();
                const link = getDelegationChildSessionLink(childSessionId);
                if (!link) {
                    return;
                }
                const completed = Number.isFinite(Number(info?.time?.completed ?? NaN));
                const failed = info?.error !== undefined && info?.error !== null;
                if (!completed && !failed) {
                    return;
                }
                const record = registerDelegationOutcome({
                    sessionId: link.parentSessionId,
                    status: failed ? "failed" : "completed",
                    reasonCode: failed
                        ? "subagent_telemetry_child_message_failed_reconciled"
                        : "subagent_telemetry_child_message_completed_reconciled",
                    endedAt: Date.now(),
                    childRunId: link.childRunId || undefined,
                }, options.maxTimelineEntries);
                if (!record) {
                    return;
                }
                clearDelegationChildSessionLink(childSessionId);
                const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                    ? eventPayload.directory
                    : options.directory;
                writeGatewayEventAudit(directory, {
                    hook: "subagent-telemetry-timeline",
                    stage: "state",
                    reason_code: record.reasonCode,
                    session_id: record.sessionId,
                    child_run_id: record.childRunId,
                    subagent_type: record.subagentType || undefined,
                    category: record.category,
                    duration_ms: String(record.durationMs),
                    status: record.status,
                    trace_id: record.traceId,
                });
                return;
            }
            if (type === "session.deleted") {
                const sid = sessionId((payload ?? {}));
                if (sid) {
                    const childLink = clearDelegationChildSessionLink(sid);
                    if (childLink) {
                        const record = registerDelegationOutcome({
                            sessionId: childLink.parentSessionId,
                            status: "completed",
                            reasonCode: "subagent_telemetry_child_deleted_reconciled",
                            endedAt: Date.now(),
                            childRunId: childLink.childRunId || undefined,
                        }, options.maxTimelineEntries);
                        if (record) {
                            writeGatewayEventAudit(options.directory, {
                                hook: "subagent-telemetry-timeline",
                                stage: "state",
                                reason_code: record.reasonCode,
                                session_id: record.sessionId,
                                child_run_id: record.childRunId,
                                subagent_type: record.subagentType || undefined,
                                category: record.category,
                                duration_ms: String(record.durationMs),
                                status: record.status,
                                trace_id: record.traceId,
                            });
                        }
                    }
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
                annotateDelegationMetadata(eventPayload.output ?? {}, args);
                const childRunId = extractDelegationChildRunId(eventPayload.output?.metadata);
                const subagentType = String(args?.subagent_type ?? "").toLowerCase().trim();
                const category = String(args?.category ?? "balanced").toLowerCase().trim() || "balanced";
                if (!subagentType && !category) {
                    return;
                }
                registerDelegationStart({
                    sessionId: sid,
                    childRunId: childRunId || undefined,
                    subagentType,
                    category,
                    startedAt: Date.now(),
                    traceId,
                });
                return;
            }
            if (type === "tool.execute.before.error") {
                const eventPayload = (payload ?? {});
                if (String(eventPayload.input?.tool ?? "").toLowerCase().trim() !== "task") {
                    return;
                }
                const sid = sessionId(eventPayload);
                if (!sid) {
                    return;
                }
                clearActiveDelegation({
                    sessionId: sid,
                    childRunId: extractDelegationChildRunId(eventPayload.output?.metadata) || undefined,
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
            const output = readToolAfterOutputText(eventPayload.output?.output);
            const failed = isFailureOutput(output);
            const childRunId = extractDelegationChildRunId(eventPayload.output?.metadata);
            const record = registerDelegationOutcome({
                sessionId: sid,
                status: failed ? "failed" : "completed",
                reasonCode: failed
                    ? "subagent_telemetry_failed"
                    : "subagent_telemetry_completed",
                endedAt: Date.now(),
                childRunId: childRunId || undefined,
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
                child_run_id: record.childRunId,
                subagent_type: record.subagentType || undefined,
                category: record.category,
                duration_ms: String(record.durationMs),
                status: record.status,
                trace_id: record.traceId,
            });
        },
    };
}
