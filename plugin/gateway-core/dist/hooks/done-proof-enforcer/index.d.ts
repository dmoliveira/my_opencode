import type { GatewayHook } from "../registry.js";
import { type LlmDecisionRuntime } from "../shared/llm-decision-runtime.js";
export declare function createDoneProofEnforcerHook(options: {
    enabled: boolean;
    requiredMarkers: string[];
    requireLedgerEvidence: boolean;
    allowTextFallback: boolean;
    directory?: string;
    decisionRuntime?: LlmDecisionRuntime;
}): GatewayHook;
