import type { GatewayHook } from "../registry.js";
export declare function createStalePathHealerHook(options: {
    directory: string;
    enabled: boolean;
}): GatewayHook;
