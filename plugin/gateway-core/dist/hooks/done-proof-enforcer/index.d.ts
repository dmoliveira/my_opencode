import type { GatewayHook } from "../registry.js";
export declare function createDoneProofEnforcerHook(options: {
    enabled: boolean;
    requiredMarkers: string[];
}): GatewayHook;
