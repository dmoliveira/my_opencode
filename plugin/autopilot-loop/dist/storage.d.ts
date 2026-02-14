import type { AutopilotLoopState } from "./types.js";
export declare function resolveStatePath(directory: string, stateFile?: string): string;
export declare function loadState(directory: string, stateFile?: string): AutopilotLoopState | null;
export declare function saveState(directory: string, state: AutopilotLoopState, stateFile?: string): void;
export declare function clearState(directory: string, stateFile?: string): void;
export declare function incrementIteration(directory: string, state: AutopilotLoopState, stateFile?: string): AutopilotLoopState;
