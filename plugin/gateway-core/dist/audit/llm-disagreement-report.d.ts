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
export declare function parseGatewayAuditJsonl(text: string): GatewayAuditEvent[];
export declare function summarizeLlmDecisionDisagreements(events: GatewayAuditEvent[]): LlmDisagreementSummary;
