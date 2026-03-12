import type { GatewayHook } from "../registry.js";
import { type LlmDecisionRuntime } from "../shared/llm-decision-runtime.js";
export declare function createValidationEvidenceLedgerHook(options: {
    directory: string;
    enabled: boolean;
    decisionRuntime?: LlmDecisionRuntime;
}): GatewayHook;
