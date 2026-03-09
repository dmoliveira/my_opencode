export interface WorkflowScenarioResult {
    id: string;
    workflow: string;
    requestType: string;
    description: string;
    expectedAction: string;
    actualAction: string;
    correct: boolean;
}
export interface WorkflowScenarioSummary {
    total: number;
    correct: number;
    accuracyPct: number;
    byWorkflow: Array<{
        workflow: string;
        total: number;
        correct: number;
        accuracyPct: number;
    }>;
}
export declare function summarizeWorkflowScenarioResults(results: WorkflowScenarioResult[]): WorkflowScenarioSummary;
export declare function renderWorkflowScenarioMarkdown(summary: WorkflowScenarioSummary, results: WorkflowScenarioResult[]): string;
