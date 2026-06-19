import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { loadAgentMetadata, } from "../shared/agent-metadata.js";
import { annotateDelegationMetadata, extractDelegationSubagentType, extractDelegationSubagentTypeFromOutput, extractDelegationTraceId, resolveDelegationTraceId, } from "../shared/delegation-trace.js";
function delegationKey(sessionId, traceId, subagentType) {
    if (traceId) {
        return `${sessionId}:${traceId}`;
    }
    return `${sessionId}:agent:${subagentType || "unknown"}`;
}
function sessionId(payload) {
    return String(payload.input?.sessionID ??
        payload.input?.sessionId ??
        payload.properties?.info?.id ??
        "").trim();
}
function looksLikeFailure(text) {
    return /(\[error\]|invalid arguments|failed|exception|traceback|unknown\s+agent|unknown\s+category)/i.test(text);
}
function buildHint(context) {
    const trigger = Array.isArray(context.metadata.triggers) &&
        context.metadata.triggers.length > 0
        ? context.metadata.triggers[0]
        : "verify delegation intent";
    const avoid = Array.isArray(context.metadata.avoid_when) &&
        context.metadata.avoid_when.length > 0
        ? context.metadata.avoid_when[0]
        : "avoid mismatched scope";
    return [
        "[agent-context-shaper] delegation context",
        `- subagent: ${context.subagentType}`,
        `- recommended_category: ${context.category}`,
        `- cost_tier: ${context.metadata.cost_tier ?? "unknown"}`,
        `- next_best_trigger: ${trigger}`,
        `- avoid_when: ${avoid}`,
    ].join("\n");
}
function buildTaskFocusReminder(context) {
    const trigger = Array.isArray(context.metadata.triggers) &&
        context.metadata.triggers.length > 0
        ? context.metadata.triggers[0]
        : "complete the delegated objective";
    const avoid = Array.isArray(context.metadata.avoid_when) &&
        context.metadata.avoid_when.length > 0
        ? context.metadata.avoid_when[0]
        : "scope drift or unrelated follow-up work";
    return [
        "[agent-context-shaper] delegated task focus",
        `- subagent: ${context.subagentType}`,
        `- category: ${context.category}`,
        "- execute one delegated objective for this task call before returning control",
        `- prioritize: ${trigger}`,
        `- avoid: ${avoid}`,
        "- if you uncover extra work, report it as a follow-up instead of expanding scope in the same delegation",
    ].join("\n");
}
export function createAgentContextShaperHook(options) {
    const contextByDelegation = new Map();
    return {
        id: "agent-context-shaper",
        priority: 294,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const sid = sessionId((payload ?? {}));
                if (sid) {
                    for (const key of contextByDelegation.keys()) {
                        if (key === sid || key.startsWith(`${sid}:`)) {
                            contextByDelegation.delete(key);
                        }
                    }
                }
                return;
            }
            if (type === "tool.execute.before") {
                const eventPayload = (payload ?? {});
                const tool = String(eventPayload.input?.tool ?? "")
                    .toLowerCase()
                    .trim();
                if (tool !== "task") {
                    return;
                }
                const sid = sessionId(eventPayload);
                if (!sid) {
                    return;
                }
                const subagentType = String(eventPayload.output?.args?.subagent_type ?? "")
                    .toLowerCase()
                    .trim();
                if (!subagentType) {
                    return;
                }
                const traceId = resolveDelegationTraceId(eventPayload.output?.args ?? {});
                annotateDelegationMetadata(eventPayload.output ?? {}, eventPayload.output?.args);
                const metadata = loadAgentMetadata(options.directory).get(subagentType) ?? {};
                const category = String(eventPayload.output?.args?.category ??
                    metadata.default_category ??
                    "balanced");
                contextByDelegation.set(delegationKey(sid, traceId, subagentType), {
                    sessionId: sid,
                    traceId,
                    subagentType,
                    category,
                    metadata,
                });
                const prompt = String(eventPayload.output?.args?.prompt ?? "");
                if (prompt &&
                    !prompt.includes("[agent-context-shaper] delegated task focus")) {
                    eventPayload.output = eventPayload.output ?? {};
                    eventPayload.output.args = eventPayload.output.args ?? {};
                    eventPayload.output.args.prompt = `${buildTaskFocusReminder({
                        sessionId: sid,
                        traceId,
                        subagentType,
                        category,
                        metadata,
                    })}\n\n${prompt}`;
                    writeGatewayEventAudit(options.directory, {
                        hook: "agent-context-shaper",
                        stage: "before",
                        reason_code: "delegated_task_focus_injected",
                        session_id: sid,
                        trace_id: traceId,
                        subagent_type: subagentType,
                        recommended_category: category,
                    });
                }
                return;
            }
            if (type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            const tool = String(eventPayload.input?.tool ?? "")
                .toLowerCase()
                .trim();
            if (tool !== "task" || typeof eventPayload.output?.output !== "string") {
                return;
            }
            const sid = sessionId(eventPayload);
            if (!sid) {
                return;
            }
            const outputText = eventPayload.output.output;
            const traceId = extractDelegationTraceId(eventPayload.output?.args, eventPayload.output?.metadata);
            const subagentType = extractDelegationSubagentType(eventPayload.output?.args, eventPayload.output?.metadata) || extractDelegationSubagentTypeFromOutput(outputText);
            const directKey = delegationKey(sid, traceId, subagentType);
            let matchedKey = directKey;
            let context = contextByDelegation.get(directKey);
            if (!context) {
                const matches = [...contextByDelegation.entries()].filter(([, candidate]) => candidate.sessionId === sid &&
                    candidate.subagentType === subagentType);
                if (matches.length === 1) {
                    [[matchedKey, context]] = matches;
                }
            }
            if (!context) {
                return;
            }
            annotateDelegationMetadata(eventPayload.output ?? {}, {
                subagent_type: context.subagentType,
                category: context.category,
                prompt: `[DELEGATION TRACE ${context.traceId}]`,
            });
            const output = outputText;
            if (!looksLikeFailure(output) && output.length < 1200) {
                contextByDelegation.delete(matchedKey);
                return;
            }
            const hint = buildHint(context);
            if (!output.includes("[agent-context-shaper]")) {
                eventPayload.output.output = `${output}\n\n${hint}`;
            }
            const directory = typeof eventPayload.directory === "string" &&
                eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            writeGatewayEventAudit(directory, {
                hook: "agent-context-shaper",
                stage: "state",
                reason_code: "agent_context_hint_appended",
                session_id: sid,
                subagent_type: context.subagentType,
                recommended_category: context.category,
            });
            contextByDelegation.delete(matchedKey);
        },
    };
}
