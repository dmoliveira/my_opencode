import { writeGatewayEventAudit } from "../../audit/event-audit.js";
function sessionId(payload) {
    return String(payload.input?.sessionID ?? payload.input?.sessionId ?? "").trim();
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
function detectRewriteSource(text) {
    if (text.includes("[delegation-fallback-orchestrator]")) {
        return "fallback";
    }
    if (text.includes("[DELEGATION ROUTER]")) {
        return "route";
    }
    return null;
}
export function createAgentDiscoverabilityInjectorHook(options) {
    return {
        id: "agent-discoverability-injector",
        priority: 294,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.before") {
                return;
            }
            const eventPayload = (payload ?? {});
            if (String(eventPayload.input?.tool ?? "").toLowerCase().trim() !== "task") {
                return;
            }
            const args = eventPayload.output?.args;
            if (!args || typeof args !== "object") {
                return;
            }
            const combined = `${String(args.prompt ?? "")}\n${String(args.description ?? "")}`;
            if (combined.includes("/agent-catalog")) {
                return;
            }
            const source = detectRewriteSource(combined);
            if (!source) {
                return;
            }
            const subagentType = String(args.subagent_type ?? "").toLowerCase().trim();
            const hint = subagentType
                ? `[AGENT CATALOG] Inspect details with: /agent-catalog explain ${subagentType}`
                : "[AGENT CATALOG] Inspect details with: /agent-catalog list";
            args.prompt = prependHint(String(args.prompt ?? ""), hint);
            args.description = prependHint(String(args.description ?? ""), hint);
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            writeGatewayEventAudit(directory, {
                hook: "agent-discoverability-injector",
                stage: "state",
                reason_code: "agent_discoverability_hint_injected",
                session_id: sessionId(eventPayload),
                subagent_type: subagentType || undefined,
                trigger_source: source,
            });
        },
    };
}
