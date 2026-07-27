export interface GatewayLoopState {
    [key: string]: unknown;
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
export interface GatewayConciseModeState {
    [key: string]: unknown;
    mode: "off" | "lite" | "full" | "ultra" | "review" | "commit";
    source: string;
    sessionId: string;
    activatedAt: string;
    updatedAt: string;
}
export interface GatewayState {
    [key: string]: unknown;
    activeLoop: GatewayLoopState | null;
    conciseMode?: GatewayConciseModeState | null;
    lastUpdatedAt: string;
    source?: string;
}
