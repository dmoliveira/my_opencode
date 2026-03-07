import type { GatewayHook } from "../registry.js";
export declare function createAgentDiscoverabilityInjectorHook(options: {
    directory: string;
    enabled: boolean;
    cooldownMs: number;
}): GatewayHook;
