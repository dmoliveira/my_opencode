import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { loadAgentMetadata } from "../shared/agent-metadata.js";
function sessionId(payload) {
    return String(payload.input?.sessionID ?? payload.input?.sessionId ?? payload.properties?.info?.id ?? "").trim();
}
export function createDelegationConcurrencyGuardHook(options) {
    const activeBySession = new Map();
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
                    activeBySession.delete(sid);
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
                    activeBySession.delete(sid);
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
            if (!subagentType && !category) {
                return;
            }
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const metadata = subagentType ? loadAgentMetadata(directory).get(subagentType) : undefined;
            const costTier = String(metadata?.cost_tier ?? "cheap").toLowerCase();
            const fallbackCategory = category.length > 0 ? category : "balanced";
            const recommendedCategory = String(metadata?.default_category ?? fallbackCategory).toLowerCase();
            const values = [...activeBySession.values()];
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
            activeBySession.set(sid, {
                subagentType,
                category: recommendedCategory,
                costTier,
            });
            writeGatewayEventAudit(directory, {
                hook: "delegation-concurrency-guard",
                stage: "state",
                reason_code: "delegation_concurrency_reserved",
                session_id: sid,
                subagent_type: subagentType || undefined,
                category: recommendedCategory,
                cost_tier: costTier,
            });
        },
    };
}
