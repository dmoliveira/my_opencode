export function summarizeLlmScenarioResults(results) {
    const byHook = new Map();
    const byRequestType = new Map();
    let correct = 0;
    for (const result of results) {
        if (result.correct) {
            correct += 1;
        }
        const hook = byHook.get(result.hookId) ?? { total: 0, correct: 0 };
        hook.total += 1;
        hook.correct += result.correct ? 1 : 0;
        byHook.set(result.hookId, hook);
        const requestType = byRequestType.get(result.requestType) ?? { total: 0, correct: 0 };
        requestType.total += 1;
        requestType.correct += result.correct ? 1 : 0;
        byRequestType.set(result.requestType, requestType);
    }
    const total = results.length;
    const ratio = (value, denom) => (denom > 0 ? Number(((value / denom) * 100).toFixed(1)) : 0);
    return {
        total,
        correct,
        accuracyPct: ratio(correct, total),
        byHook: [...byHook.entries()]
            .map(([hookId, item]) => ({ hookId, total: item.total, correct: item.correct, accuracyPct: ratio(item.correct, item.total) }))
            .sort((a, b) => a.hookId.localeCompare(b.hookId)),
        byRequestType: [...byRequestType.entries()]
            .map(([requestType, item]) => ({ requestType, total: item.total, correct: item.correct, accuracyPct: ratio(item.correct, item.total) }))
            .sort((a, b) => a.requestType.localeCompare(b.requestType)),
    };
}
export function renderLlmScenarioMarkdown(summary, results) {
    const failures = results.filter((result) => !result.correct);
    const weakestHook = summary.byHook
        .filter((item) => item.correct < item.total)
        .sort((left, right) => left.accuracyPct - right.accuracyPct || right.total - left.total || left.hookId.localeCompare(right.hookId))[0];
    const lines = [
        "# LLM Scenario Reliability Report",
        "",
        `- Total scenarios: ${summary.total}`,
        `- Correct decisions: ${summary.correct}`,
        `- Overall accuracy (correct / total scenarios): ${summary.accuracyPct}%`,
        "- By Hook and By Request Type sections show correct / total scenario counts for each bucket.",
        "",
        "## By Hook (correct / total scenarios per hook)",
    ];
    for (const item of summary.byHook) {
        lines.push(`- ${item.hookId}: ${item.correct}/${item.total} (${item.accuracyPct}%)`);
    }
    lines.push("", "## By Request Type (correct / total scenarios per request type)");
    for (const item of summary.byRequestType) {
        lines.push(`- ${item.requestType}: ${item.correct}/${item.total} (${item.accuracyPct}%)`);
    }
    if (failures.length > 0) {
        lines.push("", "## Failure focus");
        if (weakestHook) {
            lines.push("", `- Start with \`${weakestHook.hookId}\` (${weakestHook.correct}/${weakestHook.total}); it is the weakest hook bucket in this run.`);
        }
        for (const result of failures) {
            lines.push("", `- ${result.id}: FAIL | ${result.hookId} | ${result.requestType} | expected=${result.expectedChar} actual=${result.actualChar || "(none)"}`);
        }
    }
    lines.push("", "## Scenario Results (one row per scenario)");
    for (const result of results) {
        lines.push(`- ${result.id}: ${result.correct ? "PASS" : "FAIL"} | ${result.hookId} | ${result.requestType} | expected=${result.expectedChar} actual=${result.actualChar || "(none)"} | ${result.durationMs}ms`);
    }
    return `${lines.join("\n")}\n`;
}
