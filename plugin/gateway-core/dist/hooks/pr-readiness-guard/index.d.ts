import type { GatewayHook } from "../registry.js";
export declare function createPrReadinessGuardHook(options: {
    directory: string;
    enabled: boolean;
    requireCleanWorktree: boolean;
    requireValidationEvidence: boolean;
    requiredMarkers: string[];
}): GatewayHook;
