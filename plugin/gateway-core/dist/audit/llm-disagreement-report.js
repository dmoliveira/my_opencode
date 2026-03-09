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
export function recommendLlmRolloutActions(summary) {
    return summary.byHook.map(({ hook, count }) => {
        if (count >= 10) {
            return {
                hook,
                action: "investigate",
                reason: "high disagreement volume; keep in shadow and inspect top disagreement pairs",
                disagreementCount: count,
            };
        }
        if (count >= 4) {
            return {
                hook,
                action: "tune",
                reason: "moderate disagreement volume; refine prompt, context shaping, or fallback policy",
                disagreementCount: count,
            };
        }
        if (count >= 1) {
            return {
                hook,
                action: "observe",
                reason: "low disagreement volume; continue shadow sampling before promotion",
                disagreementCount: count,
            };
        }
        return {
            hook,
            action: "promote_candidate",
            reason: "no disagreements recorded in current sample; candidate for wider assist-mode evaluation",
            disagreementCount: count,
        };
    });
}
export function buildLlmRolloutReport(events) {
    const summary = summarizeLlmDecisionDisagreements(events);
    return {
        summary,
        recommendations: recommendLlmRolloutActions(summary),
    };
}
export function renderLlmRolloutMarkdown(report) {
    const lines = [
        "# LLM Disagreement Rollout Report",
        "",
        `- Total disagreements: ${report.summary.total}`,
        `- Hooks with disagreements: ${report.summary.byHook.length}`,
        "",
        "## Recommendations",
    ];
    if (report.recommendations.length === 0) {
        lines.push("", "- No disagreement data found.");
    }
    else {
        for (const item of report.recommendations) {
            lines.push("", `- ${item.hook}: ${item.action} (${item.disagreementCount})`, `  - ${item.reason}`);
        }
    }
    lines.push("", "## Top disagreement pairs");
    if (report.summary.pairs.length === 0) {
        lines.push("", "- No disagreement pairs found.");
    }
    else {
        for (const pair of report.summary.pairs.slice(0, 10)) {
            lines.push("", `- ${pair.hook}: ${pair.deterministicMeaning} -> ${pair.aiMeaning} (${pair.count})`);
        }
    }
    return `${lines.join("\n")}\n`;
}
