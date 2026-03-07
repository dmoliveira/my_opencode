const activeBySession = new Map();
const timeline = [];
function pushTimeline(record, maxEntries) {
    timeline.push(record);
    if (maxEntries <= 0) {
        timeline.splice(0, timeline.length);
        return;
    }
    while (timeline.length > maxEntries) {
        timeline.shift();
    }
}
export function registerDelegationStart(input) {
    if (!input.sessionId.trim()) {
        return;
    }
    activeBySession.set(input.sessionId, {
        subagentType: input.subagentType,
        category: input.category,
        startedAt: input.startedAt,
    });
}
export function registerDelegationOutcome(input, maxEntries) {
    const active = activeBySession.get(input.sessionId);
    if (!active) {
        return null;
    }
    activeBySession.delete(input.sessionId);
    const durationMs = Math.max(0, input.endedAt - active.startedAt);
    const record = {
        sessionId: input.sessionId,
        subagentType: active.subagentType,
        category: active.category,
        status: input.status,
        reasonCode: input.reasonCode ??
            (input.status === "failed"
                ? "delegation_runtime_failure"
                : "delegation_runtime_completed"),
        startedAt: active.startedAt,
        endedAt: input.endedAt,
        durationMs,
    };
    pushTimeline(record, maxEntries);
    return record;
}
export function clearDelegationSession(sessionId) {
    activeBySession.delete(sessionId);
}
export function getRecentDelegationOutcomes(windowMs) {
    const minTs = Date.now() - Math.max(0, windowMs);
    return timeline.filter((item) => item.endedAt >= minTs);
}
export function getDelegationFailureStats(windowMs) {
    const outcomes = getRecentDelegationOutcomes(windowMs);
    const total = outcomes.length;
    const failed = outcomes.filter((item) => item.status === "failed").length;
    return {
        total,
        failed,
        failureRate: total > 0 ? failed / total : 0,
    };
}
