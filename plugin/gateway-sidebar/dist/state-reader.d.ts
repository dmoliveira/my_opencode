export declare const EXECUTION_STATUS_FILE = "gateway-core.state.json";
export declare const EXECUTION_STATUS_DIRECTORY = ".opencode";
export declare const MAX_STATE_BYTES: number;
export declare const MAX_LABEL_CHARS = 160;
export declare const MAX_STATUS_AGE_MS: number;
export type ExecutionStatusEntry = {
    sessionId: string;
    last: string;
    next: string;
    updatedAt: string;
};
export type ExecutionStatusSnapshot = {
    version: 1;
    sessions: Record<string, ExecutionStatusEntry>;
};
export declare function parseExecutionStatus(value: unknown): ExecutionStatusSnapshot | null;
export declare function executionStatusPath(directory: string): string;
export declare function readExecutionStatus(directory: string): Promise<ExecutionStatusSnapshot | null>;
export declare function statusForSession(snapshot: ExecutionStatusSnapshot | null, sessionId: string, now?: number): ExecutionStatusEntry | null;
