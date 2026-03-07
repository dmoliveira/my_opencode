import type { GatewayHook } from "../registry.js";
export declare function createAdaptiveDelegationPolicyHook(options: {
    directory: string;
    enabled: boolean;
    windowMs: number;
    minSamples: number;
    highFailureRate: number;
    cooldownMs: number;
    blockExpensiveDuringCooldown: boolean;
}): GatewayHook;
