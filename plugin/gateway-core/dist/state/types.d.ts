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
export interface GatewayConciseModeState {
    mode: "off" | "lite" | "full" | "ultra" | "review" | "commit";
    source: string;
    sessionId: string;
    activatedAt: string;
    updatedAt: string;
}
export interface GatewayState {
    activeLoop: GatewayLoopState | null;
    conciseMode?: GatewayConciseModeState | null;
    lastUpdatedAt: string;
    source?: string;
}
