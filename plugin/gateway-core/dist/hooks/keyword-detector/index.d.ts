import type { GatewayHook } from "../registry.js";
export type KeywordMode = "ultrawork" | "analyze" | "search";
export interface KeywordDetector {
    modeForSession(sessionId: string): KeywordMode | null;
}
export declare function createKeywordDetectorHook(options: {
    directory: string;
    enabled: boolean;
}): GatewayHook & KeywordDetector;
