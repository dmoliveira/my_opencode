const DEFAULT_THRESHOLDS = {
    investigateAt: 10,
    tuneAt: 4,
    observeAt: 1,
};
export function parseGatewayAuditJsonlWithDiagnostics(text) {
    const events = [];
    let invalidLines = 0;
    for (const line of String(text ?? "")
        .split(/\r?\n/)
        .map((item) => item.trim())
        .filter(Boolean)) {
        try {
            events.push(JSON.parse(line));
        }
        catch {
            invalidLines += 1;
        }
    }
    return { events, invalidLines };
}
export function parseGatewayAuditJsonl(text) {
    return parseGatewayAuditJsonlWithDiagnostics(text).events;
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
function resolvedThresholds(hook, overrides) {
    const normalizedHook = hook.trim().toLowerCase();
    const defaultOverrides = overrides?.default ?? {};
    const hookOverrides = overrides?.hooks?.[normalizedHook] ?? overrides?.hooks?.[hook] ?? {};
    const merged = {
        investigateAt: hookOverrides.investigateAt ?? defaultOverrides.investigateAt ?? DEFAULT_THRESHOLDS.investigateAt,
        tuneAt: hookOverrides.tuneAt ?? defaultOverrides.tuneAt ?? DEFAULT_THRESHOLDS.tuneAt,
        observeAt: hookOverrides.observeAt ?? defaultOverrides.observeAt ?? DEFAULT_THRESHOLDS.observeAt,
    };
    return merged;
}
export function recommendLlmRolloutActions(summary, overrides) {
    const actions = [];
    for (const { hook, count } of summary.byHook) {
        const thresholds = resolvedThresholds(hook, overrides);
        if (count >= thresholds.investigateAt) {
            actions.push({
                hook,
                action: "investigate",
                reason: "high disagreement volume; keep in shadow and inspect top disagreement pairs",
                disagreementCount: count,
                thresholds,
            });
            continue;
        }
        if (count >= thresholds.tuneAt) {
            actions.push({
                hook,
                action: "tune",
                reason: "moderate disagreement volume; refine prompt, context shaping, or fallback policy",
                disagreementCount: count,
                thresholds,
            });
            continue;
        }
        if (count >= thresholds.observeAt) {
            actions.push({
                hook,
                action: "observe",
                reason: "low disagreement volume; continue shadow sampling before promotion",
                disagreementCount: count,
                thresholds,
            });
        }
    }
    return actions;
}
export function buildLlmRolloutReport(events, overrides) {
    const summary = summarizeLlmDecisionDisagreements(events);
    return {
        summary,
        recommendations: recommendLlmRolloutActions(summary, overrides),
    };
}
export function renderLlmRolloutMarkdown(report) {
    const lines = [
        "# LLM Disagreement Rollout Report",
        "",
        ...(report.metadata?.generatedAt ? [`- Generated at: ${report.metadata.generatedAt}`] : []),
        ...(report.metadata?.branch ? [`- Branch: \`${report.metadata.branch}\``] : []),
        ...(report.metadata?.worktreePath ? [`- Worktree: \`${report.metadata.worktreePath}\``] : []),
        ...(report.metadata?.sourceAuditPath ? [`- Source audit: \`${report.metadata.sourceAuditPath}\``] : []),
        ...(report.metadata?.sourceAuditShared ? ["- Audit source scope: shared primary repo audit feed"] : []),
        ...(typeof report.metadata?.invalidLines === "number"
            ? [`- Invalid audit lines skipped: ${report.metadata.invalidLines}`]
            : []),
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
            lines.push("", `- ${item.hook}: ${item.action} (${item.disagreementCount})`, `  - ${item.reason}`, `  - thresholds: investigate>=${item.thresholds.investigateAt}, tune>=${item.thresholds.tuneAt}, observe>=${item.thresholds.observeAt}`);
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
