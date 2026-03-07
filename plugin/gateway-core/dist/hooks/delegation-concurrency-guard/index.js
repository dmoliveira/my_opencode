import { createHash } from "node:crypto";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { loadAgentMetadata } from "../shared/agent-metadata.js";
import { annotateDelegationMetadata, extractDelegationSubagentType, extractDelegationSubagentTypeFromOutput, extractDelegationTraceId, resolveDelegationTraceId, } from "../shared/delegation-trace.js";
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
function delegationKey(sid, traceId, args) {
    return traceId ? `${sid}:${traceId}` : fallbackDelegationKey(sid, args);
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
    return String(payload.input?.sessionID ?? payload.input?.sessionId ?? payload.properties?.info?.id ?? "").trim();
}
export function createDelegationConcurrencyGuardHook(options) {
    const activeByDelegation = new Map();
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
        priority: 319,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const sid = sessionId((payload ?? {}));
                if (sid) {
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
                const sid = sessionId(eventPayload);
                if (sid) {
                    const traceId = extractDelegationTraceId(eventPayload.output?.args, eventPayload.output?.metadata);
                    if (traceId) {
                        const key = delegationKey(sid, traceId);
                        activeByDelegation.delete(key);
                    }
                    else {
                        const outputText = typeof eventPayload.output?.output === "string" ? eventPayload.output.output : "";
                        const outputSubagentType = extractDelegationSubagentType(eventPayload.output?.args, eventPayload.output?.metadata) ||
                            extractDelegationSubagentTypeFromOutput(outputText);
                        const fallbackKeys = outputSubagentType
                            ? matchingSessionDelegationKeys(activeByDelegation, sid, outputSubagentType)
                            : sessionDelegationKeys(activeByDelegation, sid);
                        if (fallbackKeys.length === 1) {
                            activeByDelegation.delete(fallbackKeys[0]);
                        }
                        else if (fallbackKeys.length > 1) {
                            writeGatewayEventAudit(options.directory, {
                                hook: "delegation-concurrency-guard",
                                stage: "skip",
                                reason_code: "delegation_concurrency_after_ambiguous_skip",
                                session_id: sid,
                                concurrent_total: String(fallbackKeys.length),
                            });
                        }
                    }
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
            const key = delegationKey(sid, traceId, args);
            if (!subagentType && !category) {
                return;
            }
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
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
                trace_id: traceId || undefined,
                subagent_type: subagentType || undefined,
                category: recommendedCategory,
                cost_tier: costTier,
            });
        },
    };
}
