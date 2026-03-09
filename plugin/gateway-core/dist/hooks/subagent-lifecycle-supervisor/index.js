import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { annotateDelegationMetadata, extractDelegationChildRunId, extractDelegationTraceId, resolveDelegationTraceId, } from "../shared/delegation-trace.js";
function lifecycleKey(sid, childRunId) {
    return `${sid}:${childRunId}`;
}
function sessionId(payload) {
    return String(payload.input?.sessionID ?? payload.input?.sessionId ?? payload.properties?.info?.id ?? "").trim();
}
function effectiveDirectory(payload, fallbackDirectory) {
    return typeof payload.directory === "string" && payload.directory.trim() ? payload.directory : fallbackDirectory;
}
function nowMs() {
    return Date.now();
}
function isFailureOutput(output) {
    const trimmed = output.trim();
    if (!trimmed) {
        return false;
    }
    return /(^\[error\]|^error:|^exception:|^traceback\b|invalid arguments|unknown\s+agent|unknown\s+category|blocked delegation)/im.test(trimmed);
}
export function createSubagentLifecycleSupervisorHook(options) {
    const byDelegation = new Map();
    function resolveLifecycleState(eventPayload) {
        const sid = sessionId(eventPayload);
        if (!sid) {
            return null;
        }
        const childRunId = extractDelegationChildRunId(eventPayload.output?.metadata);
        if (!childRunId) {
            return {
                sid,
                activeKey: "",
                state: undefined,
                resolution: eventPayload.output ? "missing_identity" : "none",
            };
        }
        const activeKey = lifecycleKey(sid, childRunId);
        const state = byDelegation.get(activeKey);
        return { sid, activeKey, state, resolution: state ? "direct" : "none" };
    }
    return {
        id: "subagent-lifecycle-supervisor",
        priority: 295,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const sid = sessionId((payload ?? {}));
                if (sid) {
                    for (const key of byDelegation.keys()) {
                        if (key === sid || key.startsWith(`${sid}:`)) {
                            byDelegation.delete(key);
                        }
                    }
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
                const subagentType = String(eventPayload.output?.args?.subagent_type ?? "").toLowerCase().trim();
                if (!subagentType) {
                    return;
                }
                const traceId = resolveDelegationTraceId(eventPayload.output?.args ?? {});
                annotateDelegationMetadata(eventPayload.output ?? {}, eventPayload.output?.args);
                const childRunId = extractDelegationChildRunId(eventPayload.output?.metadata);
                if (!childRunId) {
                    return;
                }
                const key = lifecycleKey(sid, childRunId);
                const directory = effectiveDirectory(eventPayload, options.directory);
                const existing = byDelegation.get(key);
                const now = nowMs();
                if (existing && existing.status === "running" && now - existing.lastStartedAt < options.staleRunningMs) {
                    writeGatewayEventAudit(directory, {
                        hook: "subagent-lifecycle-supervisor",
                        stage: "guard",
                        reason_code: "subagent_lifecycle_duplicate_running_blocked",
                        session_id: sid,
                        child_run_id: childRunId || undefined,
                        trace_id: traceId || undefined,
                        subagent_type: subagentType,
                    });
                    throw new Error(`Blocked delegation: subagent session ${sid} is already running for ${existing.subagentType}. Wait for completion or stale timeout.`);
                }
                if (options.blockOnExhausted &&
                    existing &&
                    existing.status === "failed" &&
                    existing.failureCount >= options.maxRetriesPerSession) {
                    writeGatewayEventAudit(directory, {
                        hook: "subagent-lifecycle-supervisor",
                        stage: "guard",
                        reason_code: "subagent_lifecycle_retry_exhausted_blocked",
                        session_id: sid,
                        child_run_id: childRunId || undefined,
                        trace_id: traceId || undefined,
                        subagent_type: subagentType,
                        failure_count: String(existing.failureCount),
                    });
                    throw new Error(`Blocked delegation: retry budget exhausted for session ${sid} (${existing.failureCount}/${options.maxRetriesPerSession}).`);
                }
                const nextFailureCount = existing?.status === "failed" ? existing.failureCount : 0;
                byDelegation.set(key, {
                    childRunId,
                    traceId: traceId || undefined,
                    subagentType,
                    status: "running",
                    failureCount: nextFailureCount,
                    lastStartedAt: now,
                    lastUpdatedAt: now,
                    lastReasonCode: "subagent_lifecycle_started",
                });
                writeGatewayEventAudit(directory, {
                    hook: "subagent-lifecycle-supervisor",
                    stage: "state",
                    reason_code: "subagent_lifecycle_started",
                    session_id: sid,
                    child_run_id: childRunId || undefined,
                    trace_id: traceId || undefined,
                    subagent_type: subagentType,
                    failure_count: String(nextFailureCount),
                });
                return;
            }
            if (type === "tool.execute.before.error") {
                const eventPayload = (payload ?? {});
                if (String(eventPayload.input?.tool ?? "").toLowerCase().trim() !== "task") {
                    return;
                }
                const directory = effectiveDirectory(eventPayload, options.directory);
                const resolved = resolveLifecycleState(eventPayload);
                if (resolved?.resolution === "missing_identity") {
                    writeGatewayEventAudit(directory, {
                        hook: "subagent-lifecycle-supervisor",
                        stage: "skip",
                        reason_code: "subagent_lifecycle_before_error_missing_identity",
                        session_id: resolved.sid,
                    });
                }
                if (!resolved?.state) {
                    return;
                }
                byDelegation.delete(resolved.activeKey);
                writeGatewayEventAudit(directory, {
                    hook: "subagent-lifecycle-supervisor",
                    stage: "state",
                    reason_code: "subagent_lifecycle_before_error_released",
                    session_id: resolved.sid,
                    subagent_type: resolved.state.subagentType,
                    trace_id: resolved.state.traceId,
                    child_run_id: resolved.state.childRunId,
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
            const directory = effectiveDirectory(eventPayload, options.directory);
            const resolved = resolveLifecycleState(eventPayload);
            if (resolved?.resolution === "missing_identity") {
                writeGatewayEventAudit(directory, {
                    hook: "subagent-lifecycle-supervisor",
                    stage: "skip",
                    reason_code: "subagent_lifecycle_after_missing_identity",
                    session_id: resolved.sid,
                });
            }
            if (!resolved) {
                return;
            }
            const sid = resolved.sid;
            const traceId = extractDelegationTraceId(eventPayload.output?.args, eventPayload.output?.metadata);
            const childRunId = extractDelegationChildRunId(eventPayload.output?.metadata);
            let activeKey = resolved.activeKey;
            let state = resolved.state;
            if (!state) {
                return;
            }
            const outputText = typeof eventPayload.output?.output === "string" ? eventPayload.output.output : "";
            if (isFailureOutput(outputText)) {
                const failedCount = state.failureCount + 1;
                byDelegation.set(activeKey, {
                    ...state,
                    status: "failed",
                    failureCount: failedCount,
                    lastUpdatedAt: nowMs(),
                    lastReasonCode: "subagent_lifecycle_failed",
                });
                writeGatewayEventAudit(directory, {
                    hook: "subagent-lifecycle-supervisor",
                    stage: "state",
                    reason_code: "subagent_lifecycle_failed",
                    session_id: sid,
                    child_run_id: childRunId || undefined,
                    trace_id: traceId || undefined,
                    subagent_type: state.subagentType,
                    failure_count: String(failedCount),
                });
                if (typeof eventPayload.output?.output === "string") {
                    eventPayload.output.output += `\n[subagent-lifecycle-supervisor] state=failed retries=${failedCount}/${options.maxRetriesPerSession}`;
                }
                return;
            }
            byDelegation.set(activeKey, {
                ...state,
                status: "completed",
                lastUpdatedAt: nowMs(),
                lastReasonCode: "subagent_lifecycle_completed",
            });
            writeGatewayEventAudit(directory, {
                hook: "subagent-lifecycle-supervisor",
                stage: "state",
                reason_code: "subagent_lifecycle_completed",
                session_id: sid,
                child_run_id: childRunId || undefined,
                trace_id: traceId || undefined,
                subagent_type: state.subagentType,
                failure_count: String(state.failureCount),
            });
            byDelegation.delete(activeKey);
        },
    };
}
