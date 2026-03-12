import { createHash } from "node:crypto";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { loadAgentMetadata } from "../shared/agent-metadata.js";
import { clearDelegationChildSessionLink, getDelegationChildSessionLink, registerDelegationChildSession, } from "../shared/delegation-child-session.js";
import { annotateDelegationMetadata, extractDelegationChildRunId, extractDelegationSubagentType, extractDelegationSubagentTypeFromOutput, extractDelegationTraceId, resolveDelegationTraceId, } from "../shared/delegation-trace.js";
function matchingSessionDelegationKeys(activeByDelegation, sid, subagentType) {
    const matches = [];
    for (const [key, value] of activeByDelegation.entries()) {
        if ((key === sid || key.startsWith(`${sid}:`)) && value.subagentType === subagentType) {
            matches.push(key);
        }
    }
    return matches;
}
function nowMs() {
    return Date.now();
}
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
function delegationKey(sid, childRunId, traceId, args) {
    if (childRunId) {
        return `${sid}:${childRunId}`;
    }
    return traceId ? `${sid}:${traceId}` : fallbackDelegationKey(sid, args);
}
function matchingSessionTraceDelegationKeys(activeByDelegation, sid, traceId) {
    const matches = [];
    for (const [key, value] of activeByDelegation.entries()) {
        if ((key === sid || key.startsWith(`${sid}:`)) && value.traceId === traceId) {
            matches.push(key);
        }
    }
    return matches;
}
function sessionDelegationKeys(activeByDelegation, sid) {
    const matches = [];
    for (const key of activeByDelegation.keys()) {
        if (key === sid || key.startsWith(`${sid}:`)) {
            matches.push(key);
        }
    }
    return matches;
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
export function createDelegationConcurrencyGuardHook(options) {
    const activeByDelegation = new Map();
    function releaseLinkedDelegation(args) {
        const fallbackEventPayload = {
            input: { tool: "task", sessionID: args.parentSessionId },
            output: {
                args: {
                    ...(args.traceId ? { prompt: `[DELEGATION TRACE ${args.traceId}]` } : {}),
                },
                metadata: {
                    gateway: {
                        delegation: {
                            ...(args.childRunId ? { childRunId: args.childRunId } : {}),
                            ...(args.traceId ? { traceId: args.traceId } : {}),
                            ...(args.subagentType ? { subagentType: args.subagentType } : {}),
                        },
                    },
                },
            },
            directory: args.directory,
        };
        const releaseMode = releaseDelegationReservation(fallbackEventPayload, args.directory);
        if (releaseMode === "none" || releaseMode === "ambiguous_skip") {
            return false;
        }
        writeGatewayEventAudit(args.directory, {
            hook: "delegation-concurrency-guard",
            stage: "state",
            reason_code: args.reasonCode,
            session_id: args.parentSessionId,
            trace_id: args.traceId || undefined,
        });
        return true;
    }
    function releaseDelegationReservation(eventPayload, directory) {
        const sid = sessionId(eventPayload);
        if (!sid) {
            return "none";
        }
        const childRunId = extractDelegationChildRunId(eventPayload.output?.metadata);
        const traceId = extractDelegationTraceId(eventPayload.output?.args, eventPayload.output?.metadata);
        if (childRunId || traceId) {
            const key = delegationKey(sid, childRunId, traceId);
            if (activeByDelegation.delete(key)) {
                return "direct";
            }
            if (traceId) {
                const traceMatches = matchingSessionTraceDelegationKeys(activeByDelegation, sid, traceId);
                if (traceMatches.length === 1) {
                    activeByDelegation.delete(traceMatches[0]);
                    writeGatewayEventAudit(directory, {
                        hook: "delegation-concurrency-guard",
                        stage: "state",
                        reason_code: "delegation_concurrency_trace_fallback_matched",
                        session_id: sid,
                        trace_id: traceId || undefined,
                    });
                    return "trace_fallback";
                }
            }
        }
        const outputText = typeof eventPayload.output?.output === "string" ? eventPayload.output.output : "";
        const outputSubagentType = extractDelegationSubagentType(eventPayload.output?.args, eventPayload.output?.metadata) ||
            extractDelegationSubagentTypeFromOutput(outputText);
        const fallbackKeys = outputSubagentType
            ? matchingSessionDelegationKeys(activeByDelegation, sid, outputSubagentType)
            : sessionDelegationKeys(activeByDelegation, sid);
        if (fallbackKeys.length === 1) {
            activeByDelegation.delete(fallbackKeys[0]);
            writeGatewayEventAudit(directory, {
                hook: "delegation-concurrency-guard",
                stage: "state",
                reason_code: "delegation_concurrency_subagent_fallback_matched",
                session_id: sid,
                subagent_type: outputSubagentType || undefined,
            });
            return "subagent_fallback";
        }
        if (fallbackKeys.length > 1) {
            for (const key of fallbackKeys) {
                activeByDelegation.delete(key);
            }
            writeGatewayEventAudit(directory, {
                hook: "delegation-concurrency-guard",
                stage: "state",
                reason_code: "delegation_concurrency_after_ambiguous_forced_release",
                session_id: sid,
                concurrent_total: String(fallbackKeys.length),
            });
        }
        return fallbackKeys.length > 1 ? "ambiguous_skip" : "none";
    }
    function pruneStaleDelegations(directory, referenceTime) {
        for (const [key, active] of activeByDelegation.entries()) {
            if (referenceTime - active.startedAt < options.staleReservationMs) {
                continue;
            }
            activeByDelegation.delete(key);
            const [sessionKey, traceKey] = key.split(":", 2);
            writeGatewayEventAudit(directory, {
                hook: "delegation-concurrency-guard",
                stage: "state",
                reason_code: "delegation_concurrency_stale_pruned",
                session_id: sessionKey,
                trace_id: active.traceId || (traceKey && !traceKey.startsWith("fp") ? traceKey : undefined),
                subagent_type: active.subagentType || undefined,
                category: active.category || undefined,
                cost_tier: active.costTier || undefined,
            });
        }
    }
    return {
        id: "delegation-concurrency-guard",
        priority: 294,
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
                releaseLinkedDelegation({
                    parentSessionId: link.parentSessionId,
                    childRunId: link.childRunId,
                    traceId: link.traceId,
                    subagentType: link.subagentType,
                    directory: options.directory,
                    reasonCode: "delegation_concurrency_child_idle_released",
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
                releaseLinkedDelegation({
                    parentSessionId: link.parentSessionId,
                    childRunId: link.childRunId,
                    traceId: link.traceId,
                    subagentType: link.subagentType,
                    directory: typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                        ? eventPayload.directory
                        : options.directory,
                    reasonCode: failed
                        ? "delegation_concurrency_child_message_failed_released"
                        : "delegation_concurrency_child_message_completed_released",
                });
                return;
            }
            if (type === "session.deleted") {
                const sid = sessionId((payload ?? {}));
                if (sid) {
                    const childLink = clearDelegationChildSessionLink(sid);
                    if (childLink) {
                        releaseLinkedDelegation({
                            parentSessionId: childLink.parentSessionId,
                            childRunId: childLink.childRunId,
                            traceId: childLink.traceId,
                            subagentType: childLink.subagentType,
                            directory: options.directory,
                            reasonCode: "delegation_concurrency_child_deleted_released",
                        });
                    }
                    for (const key of activeByDelegation.keys()) {
                        if (key === sid || key.startsWith(`${sid}:`)) {
                            activeByDelegation.delete(key);
                        }
                    }
                }
                return;
            }
            if (type === "tool.execute.after") {
                const eventPayload = (payload ?? {});
                if (String(eventPayload.input?.tool ?? "").toLowerCase().trim() !== "task") {
                    return;
                }
                releaseDelegationReservation(eventPayload, effectiveDirectory(eventPayload, options.directory));
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
                const directory = effectiveDirectory(eventPayload, options.directory);
                const releaseMode = releaseDelegationReservation(eventPayload, directory);
                if (releaseMode !== "none" && releaseMode !== "ambiguous_skip") {
                    writeGatewayEventAudit(directory, {
                        hook: "delegation-concurrency-guard",
                        stage: "state",
                        reason_code: "delegation_concurrency_before_error_released",
                        session_id: sid,
                    });
                }
                return;
            }
            if (type !== "tool.execute.before") {
                return;
            }
            const eventPayload = (payload ?? {});
            const tool = String(eventPayload.input?.tool ?? "").toLowerCase().trim();
            if (tool !== "task") {
                return;
            }
            const sid = sessionId(eventPayload);
            if (!sid) {
                return;
            }
            const args = eventPayload.output?.args;
            if (!args || typeof args !== "object") {
                return;
            }
            const subagentType = String(args.subagent_type ?? "").toLowerCase().trim();
            const category = String(args.category ?? "").toLowerCase().trim();
            const traceId = resolveDelegationTraceId(args ?? {});
            annotateDelegationMetadata(eventPayload.output ?? {}, args);
            const childRunId = extractDelegationChildRunId(eventPayload.output?.metadata);
            const key = delegationKey(sid, childRunId, traceId, args);
            if (!subagentType && !category) {
                return;
            }
            const directory = effectiveDirectory(eventPayload, options.directory);
            const now = nowMs();
            pruneStaleDelegations(directory, now);
            const metadata = subagentType ? loadAgentMetadata(directory).get(subagentType) : undefined;
            const costTier = String(metadata?.cost_tier ?? "cheap").toLowerCase();
            const fallbackCategory = category.length > 0 ? category : "balanced";
            const recommendedCategory = String(metadata?.default_category ?? fallbackCategory).toLowerCase();
            const values = [...activeByDelegation.values()];
            const total = values.length;
            const expensive = values.filter((item) => item.costTier === "expensive").length;
            const deep = values.filter((item) => item.category === "deep").length;
            const critical = values.filter((item) => item.category === "critical").length;
            if (total >= options.maxTotalConcurrent) {
                writeGatewayEventAudit(directory, {
                    hook: "delegation-concurrency-guard",
                    stage: "guard",
                    reason_code: "delegation_concurrency_total_blocked",
                    session_id: sid,
                    concurrent_total: String(total),
                });
                throw new Error(`Blocked delegation: concurrent task delegations ${total} reached maxTotalConcurrent=${options.maxTotalConcurrent}.`);
            }
            if (costTier === "expensive" && expensive >= options.maxExpensiveConcurrent) {
                writeGatewayEventAudit(directory, {
                    hook: "delegation-concurrency-guard",
                    stage: "guard",
                    reason_code: "delegation_concurrency_expensive_blocked",
                    session_id: sid,
                    concurrent_expensive: String(expensive),
                });
                throw new Error(`Blocked delegation: expensive concurrent delegations ${expensive} reached maxExpensiveConcurrent=${options.maxExpensiveConcurrent}.`);
            }
            if (recommendedCategory === "deep" && deep >= options.maxDeepConcurrent) {
                writeGatewayEventAudit(directory, {
                    hook: "delegation-concurrency-guard",
                    stage: "guard",
                    reason_code: "delegation_concurrency_deep_blocked",
                    session_id: sid,
                    concurrent_deep: String(deep),
                });
                throw new Error(`Blocked delegation: deep concurrent delegations ${deep} reached maxDeepConcurrent=${options.maxDeepConcurrent}.`);
            }
            if (recommendedCategory === "critical" && critical >= options.maxCriticalConcurrent) {
                writeGatewayEventAudit(directory, {
                    hook: "delegation-concurrency-guard",
                    stage: "guard",
                    reason_code: "delegation_concurrency_critical_blocked",
                    session_id: sid,
                    concurrent_critical: String(critical),
                });
                throw new Error(`Blocked delegation: critical concurrent delegations ${critical} reached maxCriticalConcurrent=${options.maxCriticalConcurrent}.`);
            }
            activeByDelegation.set(key, {
                childRunId: childRunId || undefined,
                subagentType,
                category: recommendedCategory,
                costTier,
                traceId,
                startedAt: now,
            });
            writeGatewayEventAudit(directory, {
                hook: "delegation-concurrency-guard",
                stage: "state",
                reason_code: "delegation_concurrency_reserved",
                session_id: sid,
                child_run_id: childRunId || undefined,
                trace_id: traceId || undefined,
                subagent_type: subagentType || undefined,
                category: recommendedCategory,
                cost_tier: costTier,
            });
        },
    };
}
