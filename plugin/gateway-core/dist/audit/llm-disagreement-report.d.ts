export interface GatewayAuditEvent {
    hook?: unknown;
    reason_code?: unknown;
    deterministic_decision_meaning?: unknown;
    deterministic_decision_value?: unknown;
    llm_decision_meaning?: unknown;
    llm_decision_value?: unknown;
}
export interface LlmDisagreementSummaryEntry {
    hook: string;
    deterministicMeaning: string;
    aiMeaning: string;
    count: number;
}
export interface LlmDisagreementSummary {
    total: number;
    byHook: Array<{
        hook: string;
        count: number;
    }>;
    pairs: LlmDisagreementSummaryEntry[];
}
export interface LlmRolloutRecommendation {
    hook: string;
    action: "investigate" | "tune" | "observe" | "promote_candidate";
    reason: string;
    disagreementCount: number;
    thresholds: LlmRolloutThresholds;
}
export interface LlmRolloutThresholds {
    investigateAt: number;
    tuneAt: number;
    observeAt: number;
}
export interface LlmRolloutThresholdMap {
    default?: Partial<LlmRolloutThresholds>;
    hooks?: Record<string, Partial<LlmRolloutThresholds>>;
}
export interface LlmRolloutReport {
    summary: LlmDisagreementSummary;
    recommendations: LlmRolloutRecommendation[];
}
export declare function parseGatewayAuditJsonl(text: string): GatewayAuditEvent[];
export declare function summarizeLlmDecisionDisagreements(events: GatewayAuditEvent[]): LlmDisagreementSummary;
export declare function recommendLlmRolloutActions(summary: LlmDisagreementSummary, overrides?: LlmRolloutThresholdMap): LlmRolloutRecommendation[];
export declare function buildLlmRolloutReport(events: GatewayAuditEvent[], overrides?: LlmRolloutThresholdMap): LlmRolloutReport;
export declare function renderLlmRolloutMarkdown(report: LlmRolloutReport): string;
