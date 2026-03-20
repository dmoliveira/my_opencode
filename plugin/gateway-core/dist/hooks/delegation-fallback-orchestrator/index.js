import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { buildCompactDecisionCacheKey, writeDecisionComparisonAudit, } from "../shared/llm-decision-runtime.js";
import { annotateDelegationMetadata, extractDelegationTraceId, resolveDelegationTraceId, } from "../shared/delegation-trace.js";
const FAILURE_REASON_BY_CHAR = {
    U: "delegation_unknown_agent",
    C: "delegation_unknown_category",
    I: "delegation_invalid_arguments",
    B: "delegation_blocked_forbidden_tool",
    R: "delegation_runtime_error",
};
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
function buildFailureInstruction() {
    return "Classify only the sanitized delegation failure evidence. U=unknown_agent, C=unknown_category, I=invalid_arguments, B=blocked_forbidden_tool, R=runtime_error, N=no_match.";
}
function sanitizeFailureText(text) {
    const trimmed = text.trim();
    const actualMatch = trimmed.match(/actual (?:failure|output|prompt|description)\s*:\s*([\s\S]+)$/i);
    const extracted = actualMatch?.[1]?.trim() || trimmed;
    return extracted
        .replace(/<[^>]+>/g, " ")
        .replace(/\b(user|assistant|system|tool)\s*:/gi, " ")
        .replace(/ignore all previous instructions/gi, " ")
        .replace(/ignore previous instructions/gi, " ")
        .replace(/answer\s+[A-Z]/g, " ")
        .replace(/classify as [a-z_-]+/gi, " ")
        .replace(/\s*[;|]\s*/g, " ")
        .replace(/\s+/g, " ")
        .trim();
}
function buildFailureContext(output, prompt, description) {
    return [
        `output=${sanitizeFailureText(output) || "(empty)"}`,
        `prompt=${sanitizeFailureText(prompt) || "(empty)"}`,
        `description=${sanitizeFailureText(description) || "(empty)"}`,
    ].join(" ");
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
            let reason = detectFailureReason(eventPayload.output.output);
            const args = eventPayload.output?.args;
            const traceId = extractDelegationTraceId(args, eventPayload.output?.metadata);
            const subagentType = String(args?.subagent_type ?? "").toLowerCase().trim();
            const category = String(args?.category ?? "").toLowerCase().trim();
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            if (!reason && options.decisionRuntime) {
                const decision = await options.decisionRuntime.decide({
                    hookId: "delegation-fallback-orchestrator",
                    sessionId: sid,
                    traceId,
                    templateId: "delegation-failure-classifier-v1",
                    instruction: buildFailureInstruction(),
                    context: buildFailureContext(String(eventPayload.output.output ?? ""), String(args?.prompt ?? ""), String(args?.description ?? "")),
                    allowedChars: ["U", "C", "I", "B", "R", "N"],
                    decisionMeaning: {
                        U: "delegation_unknown_agent",
                        C: "delegation_unknown_category",
                        I: "delegation_invalid_arguments",
                        B: "delegation_blocked_forbidden_tool",
                        R: "delegation_runtime_error",
                        N: "no_match",
                    },
                    cacheKey: buildCompactDecisionCacheKey({
                        prefix: "delegation-failure",
                        parts: [subagentType || "none", category || "none"],
                        text: buildFailureContext(String(eventPayload.output.output ?? ""), String(args?.prompt ?? ""), String(args?.description ?? "")),
                    }),
                });
                if (decision.accepted) {
                    const aiReason = FAILURE_REASON_BY_CHAR[decision.char] ?? null;
                    writeDecisionComparisonAudit({
                        directory,
                        hookId: "delegation-fallback-orchestrator",
                        sessionId: sid,
                        traceId,
                        mode: options.decisionRuntime.config.mode,
                        deterministicMeaning: "no_match",
                        aiMeaning: decision.meaning || aiReason || "no_match",
                        deterministicValue: "none",
                        aiValue: aiReason ?? "none",
                    });
                    writeGatewayEventAudit(directory, {
                        hook: "delegation-fallback-orchestrator",
                        stage: "state",
                        reason_code: "llm_delegation_failure_decision_recorded",
                        session_id: sid,
                        trace_id: traceId,
                        llm_decision_char: decision.char,
                        llm_decision_meaning: decision.meaning,
                        llm_decision_mode: options.decisionRuntime.config.mode,
                    });
                    if (options.decisionRuntime.config.mode === "shadow" && aiReason) {
                        writeGatewayEventAudit(directory, {
                            hook: "delegation-fallback-orchestrator",
                            stage: "state",
                            reason_code: "llm_delegation_failure_shadow_deferred",
                            session_id: sid,
                            trace_id: traceId,
                            llm_decision_char: decision.char,
                            llm_decision_meaning: decision.meaning,
                            llm_decision_mode: options.decisionRuntime.config.mode,
                        });
                    }
                    else {
                        reason = aiReason;
                    }
                }
            }
            if (!reason) {
                for (const key of sessionFailureKeys(lastFailureByDelegation, sid)) {
                    lastFailureByDelegation.delete(key);
                }
                return;
            }
            const key = delegationKey(sid, traceId);
            lastFailureByDelegation.set(key, {
                traceId,
                subagentType,
                category,
                reasonCode: reason,
            });
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
