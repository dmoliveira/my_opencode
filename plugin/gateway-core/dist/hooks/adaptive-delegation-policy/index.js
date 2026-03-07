import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { getDelegationFailureStats, getRecentDelegationOutcomes, } from "../shared/delegation-runtime-state.js";
import { resolveDelegationTraceId } from "../shared/delegation-trace.js";
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
function isExpensiveCategory(category) {
    return category === "critical" || category === "deep";
}
export function createAdaptiveDelegationPolicyHook(options) {
    let cooldownUntil = 0;
    return {
        id: "adaptive-delegation-policy",
        priority: 297,
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
            const traceId = resolveDelegationTraceId(args);
            const category = String(args.category ?? "balanced").toLowerCase().trim() || "balanced";
            const sid = sessionId(eventPayload);
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const stats = getDelegationFailureStats(options.windowMs);
            if (stats.total >= options.minSamples &&
                stats.failureRate >= options.highFailureRate) {
                cooldownUntil = Date.now() + options.cooldownMs;
                writeGatewayEventAudit(directory, {
                    hook: "adaptive-delegation-policy",
                    stage: "state",
                    reason_code: "adaptive_policy_cooldown_started",
                    session_id: sid,
                    trace_id: traceId,
                    sample_total: String(stats.total),
                    sample_failed: String(stats.failed),
                    failure_rate: String(stats.failureRate),
                    cooldown_until: String(cooldownUntil),
                });
            }
            const now = Date.now();
            if (cooldownUntil <= now) {
                return;
            }
            if (options.blockExpensiveDuringCooldown && isExpensiveCategory(category)) {
                writeGatewayEventAudit(directory, {
                    hook: "adaptive-delegation-policy",
                    stage: "guard",
                    reason_code: "adaptive_policy_expensive_delegation_blocked",
                    session_id: sid,
                    trace_id: traceId,
                    category,
                    cooldown_until: String(cooldownUntil),
                });
                throw new Error(`Blocked delegation: adaptive cooldown active due to recent failures; category=${category} is temporarily restricted.`);
            }
            const recent = getRecentDelegationOutcomes(options.windowMs);
            const hint = `[adaptive-delegation-policy] cooldown active; recent_failures=${stats.failed}/${stats.total}; prefer low-risk scoped delegation and explicit validation steps.`;
            args.prompt = prependHint(String(args.prompt ?? ""), hint);
            args.description = prependHint(String(args.description ?? ""), hint);
            writeGatewayEventAudit(directory, {
                hook: "adaptive-delegation-policy",
                stage: "state",
                reason_code: "adaptive_policy_hint_injected",
                session_id: sid,
                trace_id: traceId,
                category,
                recent_outcomes: String(recent.length),
                cooldown_until: String(cooldownUntil),
            });
        },
    };
}
