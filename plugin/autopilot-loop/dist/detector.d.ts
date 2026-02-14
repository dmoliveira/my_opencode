import type { AutopilotLoopState, SessionMessage } from "./types.js";
export declare function escapeRegExp(value: string): string;
export declare function detectPromiseCompletion(text: string, promise: string): boolean;
export declare function extractLastAssistantText(messages: SessionMessage[]): string;
export declare function detectObjectiveCompletionSignal(text: string): boolean;
export declare function detectCompletion(state: AutopilotLoopState, assistantText: string): boolean;
