import type { GatewayHook } from "../registry.js";
export declare function createScopeDriftGuardHook(options: {
    directory: string;
    enabled: boolean;
    allowedPaths: string[];
    blockOnDrift: boolean;
}): GatewayHook;
