import { createHash } from "node:crypto";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { extractDelegationTraceId, resolveDelegationTraceId, } from "../shared/delegation-trace.js";
function fallbackDelegationKey(sid, args) {
    const subagentType = String(args?.subagent_type ?? "").toLowerCase().trim();
    const category = String(args?.category ?? "").toLowerCase().trim();
    const prompt = String(args?.prompt ?? "").trim();
    const description = String(args?.description ?? "").trim();
    const fingerprintSource = [subagentType, category, prompt, description]
        .filter(Boolean)
        .join("\n");
    if (fingerprintSource) {
        const fingerprint = createHash("sha1").update(fingerprintSource).digest("hex").slice(0, 12);
        return `${sid}:fp:${fingerprint}`;
    }
    return `${sid}:agent:${subagentType || "unknown"}`;
}
function lifecycleKey(sid, traceId, args) {
    return traceId ? `${sid}:${traceId}` : fallbackDelegationKey(sid, args);
}
function sessionId(payload) {
    return String(payload.input?.sessionID ?? payload.input?.sessionId ?? payload.properties?.info?.id ?? "").trim();
}
function nowMs() {
    return Date.now();
}
function sessionLifecycleKeys(byDelegation, sid) {
    const matches = [];
    for (const key of byDelegation.keys()) {
        if (key === sid || key.startsWith(`${sid}:`)) {
            matches.push(key);
        }
    }
    return matches;
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
                const key = lifecycleKey(sid, traceId, eventPayload.output?.args);
                const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                    ? eventPayload.directory
                    : options.directory;
                const existing = byDelegation.get(key);
                const now = nowMs();
                if (existing && existing.status === "running" && now - existing.lastStartedAt < options.staleRunningMs) {
                    writeGatewayEventAudit(directory, {
                        hook: "subagent-lifecycle-supervisor",
                        stage: "guard",
                        reason_code: "subagent_lifecycle_duplicate_running_blocked",
                        session_id: sid,
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
                        trace_id: traceId || undefined,
                        subagent_type: subagentType,
                        failure_count: String(existing.failureCount),
                    });
                    throw new Error(`Blocked delegation: retry budget exhausted for session ${sid} (${existing.failureCount}/${options.maxRetriesPerSession}).`);
                }
                const nextFailureCount = existing?.status === "failed" ? existing.failureCount : 0;
                byDelegation.set(key, {
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
                    trace_id: traceId || undefined,
                    subagent_type: subagentType,
                    failure_count: String(nextFailureCount),
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
            const traceId = extractDelegationTraceId(eventPayload.output?.args);
            const key = lifecycleKey(sid, traceId, eventPayload.output?.args);
            let activeKey = key;
            let state = byDelegation.get(activeKey);
            if (!state) {
                if (!traceId) {
                    const matches = sessionLifecycleKeys(byDelegation, sid);
                    if (matches.length === 1) {
                        activeKey = matches[0];
                        state = byDelegation.get(activeKey);
                    }
                    else if (matches.length > 1) {
                        writeGatewayEventAudit(options.directory, {
                            hook: "subagent-lifecycle-supervisor",
                            stage: "skip",
                            reason_code: "subagent_lifecycle_after_ambiguous_skip",
                            session_id: sid,
                            concurrent_total: String(matches.length),
                        });
                        if (typeof eventPayload.output?.output === "string") {
                            eventPayload.output.output +=
                                "\n[subagent-lifecycle-supervisor] ambiguous trace-less completion observed; running state preserved until an exact delegation match arrives or stale timeout expires.";
                        }
                        return;
                    }
                }
            }
            if (!state) {
                return;
            }
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
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
                trace_id: traceId || undefined,
                subagent_type: state.subagentType,
                failure_count: String(state.failureCount),
            });
            byDelegation.delete(activeKey);
        },
    };
}
