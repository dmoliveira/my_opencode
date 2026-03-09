export function parseGatewayAuditJsonl(text) {
    return String(text ?? "")
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => {
        try {
            return JSON.parse(line);
        }
        catch {
            return null;
        }
    })
        .filter((item) => Boolean(item));
}
function normalized(value) {
    return String(value ?? "").trim().toLowerCase();
}
export function summarizeLlmDecisionDisagreements(events) {
    const pairCounts = new Map();
    const hookCounts = new Map();
    for (const event of events) {
        if (normalized(event.reason_code) !== "llm_decision_disagreement") {
            continue;
        }
        const hook = normalized(event.hook) || "unknown";
        const deterministicMeaning = normalized(event.deterministic_decision_meaning) || "unknown";
        const aiMeaning = normalized(event.llm_decision_meaning) || "unknown";
        const key = `${hook}|${deterministicMeaning}|${aiMeaning}`;
        const current = pairCounts.get(key);
        if (current) {
            current.count += 1;
        }
        else {
            pairCounts.set(key, {
                hook,
                deterministicMeaning,
                aiMeaning,
                count: 1,
            });
        }
        hookCounts.set(hook, (hookCounts.get(hook) ?? 0) + 1);
    }
    const pairs = [...pairCounts.values()].sort((left, right) => right.count - left.count || left.hook.localeCompare(right.hook));
    const byHook = [...hookCounts.entries()]
        .map(([hook, count]) => ({ hook, count }))
        .sort((left, right) => right.count - left.count || left.hook.localeCompare(right.hook));
    return {
        total: pairs.reduce((sum, item) => sum + item.count, 0),
        byHook,
        pairs,
    };
}
