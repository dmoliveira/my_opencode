import type { GatewayHook } from "../registry.js";
import type { LlmDecisionRuntime } from "../shared/llm-decision-runtime.js";
export declare function createPrBodyEvidenceGuardHook(options: {
    directory: string;
    enabled: boolean;
    requireSummarySection: boolean;
    requireValidationSection: boolean;
    requireValidationEvidence: boolean;
    allowUninspectableBody: boolean;
    requiredMarkers: string[];
    decisionRuntime?: LlmDecisionRuntime;
}): GatewayHook;
