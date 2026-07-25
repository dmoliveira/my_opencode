export interface DelegationStartInput {
    sessionId: string;
    childRunId?: string;
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
    childRunId?: string;
}
export interface DelegationOutcomeRecord {
    sessionId: string;
    childRunId?: string;
    subagentType: string;
    category: string;
    status: "completed" | "failed";
    reasonCode: string;
    startedAt: number;
    endedAt: number;
    durationMs: number;
    traceId?: string;
}
export interface DelegationPolicyProposalInput {
    sessionId: string;
    traceId?: string;
    subagentType: string;
    failures: number;
    samples: number;
    failureRate: number;
    originalCategory: string;
    proposedCategory: string;
    mode: "shadow" | "enforce";
    applied: boolean;
    createdAt: number;
}
export type DelegationPolicyProposalRecord = DelegationPolicyProposalInput;
export declare function configureDelegationRuntimeState(options: {
    directory: string;
    persistState: boolean;
    stateFile: string;
    stateMaxEntries: number;
}): void;
export declare function registerDelegationStart(input: DelegationStartInput): void;
export declare function clearActiveDelegation(input: {
    sessionId: string;
    childRunId?: string;
}): boolean;
export declare function registerDelegationOutcome(input: DelegationOutcomeInput, maxEntries: number): DelegationOutcomeRecord | null;
export declare function registerDelegationPolicyProposal(input: DelegationPolicyProposalInput): DelegationPolicyProposalRecord | null;
export declare function getRecentDelegationPolicyProposals(windowMs: number): DelegationPolicyProposalRecord[];
export declare function clearDelegationSession(sessionId: string): void;
export declare function getRecentDelegationOutcomes(windowMs: number): DelegationOutcomeRecord[];
export declare function getDelegationFailureStats(windowMs: number): {
    total: number;
    failed: number;
    failureRate: number;
};
