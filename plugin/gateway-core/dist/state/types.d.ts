export interface GatewayLoopState {
    active: boolean;
    sessionId: string;
    objective: string;
    doneCriteria?: string[];
    ignoredCompletionCycles?: number;
    completionMode: "promise" | "objective";
    completionPromise: string;
    iteration: number;
    maxIterations: number;
    startedAt: string;
}
export interface GatewayState {
    activeLoop: GatewayLoopState | null;
    lastUpdatedAt: string;
    source?: string;
}
