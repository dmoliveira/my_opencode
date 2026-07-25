import type { GatewayHook } from "../registry.js";
export declare function createDelegationOutcomeLearnerHook(options: {
    directory: string;
    enabled: boolean;
    mode: "shadow" | "enforce";
    windowMs: number;
    minSamples: number;
    highFailureRate: number;
    agentPolicyOverrides: Record<string, {
        minSamples?: number;
        highFailureRate?: number;
        protectCategories?: string[];
    }>;
}): GatewayHook;
