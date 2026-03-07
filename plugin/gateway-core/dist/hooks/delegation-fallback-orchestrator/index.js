import { writeGatewayEventAudit } from "../../audit/event-audit.js";
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
    const lastFailureBySession = new Map();
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
                    lastFailureBySession.delete(sid);
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
                const failure = lastFailureBySession.get(sid);
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
                lastFailureBySession.delete(sid);
                writeGatewayEventAudit(directory, {
                    hook: "delegation-fallback-orchestrator",
                    stage: "state",
                    reason_code: "delegation_fallback_applied",
                    session_id: sid,
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
                lastFailureBySession.delete(sid);
                return;
            }
            const args = eventPayload.output?.args;
            const subagentType = String(args?.subagent_type ?? "").toLowerCase().trim();
            const category = String(args?.category ?? "").toLowerCase().trim();
            lastFailureBySession.set(sid, {
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
                subagent_type: subagentType || undefined,
                category: category || undefined,
                failure_reason_code: reason,
            });
        },
    };
}
