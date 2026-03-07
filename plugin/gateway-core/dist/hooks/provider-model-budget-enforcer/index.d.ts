import type { GatewayHook } from "../registry.js";
export declare function createProviderModelBudgetEnforcerHook(options: {
    directory: string;
    enabled: boolean;
    windowMs: number;
    maxDelegationsPerWindow: number;
    maxEstimatedTokensPerWindow: number;
    maxPerModelDelegationsPerWindow: number;
}): GatewayHook;
