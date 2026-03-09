export interface WorkflowScenarioResult {
  id: string
  workflow: string
  requestType: string
  description: string
  expectedAction: string
  actualAction: string
  correct: boolean
}

export interface WorkflowScenarioSummary {
  total: number
  correct: number
  accuracyPct: number
  byWorkflow: Array<{ workflow: string; total: number; correct: number; accuracyPct: number }>
}

export function summarizeWorkflowScenarioResults(results: WorkflowScenarioResult[]): WorkflowScenarioSummary {
  const byWorkflow = new Map<string, { total: number; correct: number }>()
  let correct = 0
  for (const result of results) {
    if (result.correct) {
      correct += 1
    }
    const current = byWorkflow.get(result.workflow) ?? { total: 0, correct: 0 }
    current.total += 1
    current.correct += result.correct ? 1 : 0
    byWorkflow.set(result.workflow, current)
  }
  const total = results.length
  const ratio = (value: number, denom: number): number => (denom > 0 ? Number(((value / denom) * 100).toFixed(1)) : 0)
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
  }
}

export function renderWorkflowScenarioMarkdown(summary: WorkflowScenarioSummary, results: WorkflowScenarioResult[]): string {
  const lines = [
    "# Workflow Scenario Reliability Report",
    "",
    `- Total scenarios: ${summary.total}`,
    `- Correct actions: ${summary.correct}`,
    `- Accuracy: ${summary.accuracyPct}%`,
    "",
    "## By Workflow",
    ...summary.byWorkflow.map((item) => `- ${item.workflow}: ${item.correct}/${item.total} (${item.accuracyPct}%)`),
    "",
    "## Scenario Results",
    ...results.map(
      (result) =>
        `- ${result.id}: ${result.correct ? "PASS" : "FAIL"} | ${result.workflow} | ${result.requestType} | expected=${result.expectedAction} actual=${result.actualAction}`,
    ),
  ]
  return `${lines.join("\n")}\n`
}
