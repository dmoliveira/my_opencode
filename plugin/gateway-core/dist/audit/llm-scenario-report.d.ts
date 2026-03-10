export interface LlmScenarioFixture {
    id: string;
    hookId: string;
    requestType: string;
    description: string;
    expectedChar: string;
    expectedMeaning?: string;
}
export interface LlmScenarioResult extends LlmScenarioFixture {
    actualChar: string;
    actualMeaning?: string;
    accepted: boolean;
    correct: boolean;
    durationMs: number;
    raw?: string;
}
export interface LlmScenarioSummary {
    total: number;
    correct: number;
    accuracyPct: number;
    byHook: Array<{
        hookId: string;
        total: number;
        correct: number;
        accuracyPct: number;
    }>;
    byRequestType: Array<{
        requestType: string;
        total: number;
        correct: number;
        accuracyPct: number;
    }>;
}
export declare function summarizeLlmScenarioResults(results: LlmScenarioResult[]): LlmScenarioSummary;
export declare function renderLlmScenarioMarkdown(summary: LlmScenarioSummary, results: LlmScenarioResult[]): string;
