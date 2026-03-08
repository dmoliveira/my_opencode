export interface DelegationStartInput {
    sessionId: string;
    subagentType: string;
    category: string;
    startedAt: number;
    traceId?: string;
}
export interface DelegationOutcomeInput {
    sessionId: string;
    status: "completed" | "failed";
    reasonCode?: string;
    endedAt: number;
    traceId?: string;
    subagentType?: string;
}
export interface DelegationOutcomeRecord {
    sessionId: string;
    subagentType: string;
    category: string;
    status: "completed" | "failed";
    reasonCode: string;
    startedAt: number;
    endedAt: number;
    durationMs: number;
    traceId?: string;
}
export declare function configureDelegationRuntimeState(options: {
    directory: string;
    persistState: boolean;
    stateFile: string;
    stateMaxEntries: number;
}): void;
export declare function registerDelegationStart(input: DelegationStartInput): void;
export declare function registerDelegationOutcome(input: DelegationOutcomeInput, maxEntries: number): DelegationOutcomeRecord | null;
export declare function clearDelegationSession(sessionId: string): void;
export declare function getRecentDelegationOutcomes(windowMs: number): DelegationOutcomeRecord[];
export declare function getDelegationFailureStats(windowMs: number): {
    total: number;
    failed: number;
    failureRate: number;
};
