import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { loadAgentMetadata } from "../shared/agent-metadata.js";
function sessionId(payload) {
    return String(payload.input?.sessionID ?? payload.input?.sessionId ?? "").trim();
}
export function createDelegationDecisionAuditHook(options) {
    return {
        id: "delegation-decision-audit",
        priority: 291,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.before") {
                return;
            }
            const eventPayload = (payload ?? {});
            const tool = String(eventPayload.input?.tool ?? "").toLowerCase().trim();
            if (tool !== "task") {
                return;
            }
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const subagentType = String(eventPayload.output?.args?.subagent_type ?? "")
                .toLowerCase()
                .trim();
            const category = String(eventPayload.output?.args?.category ?? "").trim();
            if (!subagentType && !category) {
                return;
            }
            const metadata = loadAgentMetadata(directory).get(subagentType);
            writeGatewayEventAudit(directory, {
                hook: "delegation-decision-audit",
                stage: "state",
                reason_code: "delegation_decision_recorded",
                session_id: sessionId(eventPayload),
                subagent_type: subagentType || undefined,
                category: category || undefined,
                decision_source: subagentType ? "explicit_subagent_type" : "explicit_category",
                run_in_background: String(Boolean(eventPayload.output?.args?.run_in_background)),
                cost_tier: metadata?.cost_tier,
                recommended_category: metadata?.default_category,
                fallback_policy: metadata?.fallback_policy,
            });
        },
    };
}
