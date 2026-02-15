import { writeGatewayEventAudit } from "../../audit/event-audit.js";
const RULES_BY_TOOL = {
    bash: "Rule: use non-interactive flags and avoid destructive commands.",
    task: "Rule: delegated subagents should execute directly and avoid interactive question flows.",
    write: "Rule: do not overwrite existing files unless the behavior is intentional and validated.",
};
// Resolves session id from tool lifecycle payload.
function resolveSessionId(payload) {
    const candidates = [payload.input?.sessionID, payload.input?.sessionId];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
// Creates rules injector hook that appends conditional runtime guidance.
export function createRulesInjectorHook(options) {
    const pendingRuleBySession = new Map();
    const lastInjectedRuleBySession = new Map();
    return {
        id: "rules-injector",
        priority: 298,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const eventPayload = (payload ?? {});
                const sessionId = eventPayload.properties?.info?.id;
                if (typeof sessionId === "string" && sessionId.trim()) {
                    const key = sessionId.trim();
                    pendingRuleBySession.delete(key);
                    lastInjectedRuleBySession.delete(key);
                }
                return;
            }
            if (type === "tool.execute.before") {
                const eventPayload = (payload ?? {});
                const sessionId = resolveSessionId(eventPayload);
                const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
                const rule = RULES_BY_TOOL[tool];
                if (sessionId && rule) {
                    pendingRuleBySession.set(sessionId, rule);
                }
                return;
            }
            if (type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = resolveSessionId(eventPayload);
            if (!sessionId || typeof eventPayload.output?.output !== "string") {
                return;
            }
            const rule = pendingRuleBySession.get(sessionId);
            if (!rule) {
                return;
            }
            pendingRuleBySession.delete(sessionId);
            if (lastInjectedRuleBySession.get(sessionId) === rule) {
                return;
            }
            eventPayload.output.output = `${eventPayload.output.output}\n\n${rule}`;
            lastInjectedRuleBySession.set(sessionId, rule);
            writeGatewayEventAudit(directory, {
                hook: "rules-injector",
                stage: "state",
                reason_code: "runtime_rule_injected",
                session_id: sessionId,
            });
        },
    };
}
