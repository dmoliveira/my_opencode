import type { GatewayHook } from "../registry.js";
export declare function createAgentDeniedToolEnforcerHook(options: {
    directory: string;
    enabled: boolean;
}): GatewayHook;
