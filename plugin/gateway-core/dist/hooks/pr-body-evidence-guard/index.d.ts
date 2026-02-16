import type { GatewayHook } from "../registry.js";
export declare function createPrBodyEvidenceGuardHook(options: {
    directory: string;
    enabled: boolean;
    requireSummarySection: boolean;
    requireValidationSection: boolean;
    requireValidationEvidence: boolean;
    allowUninspectableBody: boolean;
    requiredMarkers: string[];
}): GatewayHook;
