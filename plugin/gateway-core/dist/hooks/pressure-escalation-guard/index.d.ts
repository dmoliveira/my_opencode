import type { GatewayHook } from "../registry.js";
export declare function createPressureEscalationGuardHook(options: {
    directory: string;
    enabled: boolean;
    maxContinueBeforeBlock: number;
    blockedSubagentTypes: string[];
    allowPromptPatterns: string[];
    sampleContinueCount?: () => number;
}): GatewayHook;
