export type LlmDecisionMode = "disabled" | "shadow" | "assist" | "enforce";
export interface LlmDecisionRuntimeConfig {
    enabled: boolean;
    mode: LlmDecisionMode;
    hookModes: Record<string, LlmDecisionMode>;
    command: string;
    model: string;
    env: Record<string, string>;
    allowStandaloneOpencode: boolean;
    timeoutMs: number;
    failureCooldownMs: number;
    maxConcurrentDecisions: number;
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
    userContext?: string;
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
export interface DecisionComparisonAudit {
    directory: string;
    hookId: string;
    sessionId: string;
    traceId?: string;
    mode: LlmDecisionMode;
    deterministicMeaning: string;
    aiMeaning: string;
    deterministicValue?: string;
    aiValue?: string;
}
export interface LlmDecisionRuntime {
    config: LlmDecisionRuntimeConfig;
    decide(request: SingleCharDecisionRequest): Promise<SingleCharDecisionResult>;
}
export declare function resolveLlmDecisionRuntimeConfigForHook(config: LlmDecisionRuntimeConfig, hookId: string): LlmDecisionRuntimeConfig;
type RunnerResult = {
    stdout: string;
    stderr: string;
};
interface RuntimeOptions {
    directory: string;
    config: LlmDecisionRuntimeConfig;
    runner?: (args: string[], timeoutMs: number, cwd: string, env: Record<string, string>) => Promise<RunnerResult>;
}
export declare function buildLlmDecisionFallbackNotice(failureCooldownMs: number): string;
export declare function peekLlmDecisionFallbackNotice(directory: string, sessionId: string): string;
export declare function consumeLlmDecisionFallbackNotice(directory: string, sessionId: string): string;
export declare function truncateDecisionText(text: string, maxChars: number): string;
export declare function buildCompactDecisionCacheKey(options: {
    prefix: string;
    parts?: string[];
    text: string;
    maxTextChars?: number;
}): string;
export declare function buildSingleCharDecisionPrompt(request: {
    instruction: string;
    context: string;
    userContext?: string;
    allowedChars: string[];
}): string;
export declare function parseSingleCharDecision(raw: string, allowedChars: string[]): string;
export declare function shouldAuditDecisionDisagreement(deterministicMeaning: string, aiMeaning: string): boolean;
export declare function writeDecisionComparisonAudit(input: DecisionComparisonAudit): void;
export declare function createLlmDecisionRuntime(options: RuntimeOptions): LlmDecisionRuntime;
export {};
