import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { annotateDelegationMetadata, extractDelegationTraceId, resolveDelegationTraceId, } from "../shared/delegation-trace.js";
function delegationKey(sessionId, traceId) {
    return traceId ? `${sessionId}:${traceId}` : sessionId;
}
function sessionFailureKeys(lastFailureByDelegation, sid) {
    const matches = [];
    for (const key of lastFailureByDelegation.keys()) {
        if (key === sid || key.startsWith(`${sid}:`)) {
            matches.push(key);
        }
    }
    return matches;
}
function sessionId(payload) {
    return String(payload.input?.sessionID ?? payload.input?.sessionId ?? payload.properties?.info?.id ?? "").trim();
}
function detectFailureReason(output) {
    const lower = output.toLowerCase();
    if (lower.includes("unknown agent")) {
        return "delegation_unknown_agent";
    }
    if (lower.includes("unknown category")) {
        return "delegation_unknown_category";
    }
    if (lower.includes("invalid arguments") || lower.includes("must provide either category or subagent_type")) {
        return "delegation_invalid_arguments";
    }
    if (lower.includes("blocked delegation") || lower.includes("forbidden tool")) {
        return "delegation_blocked_forbidden_tool";
    }
    if (lower.includes("[error]") || lower.includes("command failed")) {
        return "delegation_runtime_error";
    }
    return null;
}
function prependHint(original, hint) {
    if (!original.trim()) {
        return hint;
    }
    if (original.includes(hint)) {
        return original;
    }
    return `${hint}\n\n${original}`;
}
export function createDelegationFallbackOrchestratorHook(options) {
    const lastFailureByDelegation = new Map();
    return {
        id: "delegation-fallback-orchestrator",
        priority: 293,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const sid = sessionId((payload ?? {}));
                if (sid) {
                    for (const key of sessionFailureKeys(lastFailureByDelegation, sid)) {
                        lastFailureByDelegation.delete(key);
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
                const args = eventPayload.output?.args;
                if (!args || typeof args !== "object") {
                    return;
                }
                const traceId = resolveDelegationTraceId(args);
                annotateDelegationMetadata(eventPayload.output ?? {}, args);
                const failure = lastFailureByDelegation.get(delegationKey(sid, traceId));
                if (!failure) {
                    return;
                }
                const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                    ? eventPayload.directory
                    : options.directory;
                const fallbackHint = "[delegation-fallback-orchestrator] previous delegation failed; applying fallback route category=general and removing explicit subagent_type.";
                delete args.subagent_type;
                args.category = "general";
                args.prompt = prependHint(String(args.prompt ?? ""), fallbackHint);
                args.description = prependHint(String(args.description ?? ""), fallbackHint);
                lastFailureByDelegation.delete(delegationKey(sid, failure.traceId));
                writeGatewayEventAudit(directory, {
                    hook: "delegation-fallback-orchestrator",
                    stage: "state",
                    reason_code: "delegation_fallback_applied",
                    session_id: sid,
                    trace_id: traceId,
                    previous_subagent_type: failure.subagentType || undefined,
                    previous_category: failure.category || undefined,
                    previous_reason_code: failure.reasonCode,
                    fallback_category: "general",
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
            if (!sid || typeof eventPayload.output?.output !== "string") {
                return;
            }
            const reason = detectFailureReason(eventPayload.output.output);
            if (!reason) {
                for (const key of sessionFailureKeys(lastFailureByDelegation, sid)) {
                    lastFailureByDelegation.delete(key);
                }
                return;
            }
            const args = eventPayload.output?.args;
            const traceId = extractDelegationTraceId(args, eventPayload.output?.metadata);
            const subagentType = String(args?.subagent_type ?? "").toLowerCase().trim();
            const category = String(args?.category ?? "").toLowerCase().trim();
            const key = delegationKey(sid, traceId);
            lastFailureByDelegation.set(key, {
                traceId,
                subagentType,
                category,
                reasonCode: reason,
            });
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            writeGatewayEventAudit(directory, {
                hook: "delegation-fallback-orchestrator",
                stage: "state",
                reason_code: "delegation_failure_recorded",
                session_id: sid,
                trace_id: traceId,
                subagent_type: subagentType || undefined,
                category: category || undefined,
                failure_reason_code: reason,
            });
        },
    };
}
