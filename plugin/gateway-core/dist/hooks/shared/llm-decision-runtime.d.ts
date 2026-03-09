export type LlmDecisionMode = "disabled" | "shadow" | "assist" | "enforce";
export interface LlmDecisionRuntimeConfig {
    enabled: boolean;
    mode: LlmDecisionMode;
    command: string;
    model: string;
    timeoutMs: number;
    maxPromptChars: number;
    maxContextChars: number;
    enableCache: boolean;
    cacheTtlMs: number;
    maxCacheEntries: number;
}
export interface SingleCharDecisionRequest {
    hookId: string;
    sessionId: string;
    traceId?: string;
    templateId: string;
    instruction: string;
    context: string;
    allowedChars: string[];
    decisionMeaning?: Record<string, string>;
    cacheKey?: string;
}
export interface SingleCharDecisionResult {
    mode: LlmDecisionMode;
    accepted: boolean;
    char: string;
    raw: string;
    durationMs: number;
    model: string;
    templateId: string;
    meaning?: string;
    cached?: boolean;
    skippedReason?: string;
    error?: string;
}
export interface LlmDecisionRuntime {
    config: LlmDecisionRuntimeConfig;
    decide(request: SingleCharDecisionRequest): Promise<SingleCharDecisionResult>;
}
type RunnerResult = {
    stdout: string;
    stderr: string;
};
interface RuntimeOptions {
    directory: string;
    config: LlmDecisionRuntimeConfig;
    runner?: (args: string[], timeoutMs: number, cwd: string) => Promise<RunnerResult>;
}
export declare function truncateDecisionText(text: string, maxChars: number): string;
export declare function buildSingleCharDecisionPrompt(request: {
    instruction: string;
    context: string;
    allowedChars: string[];
}): string;
export declare function parseSingleCharDecision(raw: string, allowedChars: string[]): string;
export declare function createLlmDecisionRuntime(options: RuntimeOptions): LlmDecisionRuntime;
export {};
