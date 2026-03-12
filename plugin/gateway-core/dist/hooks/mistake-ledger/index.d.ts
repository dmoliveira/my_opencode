import type { GatewayHook } from "../registry.js";
import type { LlmDecisionRuntime } from "../shared/llm-decision-runtime.js";
export declare function createMistakeLedgerHook(options: {
    directory: string;
    enabled: boolean;
    path: string;
    decisionRuntime?: LlmDecisionRuntime;
}): GatewayHook;
