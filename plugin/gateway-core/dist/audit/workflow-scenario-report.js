export function summarizeWorkflowScenarioResults(results) {
    const byWorkflow = new Map();
    let correct = 0;
    for (const result of results) {
        if (result.correct) {
            correct += 1;
        }
        const current = byWorkflow.get(result.workflow) ?? { total: 0, correct: 0 };
        current.total += 1;
        current.correct += result.correct ? 1 : 0;
        byWorkflow.set(result.workflow, current);
    }
    const total = results.length;
    const ratio = (value, denom) => (denom > 0 ? Number(((value / denom) * 100).toFixed(1)) : 0);
    return {
        total,
        correct,
        accuracyPct: ratio(correct, total),
        byWorkflow: [...byWorkflow.entries()].map(([workflow, item]) => ({
            workflow,
            total: item.total,
            correct: item.correct,
            accuracyPct: ratio(item.correct, item.total),
        })),
    };
}
export function renderWorkflowScenarioMarkdown(summary, results) {
    const failures = results.filter((result) => !result.correct);
    const weakestWorkflow = summary.byWorkflow
        .filter((item) => item.correct < item.total)
        .sort((left, right) => left.accuracyPct - right.accuracyPct || right.total - left.total || left.workflow.localeCompare(right.workflow))[0];
    const lines = [
        "# Workflow Scenario Reliability Report",
        "",
        `- Total scenarios: ${summary.total}`,
        `- Correct actions: ${summary.correct}`,
        `- Overall accuracy (correct / total scenarios): ${summary.accuracyPct}%`,
        "- By Workflow shows correct / total scenario counts for each workflow bucket.",
        "",
        "## By Workflow (correct / total scenarios per workflow)",
        ...summary.byWorkflow.map((item) => `- ${item.workflow}: ${item.correct}/${item.total} (${item.accuracyPct}%)`),
    ];
    if (failures.length > 0) {
        lines.push("", "## Failure focus");
        if (weakestWorkflow) {
            lines.push("", `- Start with \`${weakestWorkflow.workflow}\` (${weakestWorkflow.correct}/${weakestWorkflow.total}); it is the weakest workflow bucket in this run.`);
        }
        lines.push(...failures.flatMap((result) => [
            "",
            `- ${result.id}: FAIL | ${result.workflow} | ${result.requestType} | expected=${result.expectedAction} actual=${result.actualAction}`,
        ]));
    }
    lines.push("", "## Scenario Results (one row per scenario)", ...results.map((result) => `- ${result.id}: ${result.correct ? "PASS" : "FAIL"} | ${result.workflow} | ${result.requestType} | expected=${result.expectedAction} actual=${result.actualAction}`));
    return `${lines.join("\n")}\n`;
}
