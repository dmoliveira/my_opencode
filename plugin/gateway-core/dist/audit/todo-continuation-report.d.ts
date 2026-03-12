import { type GatewayAuditEvent } from "./llm-disagreement-report.js";
export interface TodoContinuationReasonCount {
    reasonCode: string;
    count: number;
}
export interface TodoContinuationSessionSummary {
    sessionId: string;
    lastTs?: string;
    injected: number;
    todowriteSignals: number;
    probeRetained: number;
    stopGuards: number;
    noPending: number;
    probeFailures: number;
    injectFailures: number;
    llmDecisions: number;
    llmShadows: number;
    maxOpenTodoCount: number;
    lastReasonCode?: string;
}
export interface TodoContinuationReport {
    metadata?: {
        generatedAt?: string;
        sourceAuditPath?: string;
        worktreePath?: string;
        branch?: string;
        invalidLines?: number;
        sourceAuditShared?: boolean;
        sessionLimit?: number;
    };
    totalEvents: number;
    totalSessions: number;
    reasonCounts: TodoContinuationReasonCount[];
    sessions: TodoContinuationSessionSummary[];
}
export interface TodoContinuationParsedReport {
    report: TodoContinuationReport;
    invalidLines: number;
}
export declare function buildTodoContinuationReport(events: GatewayAuditEvent[], options?: {
    sessionLimit?: number;
}): TodoContinuationReport;
export declare function parseTodoContinuationReport(text: string, options?: {
    sessionLimit?: number;
}): TodoContinuationParsedReport;
export declare function renderTodoContinuationMarkdown(report: TodoContinuationReport): string;
