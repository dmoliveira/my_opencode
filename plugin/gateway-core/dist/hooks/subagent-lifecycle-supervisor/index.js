import { createHash } from "node:crypto";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { injectHookMessage, inspectHookMessageSafety } from "../hook-message-injector/index.js";
import { clearDelegationChildSessionLink, getDelegationChildSessionLink, registerDelegationChildSession, } from "../shared/delegation-child-session.js";
import { annotateDelegationMetadata, extractDelegationChildRunId, extractDelegationSubagentType, extractDelegationSubagentTypeFromOutput, extractDelegationTraceId, resolveDelegationTraceId, } from "../shared/delegation-trace.js";
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
function lifecycleKey(sid, childRunId, traceId, args) {
    if (childRunId) {
        return `${sid}:${childRunId}`;
    }
    return traceId ? `${sid}:${traceId}` : fallbackDelegationKey(sid, args);
}
function sessionId(payload) {
    return String(payload.input?.sessionID ??
        payload.input?.sessionId ??
        payload.properties?.sessionID ??
        payload.properties?.sessionId ??
        payload.properties?.info?.id ??
        "").trim();
}
function effectiveDirectory(payload, fallbackDirectory) {
    return typeof payload.directory === "string" && payload.directory.trim() ? payload.directory : fallbackDirectory;
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
function matchingSessionLifecycleKeys(byDelegation, sid, subagentType) {
    const matches = [];
    for (const [key, value] of byDelegation.entries()) {
        if ((key === sid || key.startsWith(`${sid}:`)) && value.subagentType === subagentType) {
            matches.push(key);
        }
    }
    return matches;
}
function matchingSessionTraceLifecycleKeys(byDelegation, sid, traceId) {
    const matches = [];
    for (const [key, value] of byDelegation.entries()) {
        if ((key === sid || key.startsWith(`${sid}:`)) && value.traceId === traceId) {
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
    async function injectParentRecoveryMessage(args) {
        const client = options.client?.session;
        if (!client) {
            writeGatewayEventAudit(args.directory, {
                hook: "subagent-lifecycle-supervisor",
                stage: "skip",
                reason_code: `${args.reasonCode}_session_client_unavailable`,
                session_id: args.parentSessionId,
            });
            return false;
        }
        const safety = await inspectHookMessageSafety({
            session: client,
            sessionId: args.parentSessionId,
            directory: args.directory,
        });
        if (!safety.safe && safety.reason !== "assistant_turn_incomplete") {
            writeGatewayEventAudit(args.directory, {
                hook: "subagent-lifecycle-supervisor",
                stage: "skip",
                reason_code: `${args.reasonCode}_${safety.reason}`,
                session_id: args.parentSessionId,
            });
            return false;
        }
        if (!safety.safe && safety.reason === "assistant_turn_incomplete") {
            writeGatewayEventAudit(args.directory, {
                hook: "subagent-lifecycle-supervisor",
                stage: "state",
                reason_code: `${args.reasonCode}_forcing_incomplete_parent_recovery`,
                session_id: args.parentSessionId,
            });
        }
        const injected = await injectHookMessage({
            session: client,
            sessionId: args.parentSessionId,
            directory: args.directory,
            content: args.subagentType
                ? `[delegated ${args.subagentType} child stalled - continuing in parent turn]\nchild_session: ${args.childSessionId}`
                : `[delegated child stalled - continuing in parent turn]\nchild_session: ${args.childSessionId}`,
        });
        writeGatewayEventAudit(args.directory, {
            hook: "subagent-lifecycle-supervisor",
            stage: injected ? "state" : "skip",
            reason_code: injected ? `${args.reasonCode}_injected` : `${args.reasonCode}_inject_failed`,
            session_id: args.parentSessionId,
        });
        return injected;
    }
    function finalizeLinkedLifecycle(args) {
        const matches = args.childRunId
            ? [`${args.parentSessionId}:${args.childRunId}`].filter((key) => byDelegation.has(key))
            : args.traceId
                ? matchingSessionTraceLifecycleKeys(byDelegation, args.parentSessionId, args.traceId)
                : args.subagentType
                    ? matchingSessionLifecycleKeys(byDelegation, args.parentSessionId, args.subagentType)
                    : sessionLifecycleKeys(byDelegation, args.parentSessionId);
        if (matches.length !== 1) {
            return false;
        }
        const activeKey = matches[0];
        const state = byDelegation.get(activeKey);
        if (!state || state.status !== "running") {
            return false;
        }
        if (args.failed) {
            const failedCount = state.failureCount + 1;
            byDelegation.set(activeKey, {
                ...state,
                status: "failed",
                failureCount: failedCount,
                lastUpdatedAt: nowMs(),
                lastReasonCode: args.reasonCode,
            });
            writeGatewayEventAudit(args.directory, {
                hook: "subagent-lifecycle-supervisor",
                stage: "state",
                reason_code: args.reasonCode,
                session_id: args.parentSessionId,
                child_run_id: state.childRunId,
                trace_id: state.traceId,
                subagent_type: state.subagentType,
                failure_count: String(failedCount),
            });
            return true;
        }
        byDelegation.set(activeKey, {
            ...state,
            status: "completed",
            lastUpdatedAt: nowMs(),
            lastReasonCode: args.reasonCode,
        });
        writeGatewayEventAudit(args.directory, {
            hook: "subagent-lifecycle-supervisor",
            stage: "state",
            reason_code: args.reasonCode,
            session_id: args.parentSessionId,
            child_run_id: state.childRunId,
            trace_id: state.traceId,
            subagent_type: state.subagentType,
            failure_count: String(state.failureCount),
        });
        byDelegation.delete(activeKey);
        return true;
    }
    function resolveLifecycleState(eventPayload) {
        const sid = sessionId(eventPayload);
        if (!sid) {
            return null;
        }
        const traceId = extractDelegationTraceId(eventPayload.output?.args, eventPayload.output?.metadata);
        const childRunId = extractDelegationChildRunId(eventPayload.output?.metadata);
        const key = lifecycleKey(sid, childRunId, traceId, eventPayload.output?.args);
        let activeKey = key;
        let state = byDelegation.get(activeKey);
        if (!state && traceId) {
            const traceMatches = matchingSessionTraceLifecycleKeys(byDelegation, sid, traceId);
            if (traceMatches.length === 1) {
                activeKey = traceMatches[0];
                state = byDelegation.get(activeKey);
            }
            if (state) {
                return { sid, activeKey, state, resolution: "trace_fallback" };
            }
        }
        if (!state && !childRunId && !traceId) {
            const outputText = typeof eventPayload.output?.output === "string" ? eventPayload.output.output : "";
            const outputSubagentType = extractDelegationSubagentType(eventPayload.output?.args, eventPayload.output?.metadata) ||
                extractDelegationSubagentTypeFromOutput(outputText);
            const matches = outputSubagentType
                ? matchingSessionLifecycleKeys(byDelegation, sid, outputSubagentType)
                : sessionLifecycleKeys(byDelegation, sid);
            if (matches.length === 1) {
                activeKey = matches[0];
                state = byDelegation.get(activeKey);
            }
            if (state) {
                return { sid, activeKey, state, resolution: "subagent_fallback" };
            }
        }
        return { sid, activeKey, state, resolution: state ? "direct" : "none" };
    }
    function forceFinalizeMatches(args) {
        for (const activeKey of args.activeKeys) {
            const state = byDelegation.get(activeKey);
            if (!state) {
                continue;
            }
            if (args.failed) {
                const failureCount = state.failureCount + 1;
                byDelegation.set(activeKey, {
                    ...state,
                    status: "failed",
                    failureCount,
                    lastUpdatedAt: nowMs(),
                    lastReasonCode: args.reasonCode,
                });
                writeGatewayEventAudit(args.directory, {
                    hook: "subagent-lifecycle-supervisor",
                    stage: "state",
                    reason_code: args.reasonCode,
                    session_id: args.sid,
                    child_run_id: state.childRunId,
                    trace_id: state.traceId,
                    subagent_type: state.subagentType,
                    failure_count: String(failureCount),
                });
                continue;
            }
            byDelegation.set(activeKey, {
                ...state,
                status: "completed",
                lastUpdatedAt: nowMs(),
                lastReasonCode: args.reasonCode,
            });
            writeGatewayEventAudit(args.directory, {
                hook: "subagent-lifecycle-supervisor",
                stage: "state",
                reason_code: args.reasonCode,
                session_id: args.sid,
                child_run_id: state.childRunId,
                trace_id: state.traceId,
                subagent_type: state.subagentType,
                failure_count: String(state.failureCount),
            });
            byDelegation.delete(activeKey);
        }
    }
    return {
        id: "subagent-lifecycle-supervisor",
        priority: 295,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.created" || type === "session.updated") {
                const link = registerDelegationChildSession((payload ?? {}));
                if (link) {
                    const matches = link.childRunId
                        ? [`${link.parentSessionId}:${link.childRunId}`].filter((key) => byDelegation.has(key))
                        : link.traceId
                            ? matchingSessionTraceLifecycleKeys(byDelegation, link.parentSessionId, link.traceId)
                            : link.subagentType
                                ? matchingSessionLifecycleKeys(byDelegation, link.parentSessionId, link.subagentType)
                                : sessionLifecycleKeys(byDelegation, link.parentSessionId);
                    for (const key of matches) {
                        const state = byDelegation.get(key);
                        if (!state || state.status !== "running") {
                            continue;
                        }
                        byDelegation.set(key, {
                            ...state,
                            childSessionId: link.childSessionId,
                            lastUpdatedAt: nowMs(),
                            lastReasonCode: "subagent_lifecycle_child_session_linked",
                        });
                    }
                }
                return;
            }
            if (type === "session.idle") {
                const childSessionId = sessionId((payload ?? {}));
                const link = getDelegationChildSessionLink(childSessionId);
                if (!link) {
                    return;
                }
                const eventPayload = (payload ?? {});
                const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                    ? eventPayload.directory
                    : options.directory;
                const staleRecovered = finalizeLinkedLifecycle({
                    parentSessionId: link.parentSessionId,
                    childRunId: link.childRunId,
                    traceId: link.traceId,
                    subagentType: link.subagentType,
                    directory,
                    failed: true,
                    reasonCode: "subagent_lifecycle_child_idle_stale_recovered",
                });
                if (staleRecovered) {
                    await injectParentRecoveryMessage({
                        parentSessionId: link.parentSessionId,
                        directory,
                        childSessionId,
                        subagentType: link.subagentType,
                        reasonCode: "subagent_lifecycle_child_idle_stale_recovered",
                    });
                }
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
                    const matches = link.childRunId
                        ? [`${link.parentSessionId}:${link.childRunId}`].filter((key) => byDelegation.has(key))
                        : link.traceId
                            ? matchingSessionTraceLifecycleKeys(byDelegation, link.parentSessionId, link.traceId)
                            : link.subagentType
                                ? matchingSessionLifecycleKeys(byDelegation, link.parentSessionId, link.subagentType)
                                : sessionLifecycleKeys(byDelegation, link.parentSessionId);
                    for (const key of matches) {
                        const state = byDelegation.get(key);
                        if (!state || state.status !== "running") {
                            continue;
                        }
                        byDelegation.set(key, {
                            ...state,
                            childSessionId,
                            lastUpdatedAt: nowMs(),
                            lastReasonCode: "subagent_lifecycle_child_message_progress",
                        });
                    }
                    return;
                }
                const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                    ? eventPayload.directory
                    : options.directory;
                finalizeLinkedLifecycle({
                    parentSessionId: link.parentSessionId,
                    childRunId: link.childRunId,
                    traceId: link.traceId,
                    subagentType: link.subagentType,
                    directory,
                    failed,
                    reasonCode: failed
                        ? "subagent_lifecycle_child_message_failed_reconciled"
                        : "subagent_lifecycle_child_message_completed_reconciled",
                });
                return;
            }
            if (type === "session.deleted") {
                const sid = sessionId((payload ?? {}));
                if (sid) {
                    const childLink = clearDelegationChildSessionLink(sid);
                    if (childLink) {
                        finalizeLinkedLifecycle({
                            parentSessionId: childLink.parentSessionId,
                            childRunId: childLink.childRunId,
                            traceId: childLink.traceId,
                            subagentType: childLink.subagentType,
                            directory: options.directory,
                            failed: false,
                            reasonCode: "subagent_lifecycle_child_deleted_reconciled",
                        });
                    }
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
                const key = lifecycleKey(sid, childRunId, traceId, eventPayload.output?.args);
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
                    childSessionId: existing?.childSessionId,
                    childRunId: childRunId || undefined,
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
                if (!resolved?.state) {
                    return;
                }
                if (resolved.resolution === "trace_fallback" || resolved.resolution === "subagent_fallback") {
                    writeGatewayEventAudit(directory, {
                        hook: "subagent-lifecycle-supervisor",
                        stage: "state",
                        reason_code: resolved.resolution === "trace_fallback"
                            ? "subagent_lifecycle_trace_fallback_matched"
                            : "subagent_lifecycle_subagent_fallback_matched",
                        session_id: resolved.sid,
                        subagent_type: resolved.state.subagentType,
                        trace_id: resolved.state.traceId,
                        child_run_id: resolved.state.childRunId,
                    });
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
            if (!resolved) {
                return;
            }
            const sid = resolved.sid;
            const traceId = extractDelegationTraceId(eventPayload.output?.args, eventPayload.output?.metadata);
            const childRunId = extractDelegationChildRunId(eventPayload.output?.metadata);
            let activeKey = resolved.activeKey;
            let state = resolved.state;
            if (state && (resolved.resolution === "trace_fallback" || resolved.resolution === "subagent_fallback")) {
                writeGatewayEventAudit(directory, {
                    hook: "subagent-lifecycle-supervisor",
                    stage: "state",
                    reason_code: resolved.resolution === "trace_fallback"
                        ? "subagent_lifecycle_trace_fallback_matched"
                        : "subagent_lifecycle_subagent_fallback_matched",
                    session_id: sid,
                    subagent_type: state.subagentType,
                    trace_id: state.traceId,
                    child_run_id: state.childRunId,
                });
            }
            if (!state && !childRunId && !traceId) {
                const outputText = typeof eventPayload.output?.output === "string" ? eventPayload.output.output : "";
                const outputSubagentType = extractDelegationSubagentType(eventPayload.output?.args, eventPayload.output?.metadata) ||
                    extractDelegationSubagentTypeFromOutput(outputText);
                const matches = outputSubagentType
                    ? matchingSessionLifecycleKeys(byDelegation, sid, outputSubagentType)
                    : sessionLifecycleKeys(byDelegation, sid);
                if (matches.length > 1) {
                    const outputFailed = isFailureOutput(outputText);
                    forceFinalizeMatches({
                        sid,
                        activeKeys: matches,
                        failed: outputFailed,
                        directory,
                        reasonCode: outputFailed
                            ? "subagent_lifecycle_after_ambiguous_forced_failed"
                            : "subagent_lifecycle_after_ambiguous_forced_completed",
                    });
                    return;
                }
            }
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
