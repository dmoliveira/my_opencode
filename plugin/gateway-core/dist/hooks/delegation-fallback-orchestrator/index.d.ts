import type { GatewayHook } from "../registry.js";
export declare function createDelegationFallbackOrchestratorHook(options: {
    directory: string;
    enabled: boolean;
}): GatewayHook;
